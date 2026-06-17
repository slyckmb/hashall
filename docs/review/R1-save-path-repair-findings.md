# R1 — save_path_repair.py + save_path_inference.py Audit Findings

## Summary
3 critical, 5 high, 6 medium, 4 low

## Known Bugs (OP-05, OP-06)

### OP-05 — fastresume patched when files_moved==0 and qB save_path not in _rehome-unique
- **Status: CONFIRMED FIXED**
- **File:** `save_path_repair.py:569`
- **Fix evidence:** `should_apply = files_moved > 0 or qb_at_rehome` gates the fastresume patch block. When `files_moved==0` and `qb_at_rehome` is False, `should_apply` is False and the fastresume code path is never entered. Additionally, the Bug 2 guard (`save_path_repair.py:558-565`) short-circuits entirely when a staging dir is empty and qB still points to it. The Bug 5 orphan guard (`save_path_repair.py:486-496`) catches empty staging dirs where neither client points there.

### OP-06 — ambiguous prefix match in _resolve_full_hash()
- **Status: CONFIRMED FIXED**
- **File:** `save_path_repair.py:298-338`
- **Fix evidence:** `_resolve_full_hash()` raises `ValueError` when a prefix matches >1 full hash in qB dict (`save_path_repair.py:313-316`) or in the catalog DB (`save_path_repair.py:327-329`). The only remaining code path when 0 matches is a silent fallback returning the truncated prefix as-is — see F-01 below.

## Findings

### F-01 — [CRITICAL] _resolve_full_hash returns bare prefix on 0-match, silently degrading inference
- **File:** `save_path_repair.py:338`
- **Condition:** A staging hash dir (16-char) has NO matching qB torrent AND NO matching catalog DB entry. This triggers the fallback `return prefix` which returns the truncated 16-char string as `effective_hash`.
- **Impact:** The caller uses `effective_hash` to look up qB/RT metadata — both lookups return empty data (qb_torrent=None, rt_info={}). The torrent is processed with empty category/tags, producing unreliable canonical path inference. If `_staging_has_real_content` returns True (dir has files), the files ARE moved to whatever canonical path is inferred from empty metadata — potentially wrong destination. Fastresume patch targets a hash key that likely doesn't exist in qB's BT_backup.
- **Proposed fix:** When `_resolve_full_hash` returns the prefix unchanged (0-match fallback), raise or log a CRITICAL warning and add an explicit note to RepairResult. At minimum, skip fastresume patching. Consider: `_scan_staging_hashes` could also store the original full 40-char hash from the torrent instance if available.

### F-02 — [CRITICAL] audit_repair_candidates loads ALL qB/RT state but most of it is irrelevant
- **File:** `save_path_repair.py:197-222` and `save_path_repair.py:638-662`
- **Condition:** `get_torrents_from_cache()` returns ALL cached qB torrents (~5200+). The function iterates every one to build the hash → torrent dict. Same for RT. This is necessary for `_resolve_full_hash` prefix matching but the full scan happens both in `audit_repair_candidates` and `execute_repair` (duplicate work).
- **Impact:** 2x redundant cache loading per repair cycle. If cache misses collide (e.g., both functions trigger live qB API calls), the repair loop becomes N×2 live API calls. With a 300s cache TTL, a long repair batch will trigger repeated live calls.
- **Proposed fix:** Share the `qb_by_hash`/`rt_by_hash` dicts between `audit_repair_candidates` and `execute_repair` — pass them through RepairAction, or make `execute_repair` accept optional pre-loaded state.

### F-03 — [CRITICAL] Cross-device check skipped in dry-run — dry-run result may not match --execute
- **File:** `save_path_repair.py:142-150`
- **Condition:** The `_move_tree` cross-device check (`src_stat.st_dev != dst_stat.st_dev`) runs only when `not dry_run`. In dry-run mode, `_move_tree` returns a file count without verifying that the source and destination are on the same filesystem.
- **Impact:** A user runs `--dry-run`, sees "would move 5 files", then runs `--execute` and gets `RuntimeError: cross-filesystem move rejected`. The repair fails at runtime with no dry-run forewarning.
- **Proposed fix:** In dry-run mode, stat both paths and add a note pointing out cross-device preconditions. Example: `src is /stash/... (dev=N), dst is /pool/... (dev=M) — if dev mismatch, --execute will fail`.

### F-04 — [HIGH] _move_tree silently skips symlinks and non-file items
- **File:** `save_path_repair.py:162`
- **Condition:** `if not item.is_file(): continue` — `rglob("*")` encounters symlinks, sockets, fifos, or unusual file types and silently skips them.
- **Impact:** Symlink-to-file: `is_file()` follows symlinks and returns True, so these ARE moved (the symlink itself via `shutil.move`). However, broken symlinks (`is_file()` returns False) are silently left behind in the staging dir. A broken symlink remaining in an otherwise-empty staging dir means `_staging_has_real_content` returns True (broken symlinks are not dirs), preventing `gc_empty_staging_dirs` from cleaning up.
- **Proposed fix:** After `_move_tree`, check for remaining non-dir entries in src and log a warning. Or change `_staging_has_real_content` to accept broken symlinks as ignorable content. Document that only regular files are moved.

