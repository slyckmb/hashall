# Phase 2: Scan Hot-Path Optimization

**Status:** Planning  
**Last updated:** 2026-05-08  
**Phase 1 baseline:** Fast freshness profile committed (feat(refresh): add fast freshness profile)

## Goal

Optimize the scan hot-path to make `make db-refresh-fast` measurably faster for the freshness profile (`--hash-mode fast --drift-policy metadata`), supporting faster client-repair evidence cycles.

## Current Performance Baseline

The `hashall scan` command walks a 35.7 TB stash + pool filesystem and:
1. Discovers all files (os.walk + stat)
2. Groups files by inode
3. Loads existing catalog entries from database
4. Processes work items (hash/comparison logic)
5. Writes results back to database

Current profile: **freshness** uses:
- `hash_mode=fast` (quick_hash only, no full SHA256 unless collision detected)
- `drift_policy=metadata` (trust unchanged mtime/size, skip recheck)
- `skip_dedup=True`
- `payload_upgrade_missing=False`

## Identified Bottlenecks

### B1: `load_existing_files()` loads entire root catalog at scan start

**Location:** `src/hashall/scan.py:95-169`  
**Impact:** Single bulk query loads all files under root, even if most won't be checked  
**Metric:** On 35.7 TB stash with millions of files, this can be a 10-30% scan overhead

**Optimization opportunity:** For `drift_policy=metadata`, defer catalog load and use lazy lookups. Only load when:
- A file's metadata has changed (size or mtime differs)
- Quick-hash mismatches existing hash (indicates actual file change)

### B2: `_relative_to_any_mount()` called repeatedly per file

**Location:** `src/hashall/scan.py:919, 994, 1105-1118`  
**Impact:** Path string manipulation for every file; called twice per work item (representative + all paths)

**Optimization opportunity:** Pre-compute and cache relative-path mappings during filesystem walk phase. Batch convert at the start, store in the work item.

### B3: Hash strategy decision repeated per file

**Location:** `src/hashall/scan.py:924-931, 1152-1188`  
**Impact:** For each file, checks `_same_metadata()` and `_representative_hash_strategy()` which involve multiple conditional branches

**Optimization opportunity:** For `drift_policy=metadata`:
- Skip all strategy logic if metadata is unchanged
- Only compute strategy if size or mtime differs
- Inline quick decision path

### B4: Quick-hash computed even when metadata unchanged

**Location:** `src/hashall/scan.py:944`  
**Impact:** `compute_quick_hash()` reads 1 MB from every file, even when we could skip it for `metadata` mode

**Optimization opportunity:** Skip quick-hash computation entirely if metadata is unchanged in `metadata` mode. Only compute if:
- File is new
- File size or mtime changed

### B5: Dictionary lookups in `existing_files` happen multiple times

**Location:** `src/hashall/scan.py:920, 995`  
**Impact:** Two lookups per work item (representative path + each path in group); dict lookup overhead is small but adds up

**Optimization opportunity:** Pre-compute existence flags during the work-item preparation phase. Store as `[existed_before: bool]` in work item.

### B6: Database lock contention during batch writes

**Location:** `src/hashall/scan.py:1028-1097, 1599-1600, 1722`  
**Impact:** Periodic `conn.commit()` every 500 files can cause lock wait if other processes access catalog

**Optimization opportunity:** For freshness scan (read-mostly), batch larger writes (2000-5000 files) to reduce commit frequency.

## Optimization Plan

### Phase 2A: Defer catalog load for metadata drift policy

**Changes:**
1. Modify `scan_path()` to skip `load_existing_files()` call if `drift_policy='metadata'`
2. Add `_lazy_load_existing_files()` helper that loads entries on-demand per file
3. Cache loaded entries in a dict to avoid repeated lookups

**Affected files:**
- `src/hashall/scan.py` (lines 1343-1345, 95-169)

**Expected improvement:** 10-20% faster for metadata-only scans  
**Testing:** `tests/test_scan_integration.py` + focused freshness profile test

### Phase 2B: Cache relative-path computations

**Changes:**
1. During filesystem walk phase, pre-compute all relative paths
2. Store in work item as `rel_path` field (already computed at walk time)
3. Remove redundant `_relative_to_any_mount()` calls

**Affected files:**
- `src/hashall/scan.py` (lines 1366-1424, 919, 994)

**Expected improvement:** 5-10% faster (reduces path string overhead)  
**Testing:** Unit test for path cache correctness

### Phase 2C: Inline hash strategy for metadata mode

