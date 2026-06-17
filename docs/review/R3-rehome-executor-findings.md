# R3 — Rehome Executor + Planner + View Builder Audit

**Job:** j09  
**Task:** J09-T03  
**Auditor:** opencode-deepseek-v4-pro  
**Date:** 2026-06-17  
**Scope:** `src/rehome/executor.py`, `src/rehome/planner.py`, `src/rehome/view_builder.py`

---

## Summary

11 findings: 1 critical, 3 high, 4 medium, 3 low.

Demotion paths audited:
- **REUSE** → `_execute_reuse` → `_ensure_target_donor` (existing-only) → `_attach_torrents_to_donor` → `_attach_torrents_via_hardened_fastresume` (default)
- **MOVE** → `_execute_move` → `_ensure_target_donor` (rsync copy) → `_attach_torrents_to_donor` → `_relocate_torrents_atomic`
- **PROMOTE_REUSE** → `_execute_promote_reuse` → `_relocate_torrents_atomic`

---

## Critical

### F-01: Fastresume hardened path rollback skips ATM restoration

**File:** `executor.py:815-846`  
**Severity:** Critical  
**Likelihood:** Medium (only triggers when fastresume patch fails after ATM disabled)

When `_attach_torrents_via_hardened_fastresume` fails after the patch has been applied (lines 784-785), the rollback at lines 815-846 calls `tool.rollback()` to restore fastresume backups and restarts qB, but does **not** restore ATM (Auto Torrent Management) for any torrent where it was disabled.

Compare to the other two transport paths, both of which have explicit ATM restoration:

| Path | ATM rollback? |
|------|--------------|
| `_repoint_torrents_via_fastresume_batch` (line 2323) | ✅ `atm_disabled_by_us` restored |
| `_relocate_torrents_atomic` (line 2498) | ✅ `atm_disabled_by_us` restored |
| `_attach_torrents_via_hardened_fastresume` (line 815) | ❌ Missing |

ATM is disabled in the hardened path at `tool._pause_selected(rows)` (line 707) which internally disables ATM for each row. It's also disabled per-torrent in the batch entry loop at lines 707-708 via `_pre_pause_state`.

**Impact:** After a failed fastresume patch, torrents may have ATM permanently disabled. Subsequent operations (rehome, TMM) may misbehave because `auto_tmm=false` persists across sessions. The operator must manually re-enable ATM on affected torrents.

---

## High

### F-02: Fastresume Docker stop — no fsync/sync before offline patch

**File:** `executor.py:758-764`, `2248-2254`  
**Severity:** High  
**Likelihood:** Low (race condition window at docker stop)

Both fastresume paths call `docker stop` (or `controller.stop()`) and then immediately proceed to patch `*.fastresume` files on disk:

- **Hardened path** (line 763): `controller.stop()` followed by validation+patch with no fsync on `self.fastresume_dir`
- **Legacy batch path** (line 2248): `self._docker_qb_ctl("stop")` followed by `patch_fastresume_file` (line 2254) with no fsync

Docker's default stop timeout (10s) sends SIGTERM then SIGKILL. qB may be mid-write to a fastresume file. The backup (line 2253) is taken **after** the stop, so the backup itself could capture a partially-written file.

The legacy batch path mitigates this somewhat by pausing all torrents before stopping qB (line 2232), which triggers qB to flush fastresume state. But there's no explicit `sync()` or `fsync()` on the fastresume directory.

**Impact:** Corrupted fastresume backup → rollback restores corrupted file → torrent metadata lost or inconsistent. Low likelihood due to pause-before-stop pattern, but high impact if triggered.

**Proposal:** Add `os.sync()` or `shutil.os.fsync()` on the fastresume directory after docker stop and before patch. Consider `docker stop --time=30` for a longer grace period.

---

### F-03: Rsync partial copy — no cleanup when target preexists

**File:** `executor.py:4449-4499`  
**Severity:** High  
**Likelihood:** Medium (partial rsync failure with preexisting target)

In `_ensure_target_donor` for MOVE decisions (line 4449-4499), the `cleanup_partial_target` flag is set to `not target_preexisting` (line 4452):

```python
target_preexisting = target_path.exists()
cleanup_partial_target = not target_preexisting   # True only if target was new
```

If `target_path` already exists (even as an empty directory — e.g., from a previous failed rehome or operator setup), and the rsync copy fails, the partial copy is **not** cleaned up. The except block at line 4487 checks `cleanup_partial_target`:

```python
if cleanup_partial_target and target_path.exists():
    shutil.rmtree(target_path)
```

