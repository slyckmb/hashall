#!/usr/bin/env python3
"""
Benchmark different worker counts for fast hash mode.
Tests on actual pool/stash data to determine optimal parallelism.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from hashall.scan import scan_path

# Test directories - representative samples
TEST_DIRS = [
    Path("/pool/data/seeds/qigong/Six Healing Sounds"),
    Path("/pool/data/seeds/qigong/Qi Gong 30-Day Challenge with Lee Holden. 30 short workouts"),
]

# Worker counts to test
WORKER_COUNTS = [2, 4, 8, 12, 16]

# Temporary database for benchmarking
BENCH_DB = Path.home() / ".hashall" / "bench-workers.db"

def count_files(path: Path) -> int:
    """Count files in directory."""
    return len(list(path.rglob("*"))) if path.exists() else 0

def benchmark_workers(test_dir: Path, workers: int) -> dict:
    """Run scan with specific worker count and measure performance."""
    # Clean database for fresh run
    if BENCH_DB.exists():
        BENCH_DB.unlink()

    file_count = count_files(test_dir)

    print(f"  Testing workers={workers} on {file_count} files... ", end="", flush=True)

    start = time.time()
    scan_path(
        db_path=BENCH_DB,
        root_path=test_dir,
        parallel=True,
        workers=workers,
        batch_size=1000,
        hash_mode='fast',
        quiet=True
    )
    duration = time.time() - start

    files_per_sec = file_count / duration if duration > 0 else 0

    print(f"{files_per_sec:.2f} files/sec ({duration:.2f}s)")

    return {
        'workers': workers,
        'files': file_count,
        'duration': duration,
        'files_per_sec': files_per_sec
    }

def main():
    print("🧪 Fast Hash Worker Benchmark")
    print("=" * 60)

    all_results = []

    for test_dir in TEST_DIRS:
        if not test_dir.exists():
            print(f"⚠️  Skipping {test_dir} (not found)")
            continue

        print(f"\n📁 Testing: {test_dir.name}")
        print(f"   Path: {test_dir}")

        results = []
        for workers in WORKER_COUNTS:
            try:
                result = benchmark_workers(test_dir, workers)
                results.append(result)
            except Exception as e:
                print(f"❌ Error: {e}")

        if results:
            # Find best performer
            best = max(results, key=lambda r: r['files_per_sec'])
            print(f"\n   🏆 Best: workers={best['workers']} at {best['files_per_sec']:.2f} files/sec")
            all_results.extend(results)

    # Overall summary
    if all_results:
        print("\n" + "=" * 60)
        print("📊 Overall Summary:")
        print("=" * 60)

        # Group by worker count
        from collections import defaultdict
        by_workers = defaultdict(list)
        for r in all_results:
            by_workers[r['workers']].append(r['files_per_sec'])

        print(f"\n{'Workers':<10} {'Avg Files/sec':<15} {'Samples'}")
        print("-" * 40)
        for workers in sorted(by_workers.keys()):
            speeds = by_workers[workers]
            avg = sum(speeds) / len(speeds)
            print(f"{workers:<10} {avg:<15.2f} {len(speeds)}")

        # Best overall
        best_workers = max(by_workers.keys(), key=lambda w: sum(by_workers[w])/len(by_workers[w]))
        best_avg = sum(by_workers[best_workers]) / len(by_workers[best_workers])
        print(f"\n🎯 Optimal: workers={best_workers} (avg {best_avg:.2f} files/sec)")

    # Cleanup
    if BENCH_DB.exists():
        BENCH_DB.unlink()
    print("\n✅ Benchmark complete!")

if __name__ == "__main__":
    main()