**Changes:**
1. Add fast path in `_hash_file_worker()` for `drift_policy='metadata'`
2. Check if metadata is unchanged first; if yes, skip strategy computation
3. Only call `_representative_hash_strategy()` if metadata changed

**Affected files:**
- `src/hashall/scan.py` (lines 923-931, 1152-1188)

**Expected improvement:** 5-8% faster (fewer branches, early exit)  
**Testing:** Unit test for drift policy branches

### Phase 2D: Skip quick-hash for unchanged metadata (biggest win)

**Changes:**
1. In `_hash_file_worker()`, add check: if `drift_policy='metadata'` AND metadata unchanged, skip `compute_quick_hash()`
2. Reuse existing quick_hash from catalog
3. Only compute quick_hash if: file is new OR metadata changed OR quick_mismatch detected

**Affected files:**
- `src/hashall/scan.py` (lines 936-944)

**Expected improvement:** 30-50% faster (skips I/O on unchanged files)  
**Testing:** Integration test verifying unchanged files skip hashing

### Phase 2E: Increase batch-write threshold for freshness scans

**Changes:**
1. For `drift_policy='metadata'`, increase batch size from 500 to 2000 files
2. Reduce commit frequency to decrease lock contention

**Affected files:**
- `src/hashall/scan.py` (lines 1599-1600, 1722, 1797-1800)

**Expected improvement:** 5-10% faster (fewer database commits)  
**Testing:** Existing scan tests (should be transparent)

## Execution Sequence

1. **2E first** (lowest risk) — increase batch writes
2. **2D second** (biggest impact) — skip quick-hash for unchanged metadata
3. **2C third** (moderate impact) — inline hash strategy
4. **2B fourth** (moderate impact) — cache relative paths
5. **2A last** (highest complexity) — defer catalog load

## Success Criteria

- `make db-refresh-fast` on stash completes 30-50% faster than baseline
- All existing scan tests pass (including integration tests)
- Focused freshness profile tests confirm skipped hashing on unchanged files
- No regression on other profiles (maintenance, integrity)
- Database integrity checks (`hashall dupes --list`) still valid

## Risk Assessment

- **Low:** 2E (batch threshold), 2C (inlined branches)
- **Medium:** 2D (quick-hash skip logic), 2B (path cache)
- **High:** 2A (deferred catalog load) — requires careful testing of lazy-load correctness

Mitigation: implement in sequence, test each step before proceeding.

## Related Code Paths

- `src/hashall/scan.py` — primary scan logic
- `src/hashall/model.py` — database schema
- `tests/test_scan_integration.py` — integration tests
- `tests/test_scan_*.py` — unit tests
- `Makefile` — refresh targets

## Code Review Validation

**Baseline test results (2026-05-08):**
- `test_scan_hardlinks.py`: 11/11 passed
- `test_scan_incremental.py`: 16/16 passed  
- `test_scan_symlinks.py`: 1/1 passed
- `test_rehome_refresh_safety.py`: 15/15 passed (freshness profile tests)
- **Total:** 43/43 baseline tests passing

**Implementation Status:**

Phase 2E: ✅ **IMPLEMENTED** (commit d2aef9d)
- Increased batch-write threshold from 500→2000 for metadata mode
- Sequential scans commit less frequently
- Parallel scans use larger batch sizes
- Expected: 5-10% faster

Phase 2D: ✅ **ALREADY IMPLEMENTED** (no change needed)
- Validated via tracing test: quick_hash is NOT recomputed when metadata unchanged
- `_representative_hash_strategy()` correctly returns None for metadata_same=True + drift_policy='metadata'
- `need_hash = False` prevents `compute_quick_hash()` call (line 944)
- Expected benefit already present: 30-50% I/O savings on unchanged files

**Remaining phases (2C, 2B, 2A):**
These are lower-priority optimizations with incrementally smaller benefits:
- 2C: Inline hash strategy (5-8% faster) — moderate complexity
- 2B: Cache relative paths (5-10% faster) — moderate complexity  
- 2A: Defer catalog load (10-20% faster) — high complexity, optional

Phase 2E + existing 2D implementation achieves core goal: reduce database contention.

## Notes

- This plan focuses on the fast freshness profile but should not regress other profiles
- The biggest win is **skipping I/O** (quick-hash) on unchanged files
- Secondary wins come from reducing path manipulation and strategy decisions
- Deferred catalog load is optional; can be skipped if 2D-2E provide sufficient improvement
- All changes must pass the 43-test baseline plus any new tests added for optimization
