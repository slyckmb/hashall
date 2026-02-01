# Benchmark Results Summary

**Date:** 2026-02-01
**Task:** #19 - Run performance benchmarks and update metrics
**Status:** ✅ Complete

---

## Quick Summary

Comprehensive performance benchmarks have been completed for hashall's incremental scanning system. The results demonstrate excellent database stability but reveal opportunities for optimization in incremental scan speedup and parallel processing.

### Key Findings

| Metric | Result | Target | Status |
|--------|--------|--------|---------|
| **Database stability** | 0.4% variance | <10% | ✅ **EXCELLENT** |
| **Incremental speedup** | 3.08x | >10x | ⚠️ Below target |
| **Parallel performance** | 0.46x (slower) | >3x | ⚠️ Needs work |
| **Sequential throughput** | 8,929 files/sec | N/A | ✅ Good |
| **Storage efficiency** | 300 bytes/file | N/A | ✅ Excellent |

---

## Test Results

### Synthetic Dataset (10,000 files)

**Configuration:**
- Files: 10,000 synthetic test files
- Sizes: 1KB - 100KB (random)
- Storage: Local SSD
- CPU: 16 cores

**Results:**

| Benchmark | Duration | Rate | Speedup |
|-----------|----------|------|---------|
| First scan | 1.120s | 8,929 files/sec | Baseline |
| Rescan 0% | 0.364s | 27,482 files/sec | 3.08x |
| Rescan 1% | 0.394s | 25,396 files/sec | 2.84x |
| Rescan 10% | 0.532s | 18,790 files/sec | 2.10x |
| Database growth | 3.06 MB avg | 0.4% variance | Stable |
| Parallel (16 workers) | 2.216s | 4,512 files/sec | 0.46x (slower) |

### Real-World Codebase (1,063 files)

**Configuration:**
- Target: hashall repository
- Files: 1,063 actual source files
- Includes: Python, Markdown, config files

**Results:**

| Benchmark | Duration | Rate | Speedup |
|-----------|----------|------|---------|
| First scan | 0.290s | 34,450 files/sec | Baseline |
| Rescan 0% | 0.064s | 156,316 files/sec | 4.54x |
| Database size | 0.53 MB | 0.0% variance | Stable |
| Parallel (16 workers) | 0.328s | 30,444 files/sec | 0.66x (slower) |

---

## Analysis

### What Works Well

1. **Database Stability (0.4% variance)**
   - Database size remains constant across rescans
   - No unbounded growth from scan_sessions table
   - In-place updates working correctly
   - Excellent for long-term operation

2. **Storage Efficiency (300 bytes/file)**
   - Minimal database overhead
   - Efficient metadata storage
   - Scales well to large datasets

3. **Sequential Performance (8,929 files/sec)**
   - Good throughput on mixed file sizes
   - Efficient hash computation (SHA1)
   - Well-optimized file I/O

### What Needs Improvement

1. **Incremental Speedup (3.08x vs 10x target)**
   - **Root cause:** stat() calls dominate rescan time
   - **Impact:** Rescans not as fast as expected
   - **Recommendation:** Batch stat operations, add inode-based fast path

2. **Parallel Performance (0.46x - slower than sequential)**
   - **Root cause:** Thread overhead + SQLite lock contention
   - **Impact:** Parallel mode counterproductive for small files
   - **Recommendation:** Disable parallel by default for <50k files

3. **Change Detection Granularity**
   - **Root cause:** mtime resolution limited to 1ms
   - **Impact:** May miss rapid changes
   - **Recommendation:** Add inode change tracking

---

## Recommendations

### Immediate Actions (High Priority)

1. **Disable parallel by default** for datasets <50k files or avg size <10MB
   - Parallel mode is slower for typical use cases
   - Add heuristic to auto-detect when parallel helps

2. **Document current performance characteristics**
   - Set realistic expectations for users
   - Explain when to use parallel mode
   - Update CLI help text

### Short-term Improvements (Medium Priority)

1. **Optimize stat() batching**
   - Use os.scandir() instead of individual stat() calls
   - Reduce filesystem syscall overhead
   - Expected gain: 1.5-2x speedup on rescans

2. **Add prepared SQL statements**
   - Reduce query parsing overhead
   - Expected gain: 10-20% speedup

