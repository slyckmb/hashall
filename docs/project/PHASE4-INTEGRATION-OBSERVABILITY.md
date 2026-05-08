# Phase 4: Integration and Observability

**Status:** Complete  
**Last updated:** 2026-05-08  
**Phase 3 baseline:** Changed-scope gating with ScanResult dataclass and pipeline gates (Phase 3A-3C)

## Goal

Integrate parallel scanning infrastructure into the CLI, provide comprehensive observability metrics, and create convenient make targets for optimized refresh workflows.

## Context

Phase 3 added changed-scope gating (detecting unchanged filesystem scopes to skip dedup work). Phase 4 completes the optimization suite by:

1. Adding parallel multi-root scanning infrastructure (`_scan_roots_parallel()` with ThreadPoolExecutor)
2. Exposing optimizations via CLI flags (`--gate-dedup-on-unchanged`, `--parallel-scans`)
3. Adding comprehensive metrics tracking (scan count, changes, dedup skips, elapsed times)
4. Creating convenient make targets for optimized workflows

## Technical Design

### 4A: Parallel Multi-Root Scanning Infrastructure

**Added to `src/rehome/auto.py`:**

```python
def _scan_roots_parallel(
    catalog_path: Path,
    roots_to_scan: list[tuple[str, str]],
    workers: int,
    scan_hash_mode: str,
    drift_policy: str,
    max_parallel: int = 4,
) -> dict[str, bool]:
    """Scan multiple roots concurrently using ThreadPoolExecutor.
    
    Returns dict[label: had_changes] with per-root change detection.
    Thread-safe via single shared db connection and proper locking.
    """
```

**Key features:**
- Uses `ThreadPoolExecutor` for concurrent scanning (not subprocess)
- Single shared database connection (SQLite-compatible)
- Per-root ScanResult with `had_changes` boolean flag
- Configurable max_parallel to avoid database contention
- Conditional activation: only if `parallel_scans > 0` AND (gating enabled OR >1 root)

**Integration:**
- Modified `run_refresh()` to collect roots into `roots_to_scan` list
- Conditional scanning logic: if `parallel_scans > 0`, use parallel; else sequential subprocess
- Maintains full backward compatibility (default: subprocess, old behavior)

### 4B: CLI Flag Integration

**Added to `src/rehome/cli.py` refresh command:**

```click
@click.option(
    "--gate-dedup-on-unchanged/--no-gate-dedup-on-unchanged",
    default=False,
    help="Phase 3B: Skip dedup if no changes detected in scanned roots."
)

@click.option(
    "--parallel-scans",
    type=int,
    default=0,
    help="Phase 4A: Max concurrent scans (0=disabled, use subprocess; recommended: 4)."
)
```

**Wiring:**
- Flags properly passed to `run_refresh()` in CLI handler
- Both optional with safe defaults (false/0) for backward compatibility
- Help text documents Phase and recommended values

**Example usage:**
```bash
# Enable changed-scope gating
python -m hashall refresh --profile freshness --gate-dedup-on-unchanged

# Enable 4-way parallel scanning
python -m hashall refresh --profile freshness --parallel-scans 4

# Combine both optimizations (recommended for fast repair cycles)
python -m hashall refresh --profile freshness --gate-dedup-on-unchanged --parallel-scans 4
```

### 4C: Observability and Metrics

**Metrics tracked in `run_refresh()`:**

```python
metrics = {
    "scan_roots_count": 0,           # Total roots scanned
    "scan_roots_with_changes": 0,    # Roots with detected changes
    "dedup_skipped_count": 0,        # 1 if gate applied, 0 otherwise
    "scan_start_time": time.time(),  # For elapsed time calculation
    "dedup_start_time": None,        # Set when dedup runs (not gated)
    "parallel_scans_enabled": bool,  # Phase 4A active
    "gate_dedup_enabled": bool,      # Phase 3B active
}
```

**Tracking points:**
- Parallel path: aggregate root counts and changes (lines 959-960)
- Sequential path: increment counters per root (lines 985-1049)
- Dedup gating: set `metrics["dedup_skipped_count"] = 1` when applied (line 1055)
- Dedup start: set `metrics["dedup_start_time"]` when dedup executes (line 1062)

**Summary reporting (new observability section):**
```
observability metrics:
  scans: 4 roots, 1 with changes
  scan elapsed: 2m15s
  dedup: skipped (gate: no changes detected)
  parallel scans: enabled (max=4)
```

Appears in final summary after status and log path (lines 1133-1143).

## Implementation Status

### 4A: Parallel Multi-Root Scanning Infrastructure ✅ **COMPLETE**

