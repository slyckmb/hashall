#!/usr/bin/env python3
"""
Benchmark different worker counts for fast hash mode with I/O monitoring.
Tests on actual pool/stash data to determine optimal parallelism.
Captures iotop readings to see if we're I/O bound.
"""

import sys
import time
import subprocess
import signal
from pathlib import Path
from threading import Thread
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent / "src"))

from hashall.scan import scan_path

# Test directories - representative samples
TEST_DIRS = [
    Path("/pool/data/seeds/qigong"),  # ~7537 files, large enough for I/O sampling
]

# Worker counts to test
WORKER_COUNTS = [2, 4, 8, 12, 16]

# Temporary database for benchmarking
BENCH_DB = Path.home() / ".hashall" / "bench-workers.db"

def count_files(path: Path) -> int:
    """Count files in directory."""
    return len(list(path.rglob("*"))) if path.exists() else 0

class IOMonitor:
    """Monitor I/O stats during benchmark."""

    def __init__(self):
        self.iotop_process = None
        self.io_samples = []
        self.monitoring = False

    def start(self):
        """Start iotop monitoring in background."""
        try:
            # Run iotop in batch mode, 1 second intervals
            # -b batch mode, -o only show processes doing I/O, -t add timestamp, -q quiet
            self.iotop_process = subprocess.Popen(
                ['sudo', 'iotop', '-b', '-o', '-t', '-d', '0.5', '-q', '-q', '-q'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            self.monitoring = True

            # Start thread to collect output
            self.monitor_thread = Thread(target=self._collect_io_stats, daemon=True)
            self.monitor_thread.start()

        except Exception as e:
            print(f"  ⚠️  Could not start iotop: {e}")
            self.monitoring = False

    def _collect_io_stats(self):
        """Collect I/O stats from iotop output."""
        current_sample = []

        for line in self.iotop_process.stdout:
            if not self.monitoring:
                break

            line = line.strip()
            if not line:
                continue

            # Look for Total DISK READ/WRITE lines
            if 'Total DISK READ' in line:
                # Parse: "Total DISK READ :      12.34 M/s | Total DISK WRITE :      56.78 M/s"
                parts = line.split('|')
                if len(parts) == 2:
                    try:
                        read_part = parts[0].split(':')[1].strip()
                        write_part = parts[1].split(':')[1].strip()

                        # Extract numbers (handle K/s, M/s, G/s)
                        read_value = self._parse_bandwidth(read_part)
                        write_value = self._parse_bandwidth(write_part)

                        self.io_samples.append({
                            'read_mb': read_value,
                            'write_mb': write_value,
                            'total_mb': read_value + write_value
                        })
                    except:
                        pass

    def _parse_bandwidth(self, bandwidth_str: str) -> float:
        """Parse bandwidth string like '12.34 M/s' to MB/s."""
        parts = bandwidth_str.split()
        if len(parts) >= 2:
            value = float(parts[0])
            unit = parts[1].upper()

            if unit.startswith('K'):
                return value / 1024
            elif unit.startswith('M'):
                return value
            elif unit.startswith('G'):
                return value * 1024
            elif unit.startswith('B'):
                return value / (1024 * 1024)

        return 0.0

    def stop(self):
        """Stop monitoring and return statistics."""
        self.monitoring = False

        if self.iotop_process:
            try:
                self.iotop_process.send_signal(signal.SIGTERM)
                self.iotop_process.wait(timeout=2)
            except:
                try:
                    self.iotop_process.kill()
                except:
                    pass

        if not self.io_samples:
            return None

        # Calculate statistics
        read_values = [s['read_mb'] for s in self.io_samples]
        write_values = [s['write_mb'] for s in self.io_samples]
        total_values = [s['total_mb'] for s in self.io_samples]

        return {
            'read_avg_mb': sum(read_values) / len(read_values),
            'read_peak_mb': max(read_values),
            'write_avg_mb': sum(write_values) / len(write_values),
            'write_peak_mb': max(write_values),
            'total_avg_mb': sum(total_values) / len(total_values),
            'total_peak_mb': max(total_values),
            'samples': len(self.io_samples)
        }

    def reset(self):
        """Reset samples for next test."""
        self.io_samples = []

def benchmark_workers(test_dir: Path, workers: int, io_monitor: IOMonitor) -> dict:
    """Run scan with specific worker count and measure performance."""
    # Clean database for fresh run
    if BENCH_DB.exists():
        BENCH_DB.unlink()

    file_count = count_files(test_dir)

    print(f"  Testing workers={workers:2d} on {file_count:4d} files... ", end="", flush=True)

    # Reset I/O monitor
    io_monitor.reset()

    # Small delay to let I/O settle
    time.sleep(0.5)

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

    # Small delay to capture final I/O
    time.sleep(0.5)

    files_per_sec = file_count / duration if duration > 0 else 0

    # Get I/O stats
    io_stats = io_monitor.stop() if not io_monitor.monitoring else None
    io_monitor.start()  # Restart for next test

    if io_stats:
        print(f"{files_per_sec:7.2f} files/sec ({duration:5.2f}s) | I/O: {io_stats['read_avg_mb']:6.2f} MB/s read, {io_stats['write_avg_mb']:6.2f} MB/s write (peak: {io_stats['total_peak_mb']:6.2f} MB/s)")
    else:
        print(f"{files_per_sec:7.2f} files/sec ({duration:5.2f}s)")

    return {
        'workers': workers,
        'files': file_count,
        'duration': duration,
        'files_per_sec': files_per_sec,
        'io_stats': io_stats
    }

def main():
    print("🧪 Fast Hash Worker Benchmark with I/O Monitoring")
    print("=" * 80)
    print("NOTE: Requires sudo for iotop. You may be prompted for password.\n")

    all_results = []

    # Start I/O monitor
    io_monitor = IOMonitor()
    io_monitor.start()

    if not io_monitor.monitoring:
        print("⚠️  I/O monitoring unavailable. Continuing without it...\n")

    for test_dir in TEST_DIRS:
        if not test_dir.exists():
            print(f"⚠️  Skipping {test_dir} (not found)")
            continue

        print(f"\n📁 Testing: {test_dir.name}")
        print(f"   Path: {test_dir}")

        results = []
        for workers in WORKER_COUNTS:
            try:
                result = benchmark_workers(test_dir, workers, io_monitor)
                results.append(result)
            except KeyboardInterrupt:
                print("\n\n⚠️  Interrupted by user")
                io_monitor.stop()
                return
            except Exception as e:
                print(f"❌ Error: {e}")

        if results:
            # Find best performer
            best = max(results, key=lambda r: r['files_per_sec'])
            print(f"\n   🏆 Best: workers={best['workers']} at {best['files_per_sec']:.2f} files/sec")
            all_results.extend(results)

    # Stop I/O monitor
    io_monitor.stop()

    # Overall summary
    if all_results:
        print("\n" + "=" * 80)
        print("📊 Overall Summary:")
        print("=" * 80)

        # Group by worker count
        by_workers = defaultdict(list)
        io_by_workers = defaultdict(list)

        for r in all_results:
            by_workers[r['workers']].append(r['files_per_sec'])
            if r.get('io_stats'):
                io_by_workers[r['workers']].append(r['io_stats'])

        print(f"\n{'Workers':<10} {'Avg Files/sec':<15} {'Avg I/O (MB/s)':<20} {'Samples'}")
        print("-" * 70)
        for workers in sorted(by_workers.keys()):
            speeds = by_workers[workers]
            avg_speed = sum(speeds) / len(speeds)

            io_str = "N/A"
            if workers in io_by_workers and io_by_workers[workers]:
                io_stats_list = io_by_workers[workers]
                avg_read = sum(s['read_avg_mb'] for s in io_stats_list) / len(io_stats_list)
                avg_write = sum(s['write_avg_mb'] for s in io_stats_list) / len(io_stats_list)
                io_str = f"R:{avg_read:5.1f} W:{avg_write:5.1f}"

            print(f"{workers:<10} {avg_speed:<15.2f} {io_str:<20} {len(speeds)}")

        # Best overall
        best_workers = max(by_workers.keys(), key=lambda w: sum(by_workers[w])/len(by_workers[w]))
        best_avg = sum(by_workers[best_workers]) / len(by_workers[best_workers])
        print(f"\n🎯 Optimal: workers={best_workers} (avg {best_avg:.2f} files/sec)")

        # I/O analysis
        if io_by_workers:
            print("\n💽 I/O Analysis:")
            for workers in sorted(io_by_workers.keys()):
                io_stats_list = io_by_workers[workers]
                avg_total = sum(s['total_avg_mb'] for s in io_stats_list) / len(io_stats_list)
                peak_total = max(s['total_peak_mb'] for s in io_stats_list)
                print(f"   workers={workers:2d}: avg={avg_total:6.2f} MB/s, peak={peak_total:6.2f} MB/s")

    # Cleanup
    if BENCH_DB.exists():
        BENCH_DB.unlink()
    print("\n✅ Benchmark complete!")

if __name__ == "__main__":
    main()
