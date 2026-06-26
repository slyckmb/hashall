# RCCA: Path Audit — OP-19, OP-24, OP-47

**Date:** 2026-06-26
**Job:** j38-t01
**Auditor:** agent (read-only)
**Environment:** hashall CR worktree `cr/hashall-20260530-000517-claude__j38`

---

## Summary

Read-only RCCA of three OPs related to RT session path corruption:
- **OP-47** (Beetlejuice/UEFA missing `cross-seed/` prefix in RT d.directory): Root cause is the known `save_path_inference.py` bug documented in OP-17 — bare `<tracker>/` returned instead of `cross-seed/<tracker>/`. Both items are already fixed (manual repoint + hash-check, recorded in OP-29).
- **OP-24** (4 anomalous items excluded from automation): All 4 map to the seeding root, cross-seed dir root, Beetlejuice, and UEFA. Items 3-4 (Beetlejuice/UEFA) resolved. Items 1-2 (seeding root / cross-seed root) remain genuine edge cases requiring human review.
- **OP-19** (Spurious subdirectory around bare single-file torrents): The canonical path spec §6.2 and `normalize_rt_target_directory()` correctly handle this — RT expects `d.directory` as parent, not file path. Any remaining bug is in callers that pass wrong paths.
- **j38-t02 scope:** Add `Path(target_directory).exists()` validation gate inside `rt_apply_directory_repoint()` with a configurable pre-check that raises before writing to session.

---

## Evidence Table

| Evidence | Source | Key Finding |
|----------|--------|-------------|
| OP-29 close record | OPS.md:78 | Beetlejuice+UEFA repointed to `cross-seed/FileList.io/` + hash-checked 2026-06-26, closed manually |
| OP-24 description | OPS.md:34 | 4 items: seeding root, cross-seed dir root, FileList.io/Beetlejuice, FileList.io/UEFA |
| OP-47 description | OPS.md:40 | RT d.directory = `/pool/media/../FileList.io/<name>/<name>` missing `cross-seed/` prefix |
| CANONICAL-PATH-SPEC §8 | docs/CANONICAL-PATH-SPEC.md:419-427 | OP-17: 2393 items damaged by `save_path_inference.py` returning bare `<tracker>/` |
| CANONICAL-PATH-SPEC §6.2 | docs/CANONICAL-PATH-SPEC.md:355-363 | Single-file rule: bare file → `<root>/<cat>/<filename>`, no subdirectory |
| `rt_apply_directory_repoint` | src/hashall/rtorrent.py:536-577 | No `Path(target_directory).exists()` check before writing to session |
| `normalize_rt_target_directory` | src/hashall/rtorrent.py:501-533 | Correctly handles single-file: strips filename to parent dir |
| `derive_rt_target_directory` | src/hashall/rtorrent.py:474-498 | Returns `content_path.parent` for single-file — correct |
| `_apply_client_drift_path_rows` | src/hashall/cli.py:3985,4005,4030 | Has `Path(target).exists()` checks BEFORE calling `rt_apply_directory_repoint` |
| `rt_session_reset_batch_cmd` | src/hashall/cli.py:5907,5937 | Has `--include-missing-target` flag; defaults to skipping missing targets |
| `rt_repair_apply_cmd` | src/hashall/cli.py:6175 | No `target_directory.exists()` check before calling `rt_apply_directory_repoint` |
| `rt_repoint_cmd` | src/hashall/cli.py:5554 | No `target_directory.exists()` check before calling `rt_apply_directory_repoint` |
| lane1_execute.py | src/hashall/lane1_execute.py:237,515 | Uses `check_before_start=True` but no target-exists validation |
| save_path_repair.py | src/hashall/save_path_repair.py:608 | No target-exists validation before repoint |
| hitchhiker_split.py | src/hashall/hitchhiker_split.py:320 | No target-exists validation before repoint |
| save_path_recovery.py | src/hashall/save_path_recovery.py:446 | No target-exists validation before repoint |
| nested_folder_repair.py | src/hashall/nested_folder_repair.py:520 | No target-exists validation before repoint |
| path_normalize.py | src/hashall/path_normalize.py:628,691 | No target-exists validation before repoint |
| `hashall` CLI in env | runtime | Failed: `ModuleNotFoundError: orjson` — cannot run live commands |
| Cross-seed config | /dump/docker/gluetun_qbit/cross_seed/ | Not accessible in this environment |

