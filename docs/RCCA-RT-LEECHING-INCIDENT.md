# RCCA: 67 RT Cross-Seed Torrents Leeching — Root Cause Investigation

**Date:** 2026-06-24  
**Discovered:** During j28 lead session (emergency stop)  
**Symptom:** 67 RT items in downloading/leeching state; none should be downloading  
**Immediate action:** `docker restart rtorrent_vpn` — confirmed `leeching=0` after restart

---

## Symptom

During j28 lead session preparation, RT was queried for state. Result:
- `leeching=67` (should be 0)
- `stopped=82` (pre-existing OP-29 items — never reached seeding state)
- 65 of 67 stopped via XMLRPC `d.stop`; 2 required container restart
- All 67 were cross-seed items (category `cross-seed/`)

These items had been leeching for an unknown duration prior to this session. The j27 agent failed to detect them, misreporting all stopped+leeching items as "normal active downloads."

---

## Root Cause

### Proximate cause: `rt_apply_directory_repoint(..., restart=True)` on incomplete items

**File:** `src/hashall/rtorrent.py`, lines 536–568

```python
def rt_apply_directory_repoint(
    torrent_hash, target_directory, *, rpc_url=..., restart=True, timeout=60
) -> list[str]:
    calls = [
        ("d.stop", torrent_hash),
        ("d.close", torrent_hash),
        ("d.directory.set", torrent_hash, target_directory),
        ("d.save_full_session", torrent_hash),
        ("session.save",),
        ("d.open", torrent_hash),
    ]
    if restart:
        calls.append(("d.start", torrent_hash))  # ← unconditional; no d.complete check
```

The function calls `d.start` unconditionally whenever `restart=True`. It does not:
- Check `d.complete` before starting
- Run `d.check_hash` to verify file presence
- Wait for hash verification to complete

### Triggering event: j22 lane1b execute

**File:** `src/hashall/lane1_execute.py`, lines 237–239 and 515–517

```python
rt_apply_directory_repoint(
    h, canonical_path,
    rpc_url=rt_rpc_url, restart=True,   # ← always restarts
)
```

j22 executed lane1b on cross-seed dup items (those identified as needing directory repoint from bare `<tracker>/` to `cross-seed/<tracker>/`). These items had:
- `d.complete = 0` — RT had never run `d.check_hash` on them
- `d.completed_bytes ≈ 0` — no data verified by RT
- Files present on disk as hardlinks from the source payload

When `rt_apply_directory_repoint(..., restart=True)` was called, the sequence:
1. `d.stop` — stopped the (already stopped) torrent
2. `d.close` — released session handle
3. `d.directory.set` — set new canonical path
4. `d.save_full_session` / `session.save` — persisted new path to fastresume
5. `d.open` — reopened the torrent
6. `d.start` — **started the torrent despite `d.complete=0`**

Because `d.complete=0` and no hash check had been done, RT interpreted the torrent as incomplete and began downloading missing pieces from trackers. The hardlinked files on disk were not recognized as satisfying the torrent's data requirements until `d.check_hash` is run.

### Why `d.complete=0` for cross-seed items

Cross-seed daemon (autobrr/cross-seed tool) injects torrents into RT in **stopped state** with `d.complete=0`. RT does not automatically hash-check new torrents unless configured to do so. The cross-seed workflow relies on a `hashDone` event hook to verify files and start seeding; if this hook is not fired (or not configured), items remain `d.complete=0` indefinitely.

OP-10 records that the `event.download.hash_done` hook was implemented in `rtorrent.rc` but not yet live (never restarted to activate). This confirms the hook path was never working.

### Secondary issue: `rt_recheck_torrent` also calls `d.start` unconditionally

**File:** `src/hashall/rtorrent.py`, lines 571–590

```python
def rt_recheck_torrent(torrent_hash, ...) -> list[str]:
    calls = [
        ("d.stop", torrent_hash),
        ("d.close", torrent_hash),
        ("d.check_hash", torrent_hash),
        ("d.open", torrent_hash),
        ("d.start", torrent_hash),  # ← unconditional after check_hash
    ]
```

`rt_recheck_torrent` does run `d.check_hash` first, but it issues `d.start` in the same multicall batch — before the hash check completes. If `d.complete` is still 0 when `d.start` executes, RT begins downloading. This is a latent bug that has not yet caused a known incident.

