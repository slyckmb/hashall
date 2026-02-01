#!/usr/bin/env python3
"""
Comprehensive performance benchmarks for hashall incremental scanning.

Benchmarks:
1. First scan baseline - 10k files, measure time and rate
2. Rescan 0% changed - Immediate rescan, measure speedup
3. Rescan 1% changed - Modify 100 files, measure speedup
4. Rescan 10% changed - Modify 1000 files, measure speedup
5. Database growth - Run 10 scans, verify constant size
6. Parallel vs sequential - Compare speedups

Usage:
    python benchmarks/bench_incremental.py --target /path/to/test/dir --db /tmp/bench.db
"""

import argparse
import os
import random
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple

from hashall.scan import scan_path


class BenchmarkRunner:
    """Orchestrates performance benchmarks for hashall."""

    def __init__(self, target_dir: Path, db_path: Path, file_count: int = 10000):
        self.target_dir = target_dir
        self.db_path = db_path
        self.file_count = file_count
        self.results: Dict[str, dict] = {}

    def setup_test_files(self):
        """Create test directory with specified number of files."""
        print(f"\n📁 Setting up {self.file_count:,} test files...")

        if self.target_dir.exists():
            shutil.rmtree(self.target_dir)

        self.target_dir.mkdir(parents=True)

        # Create directory structure: 100 dirs with 100 files each (for 10k files)
        dirs_per_level = int(self.file_count ** 0.5)
        files_per_dir = self.file_count // dirs_per_level

        file_num = 0
        for dir_idx in range(dirs_per_level):
            dir_path = self.target_dir / f"dir_{dir_idx:04d}"
            dir_path.mkdir()

            for file_idx in range(files_per_dir):
                if file_num >= self.file_count:
                    break

                file_path = dir_path / f"file_{file_idx:04d}.dat"
                # Create files with random sizes (1KB to 100KB)
                size = random.randint(1024, 102400)
                data = os.urandom(size)
                file_path.write_bytes(data)
                file_num += 1

        actual_count = sum(1 for _ in self.target_dir.rglob("*.dat"))
        print(f"✅ Created {actual_count:,} files in {self.target_dir}")
        return actual_count

    def get_db_size(self) -> int:
        """Get database file size in bytes."""
        if not self.db_path.exists():
            return 0
        return self.db_path.stat().st_size

    def count_files_in_db(self) -> int:
        """Count total files in database across all device tables."""
        if not self.db_path.exists():
            return 0

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Get all device tables
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name LIKE 'files_%'
        """)
        tables = [row[0] for row in cursor.fetchall()]

        total = 0
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE status='active'")
            total += cursor.fetchone()[0]

        conn.close()
        return total

    def modify_files(self, percentage: float) -> int:
        """Modify a percentage of files by changing their content."""
        all_files = list(self.target_dir.rglob("*.dat"))
        count_to_modify = int(len(all_files) * (percentage / 100.0))

        print(f"✏️  Modifying {count_to_modify:,} files ({percentage}%)...")

        files_to_modify = random.sample(all_files, count_to_modify)
        for file_path in files_to_modify:
            # Append random data to change file
            with open(file_path, 'ab') as f:
                f.write(os.urandom(100))

        return count_to_modify

    def run_scan(self, label: str, parallel: bool = False, workers: int | None = None) -> dict:
        """Run a scan and return timing statistics."""
        print(f"\n🔍 Running: {label}")

        db_size_before = self.get_db_size()
        start = time.perf_counter()

        scan_path(
            db_path=self.db_path,
            root_path=self.target_dir,
            parallel=parallel,
            workers=workers,
            batch_size=500
        )

        elapsed = time.perf_counter() - start
        db_size_after = self.get_db_size()
        files_in_db = self.count_files_in_db()

        result = {
            'label': label,
            'elapsed': elapsed,
            'files_per_sec': self.file_count / elapsed,
            'db_size_before': db_size_before,
            'db_size_after': db_size_after,
            'db_growth': db_size_after - db_size_before,
            'files_in_db': files_in_db,
            'parallel': parallel,
            'workers': workers
        }

        print(f"   ⏱️  Duration: {elapsed:.3f}s")
        print(f"   📊 Rate: {result['files_per_sec']:.1f} files/sec")
        print(f"   💾 DB size: {db_size_after / 1024 / 1024:.2f} MB")

        return result

    def benchmark_first_scan(self):
        """Benchmark 1: First scan baseline."""
        print("\n" + "="*60)
        print("BENCHMARK 1: First Scan Baseline")
        print("="*60)

        # Clean database
        if self.db_path.exists():
            self.db_path.unlink()

        result = self.run_scan("First scan (sequential)", parallel=False)
        self.results['first_scan'] = result

    def benchmark_rescan_0_percent(self):
        """Benchmark 2: Rescan with 0% changes (immediate rescan)."""
        print("\n" + "="*60)
        print("BENCHMARK 2: Rescan 0% Changed")
        print("="*60)

        result = self.run_scan("Rescan 0% changed", parallel=False)

        # Calculate speedup
        baseline = self.results['first_scan']['elapsed']
        speedup = baseline / result['elapsed']
        result['speedup'] = speedup

        print(f"   ⚡ Speedup: {speedup:.2f}x faster")

        self.results['rescan_0pct'] = result

    def benchmark_rescan_1_percent(self):
        """Benchmark 3: Rescan with 1% changes."""
        print("\n" + "="*60)
        print("BENCHMARK 3: Rescan 1% Changed")
        print("="*60)

        modified = self.modify_files(1.0)
        result = self.run_scan(f"Rescan 1% changed ({modified} files)", parallel=False)

        # Calculate speedup
        baseline = self.results['first_scan']['elapsed']
        speedup = baseline / result['elapsed']
        result['speedup'] = speedup
        result['files_modified'] = modified

        print(f"   ⚡ Speedup: {speedup:.2f}x faster")

        self.results['rescan_1pct'] = result

    def benchmark_rescan_10_percent(self):
        """Benchmark 4: Rescan with 10% changes."""
        print("\n" + "="*60)
        print("BENCHMARK 4: Rescan 10% Changed")
        print("="*60)

        modified = self.modify_files(10.0)
        result = self.run_scan(f"Rescan 10% changed ({modified} files)", parallel=False)

        # Calculate speedup
        baseline = self.results['first_scan']['elapsed']
        speedup = baseline / result['elapsed']
        result['speedup'] = speedup
        result['files_modified'] = modified

        print(f"   ⚡ Speedup: {speedup:.2f}x faster")

        self.results['rescan_10pct'] = result

    def benchmark_database_growth(self):
        """Benchmark 5: Database growth across 10 scans."""
        print("\n" + "="*60)
        print("BENCHMARK 5: Database Growth (10 rescans)")
        print("="*60)

        db_sizes = []

        for i in range(10):
            # Modify 1% of files each time
            if i > 0:
                self.modify_files(1.0)

            result = self.run_scan(f"Scan {i+1}/10", parallel=False)
            db_sizes.append(result['db_size_after'])

        # Analyze growth
        avg_size = sum(db_sizes) / len(db_sizes)
        max_size = max(db_sizes)
        min_size = min(db_sizes)
        variance = max_size - min_size

        growth_result = {
            'scans': 10,
            'db_sizes': db_sizes,
            'avg_size_mb': avg_size / 1024 / 1024,
            'min_size_mb': min_size / 1024 / 1024,
            'max_size_mb': max_size / 1024 / 1024,
            'variance_mb': variance / 1024 / 1024,
            'variance_percent': (variance / avg_size) * 100
        }

        print(f"\n📊 Database Growth Analysis:")
        print(f"   Average size: {growth_result['avg_size_mb']:.2f} MB")
        print(f"   Min size: {growth_result['min_size_mb']:.2f} MB")
        print(f"   Max size: {growth_result['max_size_mb']:.2f} MB")
        print(f"   Variance: {growth_result['variance_mb']:.2f} MB ({growth_result['variance_percent']:.1f}%)")

        self.results['db_growth'] = growth_result

    def benchmark_parallel_vs_sequential(self):
        """Benchmark 6: Parallel vs sequential comparison."""
        print("\n" + "="*60)
        print("BENCHMARK 6: Parallel vs Sequential")
        print("="*60)

        # Clean database for fresh scan
        if self.db_path.exists():
            self.db_path.unlink()

        # Sequential scan
        seq_result = self.run_scan("Sequential scan", parallel=False)

        # Clean database again
        self.db_path.unlink()

        # Parallel scan with default workers
        par_result = self.run_scan("Parallel scan (auto workers)", parallel=True)

        # Calculate speedup
        speedup = seq_result['elapsed'] / par_result['elapsed']

        comparison = {
            'sequential': seq_result,
            'parallel': par_result,
            'speedup': speedup,
            'workers': par_result['workers'] or os.cpu_count()
        }

        print(f"\n⚡ Parallel Speedup: {speedup:.2f}x")
        print(f"   Workers: {comparison['workers']}")

        self.results['parallel_comparison'] = comparison

    def generate_report(self) -> str:
        """Generate markdown report of benchmark results."""
        report = []
        report.append("# Performance Benchmark Results")
        report.append("")
        report.append(f"**Test Configuration:**")
        report.append(f"- Files: {self.file_count:,}")
        report.append(f"- Target directory: {self.target_dir}")
        report.append(f"- Database: {self.db_path}")
        report.append(f"- CPU cores: {os.cpu_count()}")
        report.append("")

        # Benchmark 1: First scan
        if 'first_scan' in self.results:
            r = self.results['first_scan']
            report.append("## 1. First Scan Baseline")
            report.append("")
            report.append(f"- Duration: {r['elapsed']:.3f}s")
            report.append(f"- Rate: {r['files_per_sec']:.1f} files/sec")
            report.append(f"- Database size: {r['db_size_after'] / 1024 / 1024:.2f} MB")
            report.append("")

        # Benchmark 2: Rescan 0%
        if 'rescan_0pct' in self.results:
            r = self.results['rescan_0pct']
            report.append("## 2. Rescan 0% Changed")
            report.append("")
            report.append(f"- Duration: {r['elapsed']:.3f}s")
            report.append(f"- Rate: {r['files_per_sec']:.1f} files/sec")
            report.append(f"- **Speedup: {r['speedup']:.2f}x faster**")
            report.append("")

        # Benchmark 3: Rescan 1%
        if 'rescan_1pct' in self.results:
            r = self.results['rescan_1pct']
            report.append("## 3. Rescan 1% Changed")
            report.append("")
            report.append(f"- Files modified: {r.get('files_modified', 0):,}")
            report.append(f"- Duration: {r['elapsed']:.3f}s")
            report.append(f"- Rate: {r['files_per_sec']:.1f} files/sec")
            report.append(f"- **Speedup: {r['speedup']:.2f}x faster**")
            report.append("")

        # Benchmark 4: Rescan 10%
        if 'rescan_10pct' in self.results:
            r = self.results['rescan_10pct']
            report.append("## 4. Rescan 10% Changed")
            report.append("")
            report.append(f"- Files modified: {r.get('files_modified', 0):,}")
            report.append(f"- Duration: {r['elapsed']:.3f}s")
            report.append(f"- Rate: {r['files_per_sec']:.1f} files/sec")
            report.append(f"- **Speedup: {r['speedup']:.2f}x faster**")
            report.append("")

        # Benchmark 5: Database growth
        if 'db_growth' in self.results:
            r = self.results['db_growth']
            report.append("## 5. Database Growth")
            report.append("")
            report.append(f"- Scans performed: {r['scans']}")
            report.append(f"- Average size: {r['avg_size_mb']:.2f} MB")
            report.append(f"- Size range: {r['min_size_mb']:.2f} - {r['max_size_mb']:.2f} MB")
            report.append(f"- **Variance: {r['variance_mb']:.2f} MB ({r['variance_percent']:.1f}%)**")
            report.append("")

        # Benchmark 6: Parallel vs sequential
        if 'parallel_comparison' in self.results:
            r = self.results['parallel_comparison']
            report.append("## 6. Parallel vs Sequential")
            report.append("")
            report.append(f"- Sequential: {r['sequential']['elapsed']:.3f}s ({r['sequential']['files_per_sec']:.1f} files/sec)")
            report.append(f"- Parallel ({r['workers']} workers): {r['parallel']['elapsed']:.3f}s ({r['parallel']['files_per_sec']:.1f} files/sec)")
            report.append(f"- **Speedup: {r['speedup']:.2f}x**")
            report.append("")

        # Summary
        report.append("## Summary")
        report.append("")

        if 'rescan_0pct' in self.results:
            speedup = self.results['rescan_0pct']['speedup']
            status = "✅ PASS" if speedup >= 10 else "⚠️ BELOW TARGET"
            report.append(f"- Rescan 0% speedup: {speedup:.2f}x {status} (target: >10x)")

        if 'db_growth' in self.results:
            variance = self.results['db_growth']['variance_percent']
            status = "✅ PASS" if variance < 10 else "⚠️ HIGH VARIANCE"
            report.append(f"- Database size variance: {variance:.1f}% {status} (target: <10%)")

        if 'parallel_comparison' in self.results:
            speedup = self.results['parallel_comparison']['speedup']
            workers = self.results['parallel_comparison']['workers']
            target = 3.0 if workers >= 4 else 2.0
            status = "✅ PASS" if speedup >= target else "⚠️ BELOW TARGET"
            report.append(f"- Parallel speedup: {speedup:.2f}x {status} (target: >{target}x on {workers} cores)")

        report.append("")

        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(
        description="Run comprehensive performance benchmarks for hashall"
    )
    parser.add_argument(
        "--target",
        type=Path,
        help="Target directory for test files (default: temp dir)"
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="Database path (default: temp file)"
    )
    parser.add_argument(
        "--files",
        type=int,
        default=10000,
        help="Number of test files to create (default: 10000)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output markdown file for results (default: benchmarks/scan_performance.md)"
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip test file creation (use existing files)"
    )

    args = parser.parse_args()

    # Set defaults
    if args.target is None:
        args.target = Path(tempfile.mkdtemp(prefix="hashall_bench_"))

    if args.db is None:
        fd, db_path = tempfile.mkstemp(suffix=".db", prefix="hashall_bench_")
        os.close(fd)
        args.db = Path(db_path)

    if args.output is None:
        args.output = Path(__file__).parent / "scan_performance.md"

    print("="*60)
    print("HASHALL PERFORMANCE BENCHMARKS")
    print("="*60)
    print(f"Target: {args.target}")
    print(f"Database: {args.db}")
    print(f"Files: {args.files:,}")
    print(f"CPU cores: {os.cpu_count()}")

    runner = BenchmarkRunner(args.target, args.db, args.files)

    try:
        # Setup
        if not args.skip_setup:
            actual_count = runner.setup_test_files()
            runner.file_count = actual_count

        # Run benchmarks
        runner.benchmark_first_scan()
        runner.benchmark_rescan_0_percent()
        runner.benchmark_rescan_1_percent()
        runner.benchmark_rescan_10_percent()
        runner.benchmark_database_growth()
        runner.benchmark_parallel_vs_sequential()

        # Generate report
        report = runner.generate_report()

        # Save report
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)

        print("\n" + "="*60)
        print("BENCHMARK COMPLETE")
        print("="*60)
        print(f"\n📄 Report saved to: {args.output}")
        print("\n" + report)

    finally:
        # Cleanup if using temp directories
        if str(args.target).startswith("/tmp/hashall_bench_"):
            print(f"\n🧹 Cleaning up temporary directory: {args.target}")
            shutil.rmtree(args.target, ignore_errors=True)

        if str(args.db).startswith("/tmp/hashall_bench_"):
            print(f"🧹 Cleaning up temporary database: {args.db}")
            args.db.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