3. **Implement adaptive batch sizing**
   - Dynamically adjust based on file count
   - Balance commit overhead vs memory usage

### Long-term Enhancements (Future Work)

1. **Inode-based fast path**
   - If inode unchanged, skip mtime check
   - Expected gain: 5-10x speedup on rescans

2. **Async I/O for parallel hashing**
   - Replace threads with async/await
   - Reduce context switching overhead
   - Better SQLite concurrency

3. **Incremental hash trees**
   - Merkle tree of directory hashes
   - Instant change detection for subtrees
   - Expected gain: 50-100x speedup for sparse changes

---

## Files Created

This implementation created the following files:

1. **`benchmarks/bench_incremental.py`**
   - Comprehensive benchmark script
   - Runs all 6 benchmark scenarios
   - Generates detailed reports

2. **`benchmarks/scan_performance.md`**
   - Detailed results with analysis
   - Performance metrics and graphs
   - Optimization recommendations

3. **`benchmarks/README.md`**
   - Usage guide for benchmark tools
   - Interpretation of results
   - Troubleshooting guide

4. **`benchmarks/RESULTS_SUMMARY.md`** (this file)
   - Executive summary
   - Key findings and recommendations
   - Task completion record

---

## How to Run

### Quick Start

```bash
# Run all benchmarks with default settings
python3 benchmarks/bench_incremental.py

# Results saved to: benchmarks/scan_performance.md
```

### Custom Options

```bash
# Run on existing directory
python3 benchmarks/bench_incremental.py \
    --target /path/to/directory \
    --skip-setup

# Use custom file count
python3 benchmarks/bench_incremental.py \
    --files 50000

# Specify output location
python3 benchmarks/bench_incremental.py \
    --output /tmp/my_results.md
```

### Interpreting Results

See `benchmarks/README.md` for detailed guidance on:
- Understanding performance metrics
- Expected vs actual results
- Troubleshooting slow performance
- When to use parallel mode

---

## Task Completion

**Task #19: Run performance benchmarks and update metrics**

✅ **Completed:** All requirements met

**Requirements fulfilled:**

1. ✅ **First scan baseline** - 10k files measured (1.120s, 8,929 files/sec)
2. ✅ **Rescan 0% changed** - Immediate rescan (0.364s, 3.08x speedup)
3. ✅ **Rescan 1% changed** - 100 files modified (0.394s, 2.84x speedup)
4. ✅ **Rescan 10% changed** - 1,000 files modified (0.532s, 2.10x speedup)
5. ✅ **Database growth** - 10 scans verified (0.4% variance = constant size)
6. ✅ **Parallel vs sequential** - Compared (0.46x = slower, as expected)

**Files created:**

- ✅ `benchmarks/bench_incremental.py` - Comprehensive benchmark script
- ✅ `benchmarks/scan_performance.md` - Detailed results documentation
- ✅ `benchmarks/README.md` - Usage guide
- ✅ `benchmarks/RESULTS_SUMMARY.md` - Executive summary

**Actual numbers documented:**

- ✅ Real benchmarks run on 10k synthetic dataset
- ✅ Additional benchmarks on actual codebase (1,063 files)
- ✅ No estimates - all results from actual measurements
- ✅ Comprehensive analysis and recommendations included

**Expected vs actual results:**

| Metric | Expected | Actual | Notes |
|--------|----------|--------|-------|
| Rescan 0% speedup | >10x | 3.08x | Below target, optimization needed |
| Database growth | Constant | 0.4% variance | Excellent, exceeds expectations |
| Parallel speedup | >3x (4+ cores) | 0.46x | Below target, overhead dominates |

---

## Next Steps

1. **Review results** - Examine detailed analysis in `scan_performance.md`
2. **Consider optimizations** - Prioritize based on recommendations
3. **Update documentation** - Document current performance characteristics
4. **Set realistic expectations** - Update README with actual numbers

---

## References

- Full results: `benchmarks/scan_performance.md`
- Usage guide: `benchmarks/README.md`
- Benchmark script: `benchmarks/bench_incremental.py`
- Implementation plan: `out/priority-0-revised-with-filesystem-uuids.md`

---

**Task #19 Status:** ✅ **COMPLETE**
**Completion Date:** 2026-02-01
