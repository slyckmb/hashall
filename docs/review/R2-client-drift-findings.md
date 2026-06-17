# R2 — client_drift.py Mutation/Apply Paths Audit Findings

## Summary
3 critical, 5 high, 5 medium, 3 low

## Key Questions Answered

### Q1: If RT repoint succeeds but qB set_location fails — what state is left?
- **Answer:** RT is already committed to the new path; qB is at the old path. No rollback.
- **Evidence:** `_apply_client_drift_path_rows` (cli.py:3377-3409) in `repoint_both_to_pool` calls `rt_apply_directory_repoint` first (line 3389), then `qbit.set_location` (line 3396). If set_location fails, a `ClickException` is raised (line 3418), but RT's directory change is permanent. The journal has no "undo" entry.
- **Recovery:** Re-running the apply will hit the journal "already completed" check for RT, but qB will retry set_location. Workable but manual.

### Q2: If set_location triggers a physical file move — is that guarded against?
- **Answer:** **NO guard.** qB's `setLocation` API CAN trigger a physical file move (qB moves data to the new path). The code only checks `Path(target).exists()` (cli.py:3360, 3385), which does NOT prevent qB from moving files. The docstring at `qbittorrent.py:1407` claims "Pattern: pause → setLocation → resume" but the actual implementation (qbittorrent.py:1414-1417) does NOT pause before calling setLocation — it POSTs directly.
- **Impact:** If the target path exists but is empty or differs from the content layout qB expects, qB moves all files to the new location. This is the exact class of bug that caused the 90-torrent `missingFiles` incident documented in BACKLOG.md.

### Q3: Is there any rollback mechanism if a multi-step repoint fails mid-sequence?
- **Answer:** **None.** The apply functions use a journal (JSONL) to track what was done, but there is no undo capability. The journal is append-only — once an event is written, it cannot be reversed programmatically.

### Q4: Are there any silent success returns that mask failures?
- **Answer:** The path apply flow correctly raises `ClickException` on failure (cli.py:3418). The mirror apply flow also raises (cli.py:3199). However, see F-10 below: the mirror apply hardcodes RT XMLRPC URL — if that request fails, only a warning is logged (cli.py:3166) and the operation continues. This is a partial silent failure.

### Q5: Does the dry-run path match the apply path exactly?
- **Answer:** Yes, for a single invocation. Both `client_drift_audit_cmd` and `client_drift_apply_cmd` call the same `_load_client_drift_report` function which re-computes the report from cached data. However, if cache files/state change between dry-run and apply, the report WILL diverge (see F-03 below). The `--action` flag in apply allows selecting a subset, which is intentional divergence.

## Findings

### F-01 — [CRITICAL] setLocation has no guard against physical file move
- **Files:** `cli.py:3364,3396` and `qbittorrent.py:1393-1470`
- **Condition:** `qbit.set_location(torrent_hash, target)` is called during `repoint_qb_to_rt_path` and `repoint_both_to_pool`. The qB API `setLocation` will physically move files on disk if the new save_path differs from the old one. The code checks `Path(target).exists()` but NOT that the target is on the same filesystem, nor does it pause the torrent before setLocation.
- **Impact:** If the target path is on a different mount, or even on the same mount but qB decides the layout differs, it triggers a full file move. For a multi-GB torrent, this takes minutes/hours during which the API is in a transient state. Crash mid-move → corrupted seeding state.
- **Proposed fix:** Before `set_location`, pause the torrent, verify it's `pausedUP`/`stoppedUP`, then call setLocation, then resume. Verify no `moving` or `MV` state appears after the call. The docstring at qbittorrent.py:1407 already documents this pattern — implement it.

### F-02 — [CRITICAL] repoint_both_to_pool applies RT repoint before qB set_location — partial failure leaves inconsistent state
- **File:** `cli.py:3377-3409`
- **Condition:** In `repoint_both_to_pool`, RT is repointed first (line 3389). qB set_location runs second (line 3396). If set_location fails, RT has already been changed.
- **Impact:** Client state inconsistency. RT at pool path, qB at old path. The torrent may error or show as not found in one client.
- **Proposed fix:** Reverse the order: do qB set_location FIRST (fail-fast). If that succeeds, do RT repoint. This way, if qB fails, RT is untouched. Journal entries should still reflect partial completion for resume.

