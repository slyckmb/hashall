# Hashall Performance Benchmarks

This directory contains performance benchmarking tools for hashall's incremental scanning system.

## Overview

The benchmark suite evaluates hashall's performance across six key scenarios:

1. **First scan baseline** - Initial scan of files (cold start)
2. **Rescan 0% changed** - Immediate rescan with no changes
3. **Rescan 1% changed** - Rescan after modifying 1% of files
4. **Rescan 10% changed** - Rescan after modifying 10% of files
5. **Database growth** - Verify constant DB size across multiple rescans
6. **Parallel vs sequential** - Compare parallel and sequential scanning

## Files

- `bench_incremental.py` - Comprehensive benchmark suite (runs all 6 benchmarks)
- `scan_performance.md` - Latest benchmark results with detailed analysis
- `scan_performance_codebase.md` - Benchmark results on hashall repository itself
- `README.md` - This file

## Quick Start

### Run All Benchmarks (Synthetic Data)

Creates temporary test files and runs all benchmarks:

```bash
python3 benchmarks/bench_incremental.py
```

This will:
- Create 10,000 synthetic test files
- Run all 6 benchmarks
- Generate a report at `benchmarks/scan_performance.md`
- Clean up temporary files

### Run on Existing Directory

Benchmark an existing directory (e.g., your codebase):

```bash
python3 benchmarks/bench_incremental.py \
    --target /path/to/directory \
    --skip-setup
```

### Custom Configuration

```bash
python3 benchmarks/bench_incremental.py \
    --files 50000 \
    --target /tmp/my_test \
    --db /tmp/my_bench.db \
    --output /tmp/results.md
```

## Options

- `--target PATH` - Directory to scan (default: temp dir)
- `--db PATH` - Database path (default: temp file)
- `--files N` - Number of test files to create (default: 10000)
- `--output PATH` - Output markdown file (default: benchmarks/scan_performance.md)
- `--skip-setup` - Skip test file creation (use existing files)

## Understanding the Results

### Expected Performance Targets

| Benchmark | Target | Actual (10k files) | Status |
|-----------|--------|-------------------|---------|
| Rescan 0% speedup | >10x | 3.08x | ⚠️ Below |
| Database growth | <10% variance | 0.4% | ✅ Pass |
| Parallel speedup (4+ cores) | >3x | 0.46x | ⚠️ Below |

### Key Metrics

- **Files/sec** - Throughput rate
- **Speedup** - Performance vs baseline
- **DB size** - Database storage overhead
- **Variance** - Database size stability

## Interpreting Results

### Good Results

- Database size variance <10% (indicates stable rescans)
- Sequential scan rate >5,000 files/sec
- Incremental speedup >3x for 0% changed

### Performance Factors

**What makes scans faster:**
- SSD storage (vs HDD)
- Local filesystem (vs network)
- Larger files (amortizes overhead)
- More CPU cores (for parallel mode)

**What makes scans slower:**
- Network storage (NFS, SMB)
- Many small files (<1KB)
- Slow hash algorithm (SHA256 vs SHA1)
- SQLite lock contention

## Benchmark Details

### 1. First Scan Baseline

Measures initial scan performance (cold start).

**What it tests:**
- File discovery (os.walk)
- Hash computation (SHA1)
- Database inserts
- Overall throughput

**Expected:** 5,000-15,000 files/sec on local SSD

### 2. Rescan 0% Changed

Measures incremental rescan with no changes.

**What it tests:**
- Size+mtime detection
- Database lookup efficiency
- Stat() call overhead

**Expected:** 3-10x faster than first scan

### 3. Rescan 1% Changed

Measures incremental rescan with minimal changes.

**What it tests:**
- Selective rehashing
- Update efficiency
- Mixed workload

**Expected:** Similar to 0% changed (minimal impact from 1% changes)

### 4. Rescan 10% Changed

Measures incremental rescan with moderate changes.

**What it tests:**
- Performance scaling with change rate
- Hash computation impact
- Update batching

**Expected:** 2-5x faster than first scan

### 5. Database Growth

Measures database size stability across 10 rescans.

**What it tests:**
- In-place updates (vs snapshots)
- Table bloat prevention
- Long-term stability

**Expected:** <10% variance, ideally <1%

### 6. Parallel vs Sequential

Compares parallel and sequential scanning modes.

**What it tests:**
- Thread pool efficiency
- SQLite lock contention
- Overhead vs throughput

**Expected:**
- Large files (>10MB): 2-4x speedup
- Small files (<1MB): May be slower due to overhead

## Troubleshooting

### Parallel Mode Slower Than Sequential

This is expected for:
- Small files (<1MB average)
- Fast storage (NVMe SSD)
- <10,000 files

**Solution:** Use sequential mode for these workloads.

### Low Rescan Speedup (<2x)

Possible causes:
- Filesystem not caching stat() results
- Network storage with high latency
- Database on slow storage

**Solution:** Ensure database and files on fast local storage.

### High Database Variance (>10%)

Possible causes:
- SQLite autovacuum enabled
- Large scan_sessions table
- Many deletions

**Solution:** Check database schema and vacuum settings.

## Adding New Benchmarks

To add a new benchmark scenario:

1. Add a method to `BenchmarkRunner` class:
   ```python
   def benchmark_my_test(self):
       """Benchmark description."""
       result = self.run_scan("My test")
       self.results['my_test'] = result
   ```

2. Call it in `main()`:
   ```python
   runner.benchmark_my_test()
   ```

3. Add reporting in `generate_report()`:
   ```python
   if 'my_test' in self.results:
       report.append("## My Test Results")
       # ... formatting ...
   ```

## Performance Optimization Guide

Based on benchmark results, here are recommended optimizations:

### For Large Datasets (>100k files)

1. **Use parallel mode** if average file size >10MB
2. **Increase batch size** to reduce commit overhead
3. **Enable WAL mode** for SQLite to reduce lock contention
4. **Use prepared statements** for faster queries

### For Small Files (<1MB average)

1. **Use sequential mode** (parallel has too much overhead)
2. **Optimize stat() batching** with os.scandir()
3. **Cache database lookups** for adjacent files
4. **Consider inode-based fast path**

### For Network Storage

1. **Always use parallel mode** to hide latency
2. **Increase worker count** (2x CPU cores)
3. **Batch file operations** to reduce round trips
4. **Consider local database** (not on network)

## Related Documentation

- [Architecture](../docs/architecture.md) - Overall system design
- [CLI Reference](../docs/cli.md) - Command-line usage
- [Scan Implementation](../src/hashall/scan.py) - Source code

## Contributing

To improve benchmarks:

1. Add new test scenarios
2. Improve result analysis
3. Add visualization (charts/graphs)
4. Test on different hardware/filesystems
5. Compare with other tools (rsync, rclone, etc.)

---

**Last updated:** 2026-02-01
**Benchmark version:** Task #19 implementation