### F-05 — [HIGH] No rollback on partial move failure
- **File:** `save_path_repair.py:133-180`
- **Condition:** `_move_tree` processes files one at a time inside `sorted(src.rglob("*"))`. If `shutil.move` fails mid-way (disk full, permission error), the files that were already moved are at the destination while unprocessed files remain at source. No rollback mechanism.
- **Impact:** Partial move corruption. The torrent at the new destination is incomplete. Notes report `FAILED: <error>` but don't quantify how many files were moved vs left behind.
- **Proposed fix:** In the exception handler of `execute_repair` (line 621-623), log `files_moved` so far if available. Consider making `_move_tree` transactional (copy-then-rename or a manifest of moved files for rollback).

### F-06 — [HIGH] Sequential repair stops/starts Docker per-torrent — extremely expensive in batch
- **File:** `save_path_repair.py:578-593` and `cli.py:2497-2501`
- **Condition:** The CLI loop at `cli.py:2497-2501` calls `execute_repair` per hash. For each live repair with a valid fastresume, Docker is stopped, fastresume patched, Docker started (waits 90s for API), RT repointed, and recheck triggered. Processing 12 Class 4 items would require 12 Docker restarts = ~18 minutes.
- **Impact:** Not a correctness bug but a severe performance bottleneck. The 90s startup wait in `_docker_start_qb` makes batch processing impractical for more than 1-2 torrents.
- **Proposed fix:** Batch the Docker stop/patch/start cycle: collect all fastresume paths, stop Docker once, patch all, start Docker once, then recheck individually.

### F-07 — [HIGH] _scan_staging_hashes hash collision silently drops both entries for _rehome-unique
- **File:** `save_path_repair.py:98-107`
- **Condition:** If the same hash16 appears in both `/stash/_rehome-unique/` and `/pool/_rehome-unique/`, the collision handler logs error and `del staging_hashes[key]` — dropping both entries.
- **Impact:** A torrent with a genuine hash collision between stash and pool _rehome-unique dirs is silently excluded from repair. The dirs remain on disk, unrepaired. The error log says "manual resolution required" but no CLI output or return code signals this to the operator.
- **Proposed fix:** Retain the stash entry when collision occurs (last write wins is fine for _rehome-unique), or log a warning that both have the same hash16 prefix (unlikely in practice since hash16 is unique per torrent).

### F-08 — [HIGH] execute_repair fastresume path computed without verifying qb_torrent exists
- **File:** `save_path_repair.py:579-593`
- **Condition:** If `should_apply=True` (because `files_moved > 0`), `fastresume_path = qb_client._fastresume_path(effective_hash)` is computed. If `effective_hash` was the bare prefix fallback (F-01) or if qB has no record of this hash, the fastresume won't exist. The code handles this via `if fastresume_path.exists()` — but Docker is NOT stopped in this case, so the branch is safe.
- **Impact:** Low risk because fastresume not found → skip → no Docker ops. But the code implies fastresume was expected; an operator seeing "fastresume not found" without context may not realize this is expected for stale/non-qB torrents.
- **Proposed fix:** Add a check: if `qb_torrent is None` before the fastresume block, skip with a note "no qB record — fastresume patch skipped" rather than falling through to `fastresume_path.exists()`.

### F-09 — [MEDIUM] RT repoint runs inside `should_apply` block — never runs when qB path is clean but RT is drifted
- **File:** `save_path_repair.py:596-606`
- **Condition:** RT repoint (`rt_apply_directory_repoint`) runs inside the `if not dry_run: else: ...` block which requires `should_apply=True`. If `files_moved==0` (data already at destination) and `qb_at_rehome==False` (qB already points to canonical path), but `rt_info.get("directory","")` still points to a staging dir, `should_apply` is False and RT is NOT repointed.
- **Impact:** An RT-only drift case is silently left unresolved. RT continues pointing to a staging dir while qB is already correct. This is likely rare (RT and qB are usually in sync) but possible after a manual intervention.
- **Proposed fix:** Compute `rt_needs_repoint = rt_info and _is_in_staging_dir(rt_info.get("directory",""))` and use it alongside `should_apply` to gate RT repoint.

### F-10 — [MEDIUM] RepairAction.is_drifted always False in audit_repair_candidates
- **File:** `save_path_repair.py:287`
- **Condition:** `is_drifted=False` is hardcoded. `audit_repair_candidates` never compares `current_source_path_fs` against `canonical_target_path_fs` to determine drift.
- **Impact:** The `is_drifted` field exists on RepairAction but is never populated by the audit function. Downstream consumers that check `is_drifted` get misleading data. This is a dead field in the current implementation.
- **Proposed fix:** Either populate `is_drifted` by comparing source vs canonical path, or remove the field if it's not used by any caller.