### F-03 — [CRITICAL] Dry-run and apply use separate report invocations — cache divergence possible
- **File:** `cli.py:3701-3711` (`_load_client_drift_report`)
- **Condition:** The apply command calls `_load_client_drift_report()` which rebuilds the drift report from cache files at the TIME of apply. If qB/RT cache files changed between the audit (dry-run) and apply (--apply), the computed actions may differ from what the operator reviewed.
- **Impact:** Operator reviews a dry-run with 12 items, approves, runs apply — but qB cache rotated, and now 13 items are selected (or 11, or different actions).
- **Proposed fix:** The apply command should accept a pre-computed report file (JSON) from the audit, not re-compute on the fly. Or, at minimum, emit a warning if the cache modification time changed since the dry-run.

### F-04 — [HIGH] Hardcoded RT XMLRPC URL in mirror apply path
- **File:** `cli.py:3157-3164`
- **Condition:** `_apply_client_drift_mirror_rows` hardcodes `xmlrpc.client.ServerProxy("http://127.0.0.1:18000/")` instead of using the `rt_rpc_url` parameter. The path apply function (`_apply_client_drift_path_rows`, line 3389) correctly takes `rt_rpc_url` as a parameter.
- **Impact:** If RT XMLRPC is on a non-default URL, the mirror tagging of RT side (`d.custom2.set`) fails silently — the try/except at line 3165-3166 catches and logs a warning but continues the operation. The qB add succeeds, but the RT side is not tagged with `~qb-mirrored`, breaking the mirror protocol.
- **Proposed fix:** Thread `rt_rpc_url` through to `_apply_client_drift_mirror_rows` and use it instead of the hardcoded URL. The CLI handler at line 3678 accepts `--rt-rpc-url` but never passed it to the mirror function.

### F-05 — [HIGH] No validation that set_location target is on the same filesystem
- **File:** `cli.py:3357-3367`, `qbittorrent.py:1414-1417`
- **Condition:** `Path(target).exists()` is checked, but there is no verification that the target path is on the same device/mount as the current content. Cross-device setLocation forces qB to physically copy-and-delete files.
- **Impact:** During a `repoint_both_to_pool` or `repoint_qb_to_rt_path`, if the target save_path resolves to a different mount, qB silently moves GB of data. Long operation, high I/O, high risk.
- **Proposed fix:** Stat the target path and the current content path; emit a warning or block if they differ by `st_dev`. This is analogous to the cross-device check in `save_path_repair.py:146` which already prevents this.

### F-06 — [HIGH] Apply raises ClickException on first error, abandoning the row mid-batch
- **File:** `cli.py:3416-3418`, `cli.py:3197-3199`
- **Condition:** Both `_apply_client_drift_path_rows` and `_apply_client_drift_mirror_rows` raise `ClickException` immediately on the first error. This stops the entire batch. Rows already processed (and journaled) are committed; remaining rows (including some that may have been partially processed) are abandoned.
- **Impact:** In a batch of 10 repoint_both_to_pool items, if item 5 fails mid-sequence, items 1-4 are committed (journaled), item 5 is partially committed (RT done, qB not done), items 6-10 are untouched. The operator must investigate, fix item 5, and resume.
- **Proposed fix:** Instead of raising immediately, collect errors and continue processing remaining rows. Report the full error count after the batch. Only raise at the end if any failed. The journal already supports resume, so partial failures should not abort the entire job.

### F-07 — [HIGH] repoint_rt_to_qb_path validates target existence on qB's FS, but RT repoint succeeds regardless
- **File:** `cli.py:3339-3352`
- **Condition:** The code checks `Path(target).exists()` (cli.py:3341) but this checks the HOST filesystem, not RT's container filesystem. `rt_apply_directory_repoint` sets the directory via XMLRPC to the host path. If the Docker container maps paths differently, the target exists on the host but not in RT's container.
- **Impact:** RT repoint succeeds (directory string set) but RT cannot find the files → torrent becomes errored. This is a path-mapping issue that varies by deployment.
- **Proposed fix:** Use `rt_path_aligned` or an RT-side `d.directory` stat check after repoint to verify the directory was accepted and is accessible from the RT container.