Since `cleanup_partial_target` is `False`, the half-copied directory stays on disk. A subsequent rehome attempt of the same payload finds a preexisting target (stats don't match) and refuses with "Refusing MOVE into preexisting non-empty target" (line 4472).

**Impact:** Operator must manually clean up the partial target before retrying. Self-healing is blocked.

**Proposal:** Track whether the copy actually wrote data (rsync exit code is enough) and always clean up a partial target regardless of preexisting status. Or, always clean up any target that existed empty-before-copy.

---

### F-04: Recheck + resume race in both paths

**File:** `executor.py:1999-2014`, `2472-2476`, `2288-2292`  
**Severity:** High  
**Likelihood:** Medium (race depends on qB timing)

In both relocation paths, `_ensure_qb_seed_ready_after_relocate` calls `self.qbit_client.recheck_torrent()` which puts the torrent into `checking` state. If `resume_after_relocate` is true, `resume_torrent()` is called on a checking torrent, which is undefined behavior in the qB API:

- **Atomic path** (line 2472-2476 → 2480-2486): Verify → `_ensure_qb_seed_ready_after_relocate` (rechecks) → `resume_torrent` if enabled
- **Hardened fastresume path** (line 2288-2292 → 2296-2302): Verify → `_ensure_qb_seed_ready_after_relocate` (rechecks) → `resume_torrent` if enabled. Also at line 797, `recheck_on_failure=True` in `tool.resume()` rechecks before resume.

The `recheck_queue_grace_seconds` (default 20s) mitigates this somewhat, but the pattern of "recheck then resume" is inherently racy. The executor calls `resume_torrent` while the torrent may still be in `checking` state.

**Impact:** The resume call may be silently ignored by qB, and the torrent remains paused. The operator must manually resume. Or worse, the resume races with the recheck and produces a partial recheck.

**Proposal:** After calling recheck, wait for it to complete (poll until state leaves `checking`/`checkingDL`/`checkingUP`) before calling resume. The grace period is not sufficient — it's a fixed delay, not a state-dependent wait.

---

## Medium

### F-05: Hardened fastresume rollback — no view cleanup

**File:** `executor.py:815-846`, `4555-4562`  
**Severity:** Medium  
**Likelihood:** Low (only on fastresume failure after views built)

In `_attach_torrents_to_donor` (line 4555), `_build_views()` creates hardlink views **before** `_attach_torrents_via_hardened_fastresume` is called (line 4577). If the fastresume patching fails, the hardlink views remain on disk:

- `_build_views()` at line 4555 creates view hardlinks
- `_attach_torrents_via_hardened_fastresume()` at line 4577 fails
- Exception propagates to `_execute_reuse` (line 4682) → propagates to `execute` (line 3721)
- `execute()` catches, writes failure snapshot, records run_finish=FAILED, re-raises
- **No view cleanup anywhere in this path**

Compare to `_execute_move` which calls `_rollback_partial_target_views` on failure (line 4744). The REUSE path has equivalent logic in `_rollback_partial_target_views` (line 2535), but it is never called from the REUSE exception path.

**Impact:** Dangling hardlink views accumulate on disk. They don't break anything (they're hardlinks to valid files), but they waste inodes and confuse operators. On retry, `_preflight_existing_view_conflicts` validates them as identical hardlinks, so the retry would succeed — but the dangling views are never cleaned up until a successful MOVE's `_rollback_partial_target_views` runs for the same target path.

**Proposal:** Call `_rollback_partial_target_views` in `_execute_reuse`'s exception handler, or add view cleanup to the hardened fastresume rollback path.

---

### F-06: Planner status filter asymmetry — pool check vs payload_group

**File:** `planner.py:665-694`, `919-930`  
**Severity:** Medium  
**Likelihood:** Low (requires stale/incomplete pool entry)

`_payload_exists_on_pool` queries `payloads` with `status="complete"` (line 686). But `payload_group` is built with `status=None` (line 922) — all statuses. This creates a scenario where:

1. An incomplete/stale payload entry exists on the pool device (possibly from a failed move in a previous run)
2. `_payload_exists_on_pool` returns `None` → planner picks **MOVE** decision
3. But `payload_group` includes the incomplete entry
4. The executor's `_ensure_target_donor` may find the target path exists on disk (`target_preexisting = True`)
5. If the incomplete entry's files don't match expected stats → "Refusing MOVE into preexisting non-empty target" BLOCK
6. If they match by chance → `idempotent_reconcile` mode, which may be incorrect

