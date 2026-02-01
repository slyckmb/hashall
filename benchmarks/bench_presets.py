#!/usr/bin/env python3
"""
Benchmark preset configurations on different file sizes.

Tests various worker/batch configurations on different file size distributions
to determine optimal settings empirically.
"""

import os
import sys
import time
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

# Add hashall to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hashall.scan import scan_path


def create_test_files(root: Path, count: int, avg_size: int, name: str):
    """Create test files with specified average size."""
    print(f"  Creating {count} files (~{avg_size / 1024 / 1024:.0f}MB avg) in {name}...", end=" ")

    test_dir = root / name
    test_dir.mkdir(exist_ok=True)

    for i in range(count):
        # Vary size +/- 20%
        size = int(avg_size * (0.8 + 0.4 * (i % 5) / 5))
        file_path = test_dir / f"file_{i:04d}.bin"

        with open(file_path, 'wb') as f:
            f.write(os.urandom(size))

    print("✓")
    return test_dir


def benchmark_config(
    path: Path,
    db_path: Path,
    parallel: bool,
    workers: int = None,
    batch_size: int = None
) -> Dict:
    """Benchmark a specific configuration."""
    # Clear DB before each test
    db_path.unlink(missing_ok=True)

    start = time.time()

    scan_path(
        db_path=db_path,
        root_path=path,
        parallel=parallel,
        workers=workers,
        batch_size=batch_size
    )

    duration = time.time() - start

    # Count files
    file_count = sum(1 for _ in path.rglob("*") if _.is_file())

    return {
        "parallel": parallel,
        "workers": workers,
        "batch_size": batch_size,
        "duration": duration,
        "file_count": file_count,
        "files_per_sec": file_count / duration if duration > 0 else 0
    }


def test_file_size_category(
    category: str,
    file_count: int,
    avg_size: int,
    test_root: Path,
    db_path: Path
):
    """Test different configurations on a file size category."""
    print(f"\n{'='*70}")
    print(f"Testing: {category}")
    print(f"  Files: {file_count}, Avg Size: {avg_size / 1024 / 1024:.1f}MB")
    print(f"{'='*70}\n")

    # Create test files
    test_dir = create_test_files(test_root, file_count, avg_size, category)

    # Configurations to test
    configs = [
        {"name": "Sequential", "parallel": False, "workers": None, "batch_size": None},
        {"name": "Parallel-2", "parallel": True, "workers": 2, "batch_size": 100},
        {"name": "Parallel-4", "parallel": True, "workers": 4, "batch_size": 100},
        {"name": "Parallel-8", "parallel": True, "workers": 8, "batch_size": 250},
        {"name": "Parallel-16", "parallel": True, "workers": 16, "batch_size": 500},
    ]

    results = []

    for config in configs:
        print(f"  Testing {config['name']}...", end=" ", flush=True)

        result = benchmark_config(
            path=test_dir,
            db_path=db_path,
            parallel=config['parallel'],
            workers=config['workers'],
            batch_size=config['batch_size']
        )

        result['config_name'] = config['name']
        results.append(result)

        print(f"{result['duration']:.2f}s ({result['files_per_sec']:.0f} files/sec)")

    # Find best
    best = max(results, key=lambda r: r['files_per_sec'])

    print(f"\n  🏆 WINNER: {best['config_name']}")
    print(f"     Speed: {best['files_per_sec']:.0f} files/sec")
    print(f"     Speedup vs sequential: {best['files_per_sec'] / results[0]['files_per_sec']:.2f}x")

    return results


def main():
    print("🔬 Preset Configuration Benchmark")
    print("=" * 70)
    print("\nThis benchmark tests different worker configurations on various")
    print("file sizes to determine optimal settings empirically.\n")

    # Create temp directory for tests
    test_root = Path(tempfile.mkdtemp(prefix="hashall_bench_"))
    db_path = test_root / "test.db"

    print(f"Test directory: {test_root}\n")

    try:
        all_results = {}

        # Test categories
        # Note: Using smaller files/counts for faster testing
        # Adjust for production benchmarks

        print("\n" + "="*70)
        print("PHASE 1: Small Files (Books/Documents)")
        print("="*70)
        all_results["books"] = test_file_size_category(
            category="books",
            file_count=500,
            avg_size=1 * 1024 * 1024,  # 1MB
            test_root=test_root,
            db_path=db_path
        )

        print("\n" + "="*70)
        print("PHASE 2: Medium Files (Audio)")
        print("="*70)
        all_results["audio"] = test_file_size_category(
            category="audio",
            file_count=200,
            avg_size=10 * 1024 * 1024,  # 10MB
            test_root=test_root,
            db_path=db_path
        )

        print("\n" + "="*70)
        print("PHASE 3: Large Files (Video)")
        print("="*70)
        all_results["video"] = test_file_size_category(
            category="video",
            file_count=50,
            avg_size=100 * 1024 * 1024,  # 100MB (reduced from 500MB for speed)
            test_root=test_root,
            db_path=db_path
        )

        # Summary
        print("\n" + "="*70)
        print("SUMMARY: Recommended Configurations")
        print("="*70)

        for category, results in all_results.items():
            best = max(results, key=lambda r: r['files_per_sec'])

            print(f"\n{category.upper()}:")
            print(f"  Best config: {best['config_name']}")
            print(f"  Performance: {best['files_per_sec']:.0f} files/sec")

            if best['parallel']:
                print(f"  Recommendation: parallel=True, workers={best['workers']}, batch_size={best['batch_size']}")
            else:
                print(f"  Recommendation: parallel=False (sequential)")

    finally:
        # Cleanup
        print(f"\n\nCleaning up test directory: {test_root}")
        shutil.rmtree(test_root)

    print("\n✅ Benchmark complete!")
    print("\nUse these results to update presets in:")
    print("  - hashall-smart-scan")
    print("  - hashall-auto-scan")
    print("  - hashall-plan-scan")


if __name__ == "__main__":
    main()
