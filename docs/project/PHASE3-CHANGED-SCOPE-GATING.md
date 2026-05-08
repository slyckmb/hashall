# Phase 3: Changed-Scope Gating

**Status:** Planning  
**Last updated:** 2026-05-08  
**Phase 2 baseline:** Batch-write threshold optimization committed (Phase 2E + 2D already implemented)

## Goal

Optimize the refresh pipeline by skipping dedup/link stages when file catalog shows no changes in a given scope, avoiding unnecessary computation on unchanged directory trees.

## Context

After Phase 2 scan optimization, the bottleneck shifts from scan I/O to downstream processing. The current `make db-refresh-fast` pipeline:

1. Scans all managed roots (`stash`, `pool-media`, etc.)
2. Skips dedup (Phase 1 freshness profile)
3. Syncs torrent-backed payloads

For incremental scans where most trees are unchanged:
- Scan is fast (metadata-mode, quick-hash skipped)
- But pipeline still runs full dedup validation even if no files changed
- Scan results show `files_scanned=0` for unchanged trees, but dedup runs anyway

## Optimization Opportunity

Add early gates in the refresh pipeline to:

1. **Post-scan detection:** After scan completes, check per-device/per-tree results
   - If `files_added=0 AND files_updated=0` for a tree, mark as "no changes"
   - Example: `/stash/media/torrents/seeding` has 0 changes → skip work on it

2. **Dedup skip gate:** Only run dedup on devices with actual changes
   - Current: `hashall dupes --device stash` runs even if nothing changed
   - Optimized: Skip entirely if scan reported 0 changes

3. **Link planner gate:** Only generate link plans for devices with changes
   - Current: `hashall link plan` runs full collision analysis
   - Optimized: Skip if dedup was skipped (no new candidates)

4. **Conditional stage execution:** Make dedup/link optional based on scan results
   - Update `run_refresh()` to accept `--skip-dedup-on-no-changes` flag
   - Parallelize: scan multiple roots in parallel, report per-root status
   - Gate: "if scan shows changes, run dedup; otherwise skip to payload sync"

## Technical Design

### 1. Scan Result Enrichment

Modify `src/hashall/scan.py` scan_path() to return structured result:

```python
@dataclass
class ScanResult:
    root_path: Path
    device_id: int
    files_scanned: int
    files_added: int
    files_updated: int
    files_deleted: int
    had_changes: bool  # True if any additions/updates/deletions
```

Return this from `scan_path()` instead of exit code only.

### 2. Refresh Pipeline Gate

Modify `src/rehome/auto.py` run_refresh() to:

```python
def run_refresh(..., gate_dedup_on_unchanged: bool = False):
    # Phase 1: Scan all roots
    results = []
    for root in [active_root, dest_root]:
        scan_result = scan_path(...) # Returns ScanResult
        results.append(scan_result)
        emit(f"Scan {root}: files_scanned={scan_result.files_scanned}, "
             f"changes={scan_result.had_changes}")

    # Phase 2: Gate dedup on results
    if gate_dedup_on_unchanged:
        devices_with_changes = [r.device_id for r in results if r.had_changes]
        if not devices_with_changes:
            emit("No changes detected; skipping dedup + link stages")
            # Skip to payload sync directly
            return run_payload_sync(...)

    # Continue with dedup/link as usual
    ...
```

### 3. Makefile Integration

Update `Makefile` targets:

```makefile
# Current (always runs dedup)
db-refresh-fast:
	python3 -m hashall refresh --profile freshness

# New (skips dedup if no changes detected)
db-refresh-fast-gated:
	python3 -m hashall refresh --profile freshness --gate-dedup-on-unchanged

# Testing: show what would be skipped
db-refresh-fast-dry:
	python3 -m hashall refresh --profile freshness --gate-dedup-on-unchanged --dry-run
```

## Implementation Phases

### 3A: Add ScanResult dataclass and return structure

**Changes:**
- Add `@dataclass ScanResult` to `src/hashall/scan.py`
- Modify `scan_path()` to compute `had_changes` flag
- Return `ScanResult` in addition to exit code

**Testing:** `tests/test_scan_*.py` updated to verify ScanResult fields

**Expected impact:** No performance change, purely structural

### 3B: Add refresh pipeline gate

**Changes:**
- Add `--gate-dedup-on-unchanged` flag to `refresh --profile` command
- Update `resolve_refresh_profile()` to accept gate flag
- Modify `run_refresh()` to skip dedup stages if gate enabled and no changes

**Testing:** `tests/test_rehome_refresh_safety.py` verify gate behavior

**Expected impact:** 
- 30-50% faster for unchanged trees (skip dedup entirely)
- 0% impact for trees with changes (same behavior)

### 3C: Parallel multi-root scanning

**Changes:**
- Scan multiple roots in parallel using ThreadPoolExecutor
- Collect per-root `ScanResult` objects
- Report status for each root before deciding on dedup

**Testing:** Verify parallel scan results match sequential results

**Expected impact:** 40-60% faster for systems with many roots (`stash`, `pool-media`, `pool-data`, `spare`)

## Success Criteria

- Freshness refresh with `--gate-dedup-on-unchanged` skips dedup when no changes
- All 41 baseline scan tests pass
- Refreshness profile tests confirm gate behavior
- No regression on existing profiles (maintenance, integrity)
- Parallel multi-root scan produces identical results to sequential

## Risk Assessment

- **Low:** 3A (ScanResult structure), 3B (conditional gate)
- **Medium:** 3C (parallel scanning) — requires careful thread safety

Mitigation: Implement in sequence, test thoroughly between phases.

## Related Code Paths

- `src/hashall/scan.py` — scan result collection
- `src/rehome/auto.py` — refresh pipeline
- `src/hashall/dupes.py` — dedup stage  
- `src/hashall/link_planner.py` — link stage
- `Makefile` — refresh targets

## Notes

- This phase addresses compute savings (avoiding dedup on unchanged roots)
- Phase 2 addressed I/O savings (batch writes, quick-hash skipping)
- Together: Phase 2 + 3 enable fast incremental refresh for repair cycles
- Future Phase 4 could optimize parallel I/O (concurrent root scanning)
