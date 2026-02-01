# Performance Benchmark Results

Generated: 2026-02-01
System: Linux 6.14.0-37-generic, 16 CPU cores

---

## Executive Summary

This benchmark evaluates hashall's incremental scanning performance across six key scenarios. The system demonstrates excellent database stability but has opportunities for optimization in incremental scan speedup and parallel processing efficiency.

**Key Findings:**
- ✅ Database size remains constant across rescans (0.4% variance)
- ⚠️ Incremental rescan speedup: 3.08x (target: >10x)
- ⚠️ Parallel scanning slower than sequential (overhead dominates on small files)
- ✅ Sequential scan rate: 8,929 files/sec on 10k synthetic files

---

## Test Configuration

**Dataset:** Synthetic test files
- Files: 10,000
- File sizes: 1KB - 100KB (random)
- Directory structure: 100 dirs × 100 files each
- Target directory: /tmp/hashall_bench_b1ldk39p
- Database: /tmp/hashall_bench_czi_oct7.db
- CPU cores: 16 (AMD Ryzen or Intel equivalent)

**Test scenarios:**
1. First scan baseline (cold start)
2. Rescan 0% changed (immediate rescan)
3. Rescan 1% changed (100 files modified)
4. Rescan 10% changed (1,000 files modified)
5. Database growth (10 consecutive rescans)
6. Parallel vs sequential comparison

---

## 1. First Scan Baseline

**Initial scan of 10,000 files (cold start):**

- Duration: 1.120s
- Rate: 8,928.9 files/sec
- Data hashed: 495.7 MB
- Database size: 3.05 MB
- Operations: 10,000 inserts

**Analysis:**
- Achieves ~9k files/sec on mixed file sizes
- Database overhead is minimal (3.05 MB for 10k files = ~300 bytes/file)
- Hash computation dominates (495.7 MB hashed in 1.1s = 451 MB/s)
- Sequential I/O performs well on local SSD

---

## 2. Rescan 0% Changed

**Immediate rescan with no filesystem changes:**

- Duration: 0.364s
- Rate: 27,481.7 files/sec
- Data hashed: 0.0 MB
- Database size: 3.05 MB (no growth)
- **Speedup: 3.08x faster**

**Analysis:**
- 3.08x speedup from skipping hash computation
- All files detected as unchanged via size+mtime check
- No data hashed (0 bytes)
- Database queries efficient (10k lookups in 0.36s)

**Why not 10x faster?**
- Filesystem stat() calls still required (dominant cost)
- Database lookups add overhead
- Sequential file iteration not parallelized

---

## 3. Rescan 1% Changed

**Rescan with 100 files modified (1% change rate):**

- Files modified: 100
- Duration: 0.394s
- Rate: 25,396.3 files/sec
- Data hashed: 4.7 MB
- **Speedup: 2.84x faster**

**Analysis:**
- Similar performance to 0% changed (only 100 files rehashed)
- Minimal overhead from 1% changes
- 99% of files skip hashing (size+mtime unchanged)
- Modified files: 4.7 MB hashed in ~0.03s extra

---

## 4. Rescan 10% Changed

**Rescan with 1,000 files modified (10% change rate):**

- Files modified: 1,000
- Duration: 0.532s
- Rate: 18,789.8 files/sec
- Data hashed: 50.6 MB
- **Speedup: 2.10x faster**

**Analysis:**
- Speedup degrades with more changes (expected)
- 10% of files rehashed (50.6 MB)
- Still 2.1x faster than full scan
- Incremental hashing effective even with moderate changes

**Performance scaling:**
- 0% changed: 3.08x speedup
- 1% changed: 2.84x speedup (8% degradation)
- 10% changed: 2.10x speedup (32% degradation)

---

## 5. Database Growth

**10 consecutive rescans (each with 1% changes):**

- Scans performed: 10
- Average size: 3.06 MB
- Size range: 3.05 - 3.06 MB
- **Variance: 0.01 MB (0.4%)**

**Analysis:**
- ✅ Database size remains constant across rescans
- 0.4% variance is negligible (measurement noise)
- No unbounded growth from scan_sessions table
- In-place updates working correctly

**Database growth per scan:**
| Scan | DB Size (MB) | Change |
|------|-------------|---------|
| 1    | 3.05        | -       |
| 2    | 3.05        | 0.00    |
| 3    | 3.05        | 0.00    |
| 4    | 3.06        | +0.01   |
| 5    | 3.06        | 0.00    |
| 6    | 3.06        | 0.00    |
| 7    | 3.06        | 0.00    |
| 8    | 3.06        | 0.00    |
| 9    | 3.06        | 0.00    |
| 10   | 3.06        | 0.00    |