---

## OP-47 Findings — Beetlejuice/UEFA Root Cause

### Question 1a: Which code paths can write RT d.directory?

All paths ultimately call one of two functions:

1. **`rt_apply_directory_repoint(torrent_hash, target_directory, ...)`** — multicall: `d.stop` / `d.close` / `d.directory.set` / `d.save_full_session` / `session.save` / `d.open` / (optionally) `d.start`
   - Callers: `cli.py` (4 call sites), `lane1_execute.py` (2), `save_path_repair.py`, `hitchhiker_split.py`, `save_path_recovery.py`, `nested_folder_repair.py`, `path_normalize.py` (2)

2. **`rt_reset_torrent_session(torrent_hash, target_directory=..., ...)`** — erases session files, reloads via `load.raw_start` with inline `d.directory.set`
   - Callers: `cli.py` `rt_session_reset_cmd` and `rt_session_reset_batch_cmd`

### Question 1b: Which paths lack target-exists validation?

**Functions that set d.directory WITHOUT checking `Path(target).exists()`:**
- `rt_apply_directory_repoint()` — **no** path-exists check at all
- `rt_reset_torrent_session()` — **no** path-exists check before writing (relies on caller to validate)

**Callers that independently check existence:**
- `_apply_client_drift_path_rows()` (cli.py:3985,4005,4030) — checks `Path(target).exists()` before calling repoint (3 of 3 action branches)
- `rt_session_reset_batch_cmd()` (cli.py:5937) — skips rows where `target_exists=False` by default (`--include-missing-target` flag overrides)
- `_build_rt_repair_rows()` (cli.py:6036) — computes `target_directory_exists` and stores it, but the apply command (`rt_repair_apply_cmd`) does NOT check it before calling repoint

**Callers that have NO guard:**
- `rt_repoint_cmd` (cli.py:5554) — no existence check
- `rt_repair_apply_cmd` (cli.py:6175) — no existence check despite the report having the data
- All internal callers in lane1_execute.py, save_path_repair.py, hitchhiker_split.py, save_path_recovery.py, nested_folder_repair.py, path_normalize.py

### Question 1c: What wrote `/pool/media/torrents/seeding/FileList.io/<name>/<name>`?

**Root cause: The `save_path_inference.py` bug (OP-17).**

The CANONICAL-PATH-SPEC §8 documents that `save_path_inference.py` line 223 returned bare `<tracker>/` instead of `cross-seed/<tracker>/`. This affected 2393 cross-seed items. When a repair tool computed the RT target using this path, it set `d.directory = /seeding/FileList.io/<name>/` instead of `/seeding/cross-seed/FileList.io/<name>/`.

For multi-file torrents (both Beetlejuice and UEFA are multi-file — they have `.mkv` files nested under a release-name dir), RT materializes the content at `d.directory / info_name`. So:
- Broken `d.directory` = `/pool/media/torrents/seeding/FileList.io/<name>/`
- RT expected content at: `/pool/media/torrents/seeding/FileList.io/<name>/<name>/` (doubled name)
- Actual content was at: `/pool/media/torrents/seeding/cross-seed/FileList.io/<name>/<name>/`
- Path did not exist → `state=0, complete=0`

The `/<name>/<name>/` doubling is normal RT behavior for multi-file torrents (d.directory + info_name). The missing `cross-seed/` prefix is the actual bug.

**Specific trigger mechanism (probable):**
1. Cross-seed injected both items into qB with canonical `cross-seed/FileList.io/` save_path (correct)
2. At some point, a hashall repair tool computed RT repoint target using `save_path_inference.py` which returned bare `FileList.io/` (the OP-17 bug)
3. `rt_apply_directory_repoint` wrote this wrong path to RT session without checking if it existed on disk
4. RT had `d.complete=0` (cross-seed items are always incomplete until hash-checked) → stuck at 0%, no seeding