### F-08 — [MEDIUM] `_apply_client_drift_mirror_rows` does not pass `rt_rpc_url` — hardcoded only in mirror path
- **File:** `cli.py:3744-3755`
- **Condition:** When mirror action is selected, `_apply_client_drift_mirror_rows` is called (line 3745) without the `rt_rpc_url` parameter. The function doesn't accept it (see F-04).
- **Impact:** See F-04. The CLI has `--rt-rpc-url` but it's ignored for mirror operations.
- **Proposed fix:** Add `rt_rpc_url` parameter to `_apply_client_drift_mirror_rows` and pass it from the CLI handler.

### F-09 — [MEDIUM] `set_location` retry logic logs but continues — last error may be stale
- **File:** `qbittorrent.py:1412-1469`
- **Condition:** On non-timeout HTTP errors (e.g., 400 Bad Request), the function retries per `request_retries`. On all failures, it sets `self.last_error`. But the caller (`cli.py:3367`) only checks `last_error` on the final `False` return. If all retries fail, the error is correct. But if retry succeeds after a failure, `last_error` still holds the OLD error from the first attempt (not cleared until line 1420).
- **Impact:** In the retry-success case, the caller gets `True` (success) but `last_error` still contains a stale error string. Subsequent operations that check `last_error` may see an irrelevant error message.
- **Proposed fix:** Set `self.last_error = None` at the top of each retry attempt, or only set it on definitive failure (exhausted retries).

### F-10 — [MEDIUM] Missing test coverage for _apply_client_drift_path_rows mutation paths
- **File:** `tests/test_client_drift.py`
- **Condition:** The test file (1882 lines) covers report building, drift detection, and classification thoroughly, but the actual apply functions (`_apply_client_drift_path_rows`, `_apply_client_drift_mirror_rows`) have NO unit tests. The tests use mocks for qB/RT cache and session data but never invoke the mutation functions.
- **Impact:** The most dangerous code (actual mutation of client state) is untested. Bugs in the apply path are only discoverable via live runs.
- **Proposed fix:** Add mock-based tests for `_apply_client_drift_path_rows` with fake qbittorrent client and fake RT XMLRPC, covering: success, RT-only failure, qB-only failure, dual failure, recheck behavior, and pause-after-recheck.

### F-11 — [MEDIUM] `_apply_client_drift_path_rows` has duplicated recheck/pause logic between repoint_qb_to_rt_path and repoint_both_to_pool
- **File:** `cli.py:3368-3376` and `cli.py:3401-3409`
- **Condition:** The 9-line recheck-then-pause block is duplicated across the two action branches (identical code at lines 3368-3376 and 3401-3409).
- **Impact:** Maintenance risk — a fix to one block (e.g., adding recheck error handling) must be ported to the other manually. DRY violation.
- **Proposed fix:** Extract a helper: `_recheck_and_pause_torrent(qbit, torrent_hash) -> dict`.

### F-12 — [MEDIUM] `_read_json` returns None for any error — silent data loss for cache reads
- **File:** `client_drift.py:135-139`, used by `load_qb_cache_rows:377` and `load_rt_cache_rows:415`
- **Condition:** `_read_json` catches all exceptions and returns None. Callers treat None as "no data" (empty dict). A corrupted cache file, permission error, or JSON parse error silently returns empty state — the drift report shows 0 torrents.
- **Impact:** An operator runs a drift audit, sees "0 torrents" and assumes no drift exists, when actually the cache file was unreadable. The warning is buried in logs.
- **Proposed fix:** Differentiate between "file not found" (return None) and "file found but unreadable" (log warning, return None with context).

### F-13 — [LOW] `_pool_seeding_category` uses `startswith` without `/` boundary check
- **File:** `client_drift.py:1042-1048`
- **Condition:** `if root_path.startswith(pool_root):` — if pool_root is `/pool/media/torrents/seeding` and root_path is `/pool/media/torrents/seeding-other/abc`, the prefix matches incorrectly. Same issue as `_api_path` in save_path_repair.py.
- **Impact:** Low risk because pool_roots are well-known constants, but defensive boundary check (`startswith(pool_root + "/") or root_path == pool_root`) would be safer.
- **Proposed fix:** Add `/` boundary suffix: `if root_path == pool_root or root_path.startswith(pool_root + "/"):`