### F-11 — [MEDIUM] _move_tree for directory case creates destination parent for each file (N mkdir calls)
- **File:** `save_path_repair.py:167`
- **Condition:** `dst_file.parent.mkdir(parents=True, exist_ok=True)` is called inside the loop for every file moved. For a torrent with 50 files in subdirectory structure, this is ~50 redundant mkdir calls (many for the same directory).
- **Impact:** Performance issue, not correctness. The `exist_ok=True` makes it safe but wasteful. Annoying on spinning disks with many tiny files.
- **Proposed fix:** Move the initial `dst.parent.mkdir(parents=True, exist_ok=True)` outside the loop (it's already done at line 144 for the non-dry-run cross-device check), then only mkdir for subdirectories that differ.

### F-12 — [MEDIUM] No preflight validation that target path exists or is writable
- **File:** `save_path_repair.py:567`
- **Condition:** `_move_tree(src, dst, dry_run=dry_run)` runs with no stat check that `dst.parent` is mounted, writable, or has sufficient free space. The first sign of trouble is a `PermissionError` or `OSError` from `shutil.move`.
- **Impact:** Silent failure surface. A network mount dropped, disk full, or permission change would cause repair to fail mid-batch with the first problematic torrent, leaving preceding torrents partially processed and later torrents untouched.
- **Proposed fix:** Before the loop, probe `dst.parent` with `os.access(W_OK)` and stat for free space. Add a `try:` early-exit in `execute_repair` that checks `Path(target_fs).parent.exists()`.

### F-13 — [MEDIUM] gc_empty_staging_dirs uses hash prefix collision logic for "live" detection
- **File:** `save_path_repair.py:672-679`
- **Condition:** `has_live_qb = any(full_h.startswith(hash_val) and _is_in_staging_dir(str(t.save_path)) for full_h, t in qb_by_hash.items())`. This is a prefix match against ALL qB hashes. With 4800+ torrents, ~80% of 16-char prefixes collide with unrelated hashes (documented in code comments).
- **Impact:** The `_is_in_staging_dir` filter mitigates this: only hits where qB save_path actually points to a staging dir count as "live". However, if a completely unrelated qB torrent (different hash that happens to share the 16-char prefix) has a save_path in ANY staging dir (not just this hash's dir), it would prevent GC of this orphan.
- **Proposed fix:** This is partially mitigated by the save_path filter, but it could be made more precise by excluding the save path specific to the dir being GC'd. Or accept the existing mitigation as sufficient for the documented false-positive rate.

### F-14 — [LOW] Dry-run adds contradictory notes when files_were counted
- **File:** `save_path_repair.py:616-626`
- **Condition:** In dry-run mode with files in staging dir, two notes are appended: (1) `[dry-run] would move N files from...` (line 616-619), and (2) `dry-run: no files moved, no qB/fastresume/RT changes made` (line 625-626). Note 2 contradicts the implication of note 1.
- **Impact:** Cosmetic confusion in output. An operator sees "would move N files" and "no files moved" in the same result — ambiguous.
- **Proposed fix:** Only add the second note when `not files_moved > 0` in dry-run mode. Or rephrase to "dry-run: no actual changes made".

### F-15 — [LOW] infer_canonical_save_path path-hint device override for cross-seed doesn't check first component against staging dirs for all path components
- **File:** `save_path_inference.py:346-359`
- **Condition:** When determining device for cross-seed without ~noHL, the code checks if the first path component after the seeding root is a staging dir. But a path like `/pool/media/torrents/seeding/Aither/_rehome-unique/abcd1234` has first component "Aither" (not staging), so it infers "pool". This is correct in intent but the comment doesn't fully explain the skip logic.
- **Impact:** Low — no incorrect device inference in practice, but the code relies on the first component being the tracker name for non-staging paths. If the first component were itself a staging dir (e.g., moving files directly into `/pool/seeding/_rehome-unique/`), it would not infer pool. The guard already handles this case.
- **Proposed fix:** Documentation clarification only.

### F-16 — [LOW] load_qbm_config uses hardcoded path to the user's sys/docker repo
- **File:** `save_path_inference.py:265`
- **Condition:** `config_path: str = "/home/michael/dev/sys/docker/qbit_manage/config.yml"` — hardcoded user home path.
- **Impact:** Not portable across users or CI environments. The function silently returns `{}` when the config is not found, degrading to alphabetical tag fallback (already documented as a limitation at `save_path_inference.py:273`).
- **Proposed fix:** Make the path configurable (environment variable or passed from CLI), or document the requirement in the function's contract. The `lru_cache` prevents reloading even if the file changes.

### F-17 — [LOW] _api_path uses string slicing without bound check
- **File:** `save_path_repair.py:129`
- **Condition:** `rel = path_on_fs[len(fs_root):]` — if `path_on_fs` is somehow shorter than `fs_root`, this silently produces an empty string (Python doesn't raise on OOB string slicing). The resulting API path would be just `api_root` with no subpath.
- **Impact:** Currently unreachable because callers always pass paths starting with `fs_root`. Defensive edge case.
- **Proposed fix:** Add `assert path_on_fs.startswith(fs_root)` or `if not path_on_fs.startswith(fs_root): return path_on_fs` guard.