**Cross-seed config investigation:** Live config at `/dump/docker/gluetun_qbit/cross_seed/` is not accessible in this environment. However, the fact that both items had their actual content at the correct `cross-seed/FileList.io/` path (and were seeding correctly from qB's perspective) confirms cross-seed injected them correctly. The RT path corruption is a post-injection repair artifact.

**Items are already fixed:** Per OP-29 (OPS.md:78), "Final 2 (Beetlejuice+UEFA) repointed to cross-seed/FileList.io/ + hash-checked 2026-06-26. | manual+j35". Both are now state=1 complete=1.

**Prevention gap:** `rt_apply_directory_repoint()` has no `Path(target_directory).exists()` guard. Any caller that passes a non-existent target will write it to the RT session file without warning. This is the fix target for j38-t02.

---

## OP-24 Findings — 4 Anomalous Items

### Question 2a: Identify the four items from available docs

OP-24 (OPS.md:34) names 4 items excluded from automation:
> "dangerous source paths excluded from all automation: seeding root itself, cross-seed dir root, and 2 content subdirs 2 levels deep (FileList.io/Beetlejuice, FileList.io/UEFA)"

| # | Item | Path Pattern | Status |
|---|------|-------------|--------|
| 1 | Seeding root | `/pool/media/torrents/seeding/` | **Still open** — cannot safely repoint because it IS the root |
| 2 | Cross-seed dir root | `/pool/media/torrents/seeding/cross-seed/` | **Still open** — cannot safely repoint because it IS the root |
| 3 | FileList.io/Beetlejuice | `/pool/media/torrents/seeding/FileList.io/Beetlejuice...` | **Resolved** — repointed to `cross-seed/FileList.io/` + hash-checked in OP-29 |
| 4 | FileList.io/UEFA | `/pool/media/torrents/seeding/FileList.io/UEFA...` | **Resolved** — repointed to `cross-seed/FileList.io/` + hash-checked in OP-29 |

Items 3-4 are the same hashes as OP-47 (E04E524750C999AC and 3E82F6F7A3A5ADAE).

### Question 2b: Which are resolved, which still require review?

**Resolved (can be narrowed/closed):**
- Items 3-4 (Beetlejuice + UEFA): Fully resolved via manual repoint + hash-check. Both seeding at state=1 complete=1. OPS.md OP-40 and OP-29 confirm.

**Still require manual review:**
- Items 1-2 (seeding root + cross-seed root): These are structural paths that appear as save locations for a small number of orphan/fragmented items. They require human inspection to determine whether:
  - The items are actually needed (data may be orphaned)
  - The correct canonical path can be inferred
  - Safe deletion/repoint is possible

**No changes to OPS.md:** Items 1-2 remain open. Items 3-4 are already accounted for as resolved in OP-29. No narrowing/closing action needed on the OPS table — the current state already reflects the fix.

---

## FileList.io Audit

### Question: Are Beetlejuice/UEFA now represented as fixed in repo docs/OPS state?

**Yes.** OPS.md records:
- OP-40 (line 76): "Beetlejuice+UEFA remain OP-24 scope (human inspection required, not touched)" — was true at j34 time
- OP-29 (line 78): "Final 2 (Beetlejuice+UEFA) repointed to cross-seed/FileList.io/ + hash-checked 2026-06-26. | manual+j35" — CONFIRMS FIX

### Question: Are there other FileList.io RT rows with missing `cross-seed/` prefix?

Cannot run `python3 -m hashall rt-session-directories --missing-only` in this environment (missing `orjson` dependency). Live session directory `/dump/docker/gluetun_qbit/rtorrent_vpn/.session` is on the RT Docker host, not accessible from this worktree.

**Command to verify (read-only, safe to run):**
```bash
python3 -m hashall rt-session-directories --missing-only --path-contains FileList.io \
  --session-dir /dump/docker/gluetun_qbit/rtorrent_vpn/.session --json-output
```
This is read-only — it reads `.torrent.rtorrent` files from the session directory and reports `path_exists` per entry. It does not mutate RT state.

**Without live data:** The CANONICAL-PATH-SPEC §8 documents 2393 items with missing `cross-seed/` prefix (OP-17 cohort). Beetlejuice and UEFA were likely in this cohort. Other FileList.io items with the same problem would have been corrected during lane1 execution (j22) unless they were explicitly excluded (which Beetlejuice/UEFA were, via OP-24 exclusion).

---

## OP-19 Findings — Spurious Subdirectory Around Single-File Torrents

### Question 4a: Which code computes RT save path vs content path for single-file torrents?

Key functions:

1. **`load_rt_inventory_rows()`** (rtorrent.py:434-471):
   - For single-file: `content_path = Path(save_path) / root_name`
   - This is correct — RT stores `d.directory` as the parent dir, and the file lives at `d.directory / info_name`

2. **`derive_rt_target_directory()`** (rtorrent.py:474-498):
   - For multi-file: returns `content_path` if it exists and is a dir, else `save_path` or `Path(content_path).parent`
   - For single-file (line 493): returns `Path(content_path).parent` — the containing directory, not the file itself

3. **`normalize_rt_target_directory()`** (rtorrent.py:501-533):
   - For single-file (line 509-513): strips file suffix → takes parent directory
   - This prevents passing a file path directly as d.directory

4. **`rt_expected_loaded_directory()`** (rtorrent.py:376-383):
   - For multi-file: returns `normalized_target / info_name` (because RT appends info_name for multi-file)
   - For single-file: returns just `normalized_target` (RT does NOT append for single-file)

### Question 4b: Current behavior for bare single-file torrents

**Current code correctly implements the canonical path spec:**
- `normalize_rt_target_directory()` at line 509-513 checks `not torrent_meta.is_multi_file` and strips file extensions/paths to the parent directory
- The canonical form is `<root>/<cat>/<filename>` with no subdirectory

**Where the spurious subdirectory can still occur:**
The bug is NOT in `normalize_rt_target_directory()` itself. It can occur if a CALLER passes a path with an extra directory level (e.g., `<root>/<cat>/<release>/<filename>` where only `<root>/<cat>/<filename>` is correct). This would happen if the caller's path derivation logic treats a single-file torrent as multi-file and adds a release-name directory.

The `save_path_inference.py` module is the most likely source of such wrong path derivation (it had the known OP-17 bug of returning wrong paths). The fix for OP-16/OP-17 (`derive_policy_base_save_path` returning `cross-seed/{provider}` correctly) was in j14, but this only addresses the `cross-seed/` prefix, not the single-file subdirectory issue.

### Question 4c: Concrete test case for any remaining bug

If a reproducer torrent file is available, this test can be run:

```python
# Test: normalize_rt_target_directory for single-file torrent
torrent_meta = RTTorrentMeta(
    torrent_hash="a"*40,
    info_name="Some.File.2024.1080p.mkv",
    is_multi_file=False,
    file_count=1,
    total_bytes=1000000000,
)

# Correct: RT's d.directory should be the parent directory
result = normalize_rt_target_directory(
    "/pool/media/torrents/seeding/movies/Some.File.2024.1080p.mkv",
    torrent_meta,
)
assert result == "/pool/media/torrents/seeding/movies"
assert "Some.File" not in Path(result).name

# Incorrect (bug) - if caller passes a release-name subdir:
# target = "/pool/media/torrents/seeding/movies/Some.File.2024.1080p"
# This would create an RT directory that does NOT match the canonical form
```

The most likely remaining bug is in the PATH used for the initial cross-seed injection or a repair tool that treats all torrents as multi-file (adding a release-name subdirectory even for bare files).

---

## j38-t02 Implementation Scope

### Smallest source change to prevent writing non-existent target directories

**Primary fix: Add target-exists validation to `rt_apply_directory_repoint()`**

In `src/hashall/rtorrent.py`, function `rt_apply_directory_repoint()` (line 536):

Add an optional `validate_target_exists: bool = False` parameter. When True, check `Path(target_directory).exists()` before executing the multicall. If the path does not exist, raise `FileNotFoundError` with a descriptive message.

```python
def rt_apply_directory_repoint(
    torrent_hash: str,
    target_directory: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    restart: bool = True,
    check_before_start: bool = False,
    validate_target_exists: bool = False,  # NEW
    timeout: int = 60,
) -> list[str]:
    if validate_target_exists:
        if not target_directory or not Path(target_directory).exists():
            raise FileNotFoundError(
                f"rt_apply_directory_repoint target does not exist: hash={torrent_hash} "
                f"target={target_directory!r}"
            )
    # ... rest of function unchanged
```

**Files to update:**

| File | Change |
|------|--------|
| `src/hashall/rtorrent.py` | Add `validate_target_exists` param to `rt_apply_directory_repoint()`. Add `Path(target_directory).exists()` check |
| `tests/test_rtorrent_safe_start.py` | Add test: `test_validate_target_exists_true_missing_path` — asserts `FileNotFoundError` when target missing |
| | Add test: `test_validate_target_exists_true_existing_path` — asserts normal execution when target exists |

**Callers to update (opt-in — set `validate_target_exists=True`):**

Opt-in approach (default `False`) is chosen to avoid breaking existing callers that may legitimately repoint to a path that hasn't been created yet (e.g., cross-seed creates directories as part of injection).

For j38-t02, set `validate_target_exists=True` in these callers:

| Caller | File | Why |
|--------|------|-----|
| `rt_repair_apply_cmd` | cli.py:6216 | Repair targets must exist — they should already be on disk |
| `rt_session_reset_batch_cmd` | cli.py:5964 | Currently has optional skip via `--include-missing-target`; add built-in guard |
| `rt_session_reset_cmd` | cli.py:5628 | Single-item session reset should validate target |
| `_apply_client_drift_path_rows` | cli.py:3989,4044 | These already have pre-checks; the guard is redundant but harmless (belt-and-suspenders) |
| `lane1_execute.py` | lane1_execute.py:237,515 | Canonical path computation should verify the directory exists before repointing |
| `save_path_repair.py` | save_path_repair.py:608 | Data presumably moved to target; verify it's there before writing to RT |
| `save_path_recovery.py` | save_path_recovery.py:446 | Similar — data should be at target |

**Tests to update/create:**

1. `tests/test_rtorrent_safe_start.py` — add two new test methods to `TestApplyDirectoryRepoint`:
   - `test_validate_target_exists_true_missing_path`: patch `Path.exists()` to return `False`, assert `FileNotFoundError`
   - `test_validate_target_exists_true_existing_path`: patch `Path.exists()` to return `True`, assert normal execution

2. No other test files need changes — existing tests mock `rt_xmlrpc_multicall` and won't be affected by the new parameter (default `False` is backward-compatible).

### Future work (j38-t03+):
- Consider making `validate_target_exists` default to `True` after all callers have been audited
- Add the same guard to `rt_reset_torrent_session()`
- Implement post-inject RT path audit (OP-47 item 5): after cross-seed injection or repoint, verify the written path exists

---

## Verification Commands Run

```bash
# rg searches for OP-19, OP-24, OP-47, Beetlejuice, UEFA, FileList.io, etc.
rg -n "OP-19|OP-24|OP-47|Beetlejuice|UEFA|FileList.io|single-file|rt_apply_directory_repoint" OPS.md docs src tests

# python3 -m hashall command — FAILED (orjson not installed in this environment)
python3 -m hashall rt-session-directories --missing-only \
  --session-dir /dump/docker/gluetun_qbit/rtorrent_vpn/.session

# Result: ModuleNotFoundError: No module named 'orjson'
# Note: hashall requires system-level pip install with orjson dependency.
# This is a read-only constraint of the audit environment.
```

All evidence is from code analysis and repo documentation. No live RT/qB/FS access was needed to answer the root cause questions.

---

## OPS.md Changes

**No changes needed.** Current OPS.md state already reflects:
- OP-47: Open with correct description and fix plan (line 40) — keep open until j38-t02 guard ships
- OP-24: Open (line 34) — items 1-2 still need human review
- OP-19: Open (line 32) — scope now clear; can narrow after implementation
- OP-29: Closed (line 78) — confirms Beetlejuice/UEFA fixed