**Impact:** MOVE decision could target a path that already has stale/unexpected content. The executor's defensive checks prevent a bad move, but the operator gets a confusing error message. The planner should have caught this and BLOCKed or selected REUSE.

**Proposal:** In `plan_demotion`, after deciding MOVE, verify the computed target path does not already have non-plan content. Or, when building `payload_group`, check if any pool entry with `status=complete` exists and short-circuit to REUSE.

---

### F-07: `payload_group` and `view_targets` excluded from BLOCK plans

**File:** `planner.py:729-1001`  
**Severity:** Medium  
**Likelihood:** High (every BLOCK plan)

BLOCK plans are returned without `payload_group` or `view_targets` keys. The planner sets these keys only in the REUSE/MOVE branch (lines 919-930). Downstream consumers must use `.get("payload_group") or []`.

The executor handles this correctly (e.g., line 4619: `plan.get("payload_group") or []`), but it makes the plan schema inconsistent. Any code that accesses `plan["payload_group"]` directly would crash.

**Impact:** If a new consumer of plan dicts doesn't use `.get()` with defaults, it gets a `KeyError` on BLOCK plans. This is a latent fragility.

---

### F-08: Unbounded module-level content-equality cache

**File:** `view_builder.py:19`, `116-158`  
**Severity:** Medium  
**Likelihood:** High (every rehome run)

`_CONTENT_EQ_CACHE` is a module-level dict at line 19 used by `_same_content()` to cache `(st_dev, st_ino, st_dev, st_ino, st_size, st_size)` comparison results. It is never pruned. In a long-running rehome session with many torrents/files, this cache grows unbounded.

The cache key includes device+inode pairs, so it's specific to a given file at a given point in time. However, if the same inode is reused after deletion (possible on some filesystems), the cache returns stale results.

**Impact:** Memory leak over long runs. Stale results on inode reuse.

**Proposal:** Add a `functools.lru_cache(maxsize=10000)` or similar bounded cache. The `_same_content` function is a natural candidate for `lru_cache` since its parameters are `Path` objects (which are hashable).

---

## Low

### F-09: Duplicate `_refresh_identity_cache` call

**File:** `planner.py:713-714`  
**Severity:** Low  
**Likelihood:** 100%

```python
self._refresh_identity_cache(conn)
self._refresh_identity_cache(conn)
```

Two consecutive calls with no intervening state change. The second call is entirely redundant.

---

### F-10: Legacy `_relocate_torrent` (single) is dead code

**File:** `executor.py:3088-3176`  
**Severity:** Low  
**Likelihood:** 100%

`_relocate_torrent(self, torrent_hash, new_path)` is a well-documented single-torrent relocation method (pauses, sets location, verifies, resumes). It has no callers anywhere in the codebase. It also lacks the sophisticated rollback of `_relocate_torrents_atomic` (no ATM restoration, no resume-candidate tracking).

This function is a legacy from before the atomic batch path was built. It should either be removed or retained as a fallback utility with a note about its limitations.

---

### F-11: No `view_targets` deduplication in planner

**File:** `planner.py:79-217`  
**Severity:** Low  
**Likelihood:** Low (only with cross-seed siblings sharing same save_path)

`_build_view_targets` returns one entry per torrent hash but does not check for duplicate `target_save_path` values. If two sibling torrents share the same `save_path` in qB (cross-seeds to identical content), they would produce different unique-view subdirectories (by torrent hash), which is correct. But the executor's `_build_views` has dedup logic that silently skips duplicate view targets. This means one sibling would not get its view built — which is fine for seeding but unexpected if the operator expects per-torrent views.

---

## Cross-Cutting Observations

- **Rollback surface is fragmented.** Three different rollback patterns exist (atomic's try/except at 2491, fastresume batch's at 2307, hardened fastresume's at 815) with different coverage. ATM restoration and view cleanup are inconsistently handled.
- **`resume_after_relocate=0` (default) is the safer path.** With resume off, torrents stay paused after relocation and must be manually resumed. This avoids the recheck+resume race (F-04) but shifts cognitive load to the operator.
- **Fastresume transport has more rollback gaps than set_location transport.** The hardened fastresume path (`_attach_torrents_via_hardened_fastresume`) has the most gaps (F-01, F-05), while `_relocate_torrents_atomic` (set_location) is the most robust.
- **`_ensure_target_donor` does double duty** — it both verifies the target AND performs payload copy (for MOVE). This violates single-responsibility and makes error recovery paths harder to reason about (F-03).