**Commit:** bcc45cb  
**Changes:**
- Added `parallel_scans` parameter to `run_refresh()` (default: 0, disabled)
- Added `_scan_roots_parallel()` helper with ThreadPoolExecutor
- Added `_scan_with_change_detection()` helper for in-process scanning
- Conditional scanning logic: parallel if enabled, else sequential subprocess
- All 15 refresh safety tests passing

### 4B: CLI Flag Integration ✅ **COMPLETE**

**Commit:** 72ae60a  
**Changes:**
- Added `--gate-dedup-on-unchanged / --no-gate-dedup-on-unchanged` flag
- Added `--parallel-scans INT` flag (default: 0, recommended: 4)
- Both flags properly wired to `run_refresh()` parameters
- Help text documents phases and recommendations
- All 15 refresh safety tests passing

### 4C: Observability and Metrics ✅ **COMPLETE**

**Commit:** 64eec12  
**Changes:**
- Comprehensive metrics dict with 7 tracked fields
- Metrics updated in parallel path (roots, changes)
- Metrics updated in sequential path (per-root)
- Dedup skip tracking when gate applied
- Dedup start time tracking when dedup runs
- New summary section with human-readable reporting
- All 15 refresh safety tests passing

### Makefile Targets ✅ **COMPLETE**

**Commit:** 5c84bfd  
**Changes:**
- `db-refresh-fast-gated` — Phase 3B: skip dedup on no changes
- `db-refresh-fast-parallel` — Phase 4A: 4-root concurrent scanning
- `db-refresh-fast-gated-parallel` — Both optimizations (recommended)
- All targets shown in `make help` with descriptions

## Success Criteria

✅ Parallel scanning infrastructure with ThreadPoolExecutor  
✅ Per-root `had_changes` detection for gating decisions  
✅ `--gate-dedup-on-unchanged` CLI flag working and wired  
✅ `--parallel-scans N` CLI flag working and wired  
✅ Comprehensive metrics tracking for scans, changes, dedup skips, timing  
✅ Summary metrics reporting in human-readable format  
✅ All 15 baseline refresh safety tests passing  
✅ Makefile targets for all optimization variants  
✅ Backward compatibility maintained (all new features optional)

## Risk Assessment

**Phase 4 as completed: Very Low Risk**

- **4A (Parallel scanning):** Low risk — in-process with proper thread-safety, optional feature
- **4B (CLI flags):** Very low risk — simple parameter wiring, backward compatible defaults
- **4C (Observability):** Very low risk — metrics tracking only, no behavioral change

All changes are additive and optional; sequential subprocess remains default.

## Performance Expectations

When optimizations enabled together (`--gate-dedup-on-unchanged --parallel-scans 4`):

- **Unchanged roots scenario:** 30-50% faster (Phase 3B skips dedup entirely)
- **Multi-root scanning:** 40-60% faster (Phase 4A concurrent scans vs sequential)
- **Unchanged trees scenario:** 30-50% faster scan I/O (Phase 2D: skip quick-hash on metadata match)
- **Database contention:** 5-10% faster (Phase 2E: larger batch writes)

**Combined:** 30-70% faster for typical incremental repair evidence cycles.

## Related Code Paths

- `src/rehome/auto.py` — run_refresh(), parallel scanning, metrics tracking
- `src/rehome/cli.py` — refresh command with new flags
- `src/hashall/scan.py` — ScanResult dataclass, scan logic
- `Makefile` — new convenience targets
- `docs/project/PHASE2-*.md`, `PHASE3-*.md` — prior optimization phases

## Notes

- Phase 4 completes the "fast refresh" optimization suite (Phases 1-4)
- Phases 2-4 are all optional; can be enabled/disabled independently
- Recommended usage: `make db-refresh-fast-gated-parallel` for fast repair cycles
- All metrics tracked with minimal overhead (no observable performance impact)
- Human-readable timing format supports visual performance tracking
- Future optimization opportunities: persistent metrics logging, performance trending

## Integration Testing Recommendations

1. **Test unchanged root scenario:**
   ```bash
   make db-refresh-fast-gated-parallel --dry-run
   # Verify: dedup skipped if no changes detected
   # Verify: metrics show 0 roots with changes
   ```

2. **Test multi-root parallel scanning:**
   ```bash
   make db-refresh-fast-parallel
   # Verify: all roots scanned concurrently
   # Verify: metrics show N roots, K with changes
   ```

3. **Test backward compatibility:**
   ```bash
   make db-refresh-fast  # Should behave exactly as before
   ```

4. **Compare sequential vs parallel:**
   ```bash
   time make db-refresh-fast-parallel
   time make db-refresh-fast
   # Measure actual speedup from parallel 4-root scanning
   ```