---

## Scope

All callers of `rt_apply_directory_repoint` pass `restart=True` (default):

| File | Lines | Context |
|------|-------|---------|
| `lane1_execute.py` | 237, 515 | Lane 1a/1b cross-seed repoint |
| `save_path_repair.py` | 608 | Save path repair execute |
| `hitchhiker_split.py` | 320 | Hitchhiker split execute |
| `save_path_recovery.py` | 446 | Save path recovery execute |
| `nested_folder_repair.py` | 520 | Nested folder repair execute |
| `path_normalize.py` | 628, 691 | Path normalize (uses `plan.rt_should_restart`) |
| `cli.py` | 3989, 4043, 5574, 6214 | Direct CLI repoint commands |

Any of these callers that process items with `d.complete=0` will trigger the same leeching behavior.

---

## Fix Plan

### Fix 1 (primary): Guard `d.start` in `rt_apply_directory_repoint`

Add a `check_before_start: bool = False` parameter. When True:
1. After `d.open`, call `d.check_hash`
2. Poll `d.hashing` until 0 (with timeout)
3. Only call `d.start` if `d.complete == 1`
4. If `d.complete == 0` after hashing, raise an error or return a warning — do NOT start

The parameter should be `False` by default for backwards compatibility, but all mutation callers that touch cross-seed items must pass `check_before_start=True`.

Alternatively (simpler and safer): change the default of `restart` to `False` and require all callers to explicitly pass `restart=True`. This forces caller awareness.

### Fix 2 (secondary): Fix `rt_recheck_torrent`

Separate the `d.check_hash` call from the `d.start` call. After `d.check_hash`, poll until `d.hashing==0`, then only call `d.start` if `d.complete==1`. The existing `_rt_health_check` helper in `lane1_execute.py` implements this polling logic and should be promoted to `rtorrent.py` as a shared function.

### Fix 3 (all callers): Update `lane1_execute.py`

Before calling `rt_apply_directory_repoint`:
- Query `d.complete` for the item
- If `d.complete == 0`, call the new `check_before_start=True` path (or call `rt_safe_check_and_start` directly)
- If `d.complete == 1`, the existing `restart=True` path is safe

### Validation gate

All fixes must go through 4-gate validation (OP-25 gate applies):
- Gate 0: incident recovery (complete — RT restarted, leeching=0)
- Gate 1: editable install pinned to CR worktree, tests pass, state snapshot
- Gate 2: dry-run (assert that `d.complete` is checked before `d.start` in affected paths)
- Gate 3: single-item pilot with a known `d.complete=0` cross-seed item
- Gate 4: batch execution with human sign-off between batches

---

## Timeline

| Time | Event |
|------|-------|
| j22 (2026-06-18 ~09:20) | `lane1b-execute` ran on 67 cross-seed dup items; `rt_apply_directory_repoint(..., restart=True)` called; items began downloading |
| j27 session | j27 agent queried RT state, saw leeching items, misclassified as "normal active downloads" |
| j28 lead session (2026-06-24) | Lead identified 67 leeching items during OP-29 investigation; issued emergency stop |
| 2026-06-24 | 65/67 stopped via XMLRPC; 2 required `docker restart rtorrent_vpn`; confirmed `leeching=0` |

---

## Lessons

1. **`d.start` must never be called without first verifying `d.complete==1`** for any item that may be `d.complete=0`. Cross-seed items are always `d.complete=0` until hash-checked.

2. **Mutation executors must check `d.complete` before calling `d.start`**, especially for items injected by cross-seed daemon.

3. **`rt_recheck_torrent` is latently broken** — issues `d.start` in the same multicall as `d.check_hash`, before hashing completes. Must be split into two phases.

4. **`_rt_health_check` in `lane1_execute.py`** already implements the correct polling pattern. It should be promoted to `rtorrent.py` as `rt_poll_until_seeding()` and used by all callers.

5. **The `hashDone` hook in `rtorrent.rc` was never activated** (OP-10). If it were active, cross-seed items would auto-verify and auto-start correctly. Until OP-10 is resolved, all mutation paths must perform explicit hash-check-then-conditionally-start.
