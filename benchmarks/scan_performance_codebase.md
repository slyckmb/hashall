# Performance Benchmark Results

**Test Configuration:**
- Files: 10,000
- Target directory: /home/michael/dev/work/hashall
- Database: /tmp/hashall_codebase_bench.db
- CPU cores: 16

## 1. First Scan Baseline

- Duration: 0.290s
- Rate: 34450.4 files/sec
- Database size: 0.53 MB

## 2. Rescan 0% Changed

- Duration: 0.064s
- Rate: 156315.5 files/sec
- **Speedup: 4.54x faster**

## 3. Rescan 1% Changed

- Files modified: 0
- Duration: 0.059s
- Rate: 169433.7 files/sec
- **Speedup: 4.92x faster**

## 4. Rescan 10% Changed

- Files modified: 0
- Duration: 0.062s
- Rate: 161548.0 files/sec
- **Speedup: 4.69x faster**

## 5. Database Growth

- Scans performed: 10
- Average size: 0.53 MB
- Size range: 0.53 - 0.53 MB
- **Variance: 0.00 MB (0.0%)**

## 6. Parallel vs Sequential

- Sequential: 0.217s (46104.8 files/sec)
- Parallel (16 workers): 0.328s (30444.4 files/sec)
- **Speedup: 0.66x**

## Summary

- Rescan 0% speedup: 4.54x ⚠️ BELOW TARGET (target: >10x)
- Database size variance: 0.0% ✅ PASS (target: <10%)
- Parallel speedup: 0.66x ⚠️ BELOW TARGET (target: >3.0x on 16 cores)