### F-14 — [LOW] `_classify_common_path_drift` placement dict tracks `proposed_source_client` but never validates it before apply
- **File:** `client_drift.py:1223-1338`, `cli.py:3331-3409`
- **Condition:** The classification sets `proposed_source_client` to "qb" or "rt" (e.g., line 1233, 1243) which determines the repoint direction. But the apply command at cli.py:3331-3409 switches on `action` string, not `proposed_source_client`. If a bug in classification produces an action string that doesn't match the proposed source client, the wrong client gets modified.
- **Impact:** Not a current bug (the mapping is consistent in the code), but a defensive assertion would catch future refactoring errors.
- **Proposed fix:** Add an assert in the apply function that the action's implied source matches the placement's proposed_source_client.

### F-15 — [LOW] `_detect_nested_folder` uses Path.stem for single-file detection — may produce false negatives
- **File:** `client_drift.py:1122-1123`
- **Condition:** `item_stem = Path(item_name).stem` — for a multi-file torrent named `Show.S01.COMPLETE`, `item_name` is the torrent name (e.g., "Show.S01.COMPLETE"), and `Path(item_name).stem` returns "Show.S01.COMPLETE" (because `.` is not a separator in Path.stem on most systems — it only strips the last extension). Actually, `Path("Show.S01.COMPLETE").stem` returns "Show.S01" (strips ".COMPLETE"). If the item_name has multiple dots, the stem detection may not match.
- **Impact:** Single-file nested folder detection could produce a false negative (not flagging a genuinely nested folder). Very edge case.
- **Proposed fix:** For single-file, compare `dir_name` to `item_name` (not `item_stem`), since the dir is named after the full torrent name.

### F-16 — [LOW] `Hash` prefix filter includes both qB and RT hashes — ambiguous on collision
- **File:** `client_drift.py:1356-1359`
- **Condition:** `hash_prefixes` matches `any(torrent_hash.startswith(prefix) for prefix in hash_prefixes)`. The common hash set is `qb_hashes & rt_hashes` (line 1355). If a hash prefix matches multiple hashes in the common set, ALL matching hashes are selected.
- **Impact:** When operating on a specific hash, the operator may unintentionally select other hashes that share the same prefix. For example, `prefix="abc"` selects `abc123...` AND `abc456...`. This is documented as intentional but could surprise operators.
- **Proposed fix:** If hash_filters are provided and an ambiguous prefix match occurs, warn the operator listing the matching hashes. This mirrors the OP-06 fix pattern in `_resolve_full_hash`.

### F-17 — [LOW] `load_rt_cache_rows` infers category from path when RT category is missing — may mismatch with qB
- **File:** `client_drift.py:445-446`
- **Condition:** If the RT cache row has no category/label/custom1, `_infer_category_from_path(row.target_qb_save_path, active_policy.mirror_roots)` derives the category from the path. This inferred category may differ from qB's assigned category for the same torrent.
- **Impact:** Drift classification may compare mismatched categories between qB and RT, affecting policy decisions (category-based mirroring, blocking, etc.). False positives or false negatives in drift detection.
- **Proposed fix:** When RT category is inferred from path, note it in the row's metadata so the classification logic can account for the inference. Add a field `category_source: str` ("rt_cache" | "inferred_from_path").

### F-18 — [LOW] `recheck_after_add` parameter to `_apply_client_drift_path_rows` is accepted but never used
- **File:** `cli.py:3760` — `recheck_after_add=recheck_after_add` is passed to `_apply_client_drift_path_rows` but the function body never references this parameter (only `_apply_client_drift_mirror_rows` uses recheck_after_add).
- **Impact:** Dead parameter. No current bug since the path apply always rechecks after set_location (lines 3369, 3403), but the CLI option `--recheck-after-add` is silently ignored for path operations.
- **Proposed fix:** Either remove the parameter from the path apply call, or add path-specific recheck-after-add behavior if needed.