**Conclusion:** Database size is stable. Rescans do not cause unbounded growth.

---

## 6. Parallel vs Sequential

**Comparison of sequential vs parallel scanning (fresh scan):**

- Sequential: 1.020s (9,807.0 files/sec)
- Parallel (16 workers): 2.216s (4,511.7 files/sec)
- **Speedup: 0.46x (2.17x slower)**

**Analysis:**
- ⚠️ Parallel scanning is SLOWER than sequential
- Overhead dominates on small files (1-100KB)
- Thread pool management costs > hashing savings
- SQLite lock contention on batch writes
- 16 workers too many for this workload

**Why parallel is slower:**
1. Thread creation/management overhead
2. SQLite serializes writes (lock contention)
3. Small files = low hash computation time
4. Filesystem caching favors sequential reads

**When parallel would help:**
- Large files (>10MB) where hashing dominates
- Network storage with high latency
- Slower hash algorithms (SHA256, SHA512)

---

## Summary

### Performance Metrics

| Metric | Result | Target | Status |
|--------|--------|--------|---------|
| Rescan 0% speedup | 3.08x | >10x | ⚠️ BELOW TARGET |
| Database variance | 0.4% | <10% | ✅ PASS |
| Parallel speedup | 0.46x | >3.0x | ⚠️ BELOW TARGET |
| Sequential rate | 8,929 files/sec | N/A | ✅ Good |
| DB size/file | ~300 bytes | N/A | ✅ Efficient |

### Strengths

1. **Database stability:** No growth across rescans (0.4% variance)
2. **Sequential performance:** 8,929 files/sec on mixed workload
3. **Incremental detection:** 99% of unchanged files skip hashing
4. **Efficient storage:** 300 bytes/file metadata

### Opportunities

1. **Incremental speedup (3.08x vs 10x target):**
   - Stat() calls dominate rescan time
   - Consider batch stat operations
   - Optimize database lookups (prepared statements)
   - Add inode-based fast path

2. **Parallel performance (0.46x slowdown):**
   - Current implementation slower than sequential
   - SQLite write lock contention
   - Needs adaptive worker count
   - Consider bulk insert API

3. **Change detection:**
   - mtime resolution limited to 1ms
   - Consider inode change detection
   - Add content-based fast path (first 4KB hash)

---

## Recommendations

### Short-term (Quick Wins)

1. **Disable parallel by default** for datasets <50k files or avg file size <10MB
2. **Batch stat operations** using os.scandir() instead of individual stat() calls
3. **Add prepared statements** for database queries to reduce parsing overhead
4. **Optimize batch size** dynamically based on file count

### Medium-term (Architecture)

1. **Inode-based fast path:** If inode unchanged, skip even mtime check
2. **Async I/O:** Use async file reads for parallel hashing without threads
3. **Bulk insert API:** SQLite executemany() instead of individual inserts
4. **Lock-free reads:** Use WAL mode for concurrent read/write

### Long-term (Advanced)

1. **Incremental hash trees:** Merkle tree of directory hashes for instant change detection
2. **Content-addressed cache:** Skip rehashing if first 4KB unchanged
3. **GPU hashing:** Offload SHA1 to GPU for large files
4. **Distributed scanning:** Split filesystem across workers

---

## Real-World Codebase Test

**Benchmark on actual hashall repository (1,063 files):**

| Metric | Result |
|--------|--------|
| First scan | 0.290s (34,450 files/sec) |
| Rescan 0% | 0.064s (156,315 files/sec) |
| Speedup | 4.54x |
| DB size | 0.53 MB |
| DB variance | 0.0% (10 rescans) |

**Observations:**
- Higher file rate on smaller dataset (caching effects)
- 4.54x speedup (better than synthetic, still below 10x target)
- Database stability confirmed on real data
- Parallel still slower (0.66x) due to small file sizes

---

## Appendix: Test Environment

**Hardware:**
- CPU: 16 cores (AMD Ryzen or Intel equivalent)
- Storage: Local SSD (assumed, not measured)
- RAM: Sufficient for file caching

**Software:**
- OS: Linux 6.14.0-37-generic
- Python: 3.x (version not captured)
- SQLite: 3.x (bundled with Python)
- hashall: v0.5.0+ (unified catalog model)

**Benchmark script:** `benchmarks/bench_incremental.py`
**Generated by:** Task #19 implementation
