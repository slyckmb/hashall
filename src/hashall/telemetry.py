"""
Scan performance telemetry and adaptive preset tuning.

Collects performance metrics during scans to optimize preset recommendations.
"""

import json
import sqlite3
import statistics
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class ScanPerformanceMetrics:
    """Performance metrics for a scan execution."""

    # Scan configuration
    parallel: bool
    workers: Optional[int]
    batch_size: Optional[int]

    # File characteristics
    file_count: int
    avg_file_size: float
    median_file_size: float
    total_bytes: int

    # Performance metrics
    duration_seconds: float
    files_per_second: float
    bytes_per_second: float

    # Context
    device_id: int
    scan_timestamp: str
    preset_used: Optional[str] = None


class TelemetryCollector:
    """Collects and stores scan performance telemetry."""

    def __init__(self, db_path: Path):
        """Initialize telemetry collector."""
        self.db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self):
        """Create telemetry tables if they don't exist."""
        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_performance (
                id INTEGER PRIMARY KEY,
                scan_timestamp TEXT NOT NULL,
                device_id INTEGER NOT NULL,

                -- Configuration
                parallel BOOLEAN NOT NULL,
                workers INTEGER,
                batch_size INTEGER,
                preset_used TEXT,

                -- File characteristics
                file_count INTEGER NOT NULL,
                avg_file_size REAL NOT NULL,
                median_file_size REAL NOT NULL,
                total_bytes INTEGER NOT NULL,

                -- Performance metrics
                duration_seconds REAL NOT NULL,
                files_per_second REAL NOT NULL,
                bytes_per_second REAL NOT NULL,

                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_perf_preset
            ON scan_performance(preset_used)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_perf_avg_size
            ON scan_performance(avg_file_size)
        """)

        conn.commit()
        conn.close()

    def record_scan(self, metrics: ScanPerformanceMetrics):
        """Record scan performance metrics."""
        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            INSERT INTO scan_performance (
                scan_timestamp, device_id, parallel, workers, batch_size, preset_used,
                file_count, avg_file_size, median_file_size, total_bytes,
                duration_seconds, files_per_second, bytes_per_second
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.scan_timestamp,
            metrics.device_id,
            metrics.parallel,
            metrics.workers,
            metrics.batch_size,
            metrics.preset_used,
            metrics.file_count,
            metrics.avg_file_size,
            metrics.median_file_size,
            metrics.total_bytes,
            metrics.duration_seconds,
            metrics.files_per_second,
            metrics.bytes_per_second
        ))

        conn.commit()
        conn.close()

    def get_performance_by_preset(self, preset: str, limit: int = 50) -> List[ScanPerformanceMetrics]:
        """Get recent performance metrics for a preset."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT * FROM scan_performance
            WHERE preset_used = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (preset, limit)).fetchall()

        conn.close()

        return [self._row_to_metrics(row) for row in rows]

    def get_performance_by_size_range(
        self,
        min_size: float,
        max_size: float,
        limit: int = 50
    ) -> List[ScanPerformanceMetrics]:
        """Get performance metrics for files in size range."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT * FROM scan_performance
            WHERE avg_file_size >= ? AND avg_file_size < ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (min_size, max_size, limit)).fetchall()

        conn.close()

        return [self._row_to_metrics(row) for row in rows]

    def analyze_preset_performance(self, preset: str) -> Dict:
        """Analyze performance statistics for a preset."""
        metrics = self.get_performance_by_preset(preset)

        if not metrics:
            return {"error": "No data available for preset"}

        files_per_sec = [m.files_per_second for m in metrics]
        avg_sizes = [m.avg_file_size for m in metrics]

        return {
            "preset": preset,
            "sample_count": len(metrics),
            "avg_files_per_second": statistics.mean(files_per_sec),
            "median_files_per_second": statistics.median(files_per_sec),
            "min_files_per_second": min(files_per_sec),
            "max_files_per_second": max(files_per_sec),
            "avg_file_size": statistics.mean(avg_sizes),
            "typical_config": {
                "parallel": metrics[0].parallel,
                "workers": metrics[0].workers,
                "batch_size": metrics[0].batch_size
            }
        }

    def recommend_optimal_settings(self, avg_file_size: float) -> Dict:
        """
        Recommend optimal settings based on historical performance data.

        Returns configuration that achieved best files/sec for similar file sizes.
        """
        # Get historical data for similar file sizes (+/- 50%)
        min_size = avg_file_size * 0.5
        max_size = avg_file_size * 1.5

        similar_scans = self.get_performance_by_size_range(min_size, max_size, limit=100)

        if not similar_scans:
            return {
                "recommendation": "default",
                "reason": "No historical data for this file size",
                "confidence": "low"
            }

        # Find configuration with best performance
        best = max(similar_scans, key=lambda m: m.files_per_second)

        # Calculate confidence based on sample size
        confidence = "high" if len(similar_scans) >= 10 else "medium" if len(similar_scans) >= 3 else "low"

        return {
            "recommendation": {
                "parallel": best.parallel,
                "workers": best.workers,
                "batch_size": best.batch_size,
                "expected_files_per_sec": best.files_per_second
            },
            "reason": f"Based on {len(similar_scans)} scans with similar file sizes",
            "confidence": confidence,
            "sample_size": len(similar_scans),
            "avg_file_size_range": {
                "min": min_size,
                "max": max_size,
                "target": avg_file_size
            }
        }

    def _row_to_metrics(self, row: sqlite3.Row) -> ScanPerformanceMetrics:
        """Convert database row to ScanPerformanceMetrics."""
        return ScanPerformanceMetrics(
            parallel=bool(row['parallel']),
            workers=row['workers'],
            batch_size=row['batch_size'],
            file_count=row['file_count'],
            avg_file_size=row['avg_file_size'],
            median_file_size=row['median_file_size'],
            total_bytes=row['total_bytes'],
            duration_seconds=row['duration_seconds'],
            files_per_second=row['files_per_second'],
            bytes_per_second=row['bytes_per_second'],
            device_id=row['device_id'],
            scan_timestamp=row['scan_timestamp'],
            preset_used=row['preset_used']
        )


def generate_telemetry_report(db_path: Path, output_path: Optional[Path] = None):
    """Generate comprehensive telemetry report."""
    collector = TelemetryCollector(db_path)

    report = {
        "generated_at": datetime.now().isoformat(),
        "presets": {}
    }

    # Analyze each preset
    for preset in ["video", "audio", "books", "mixed"]:
        analysis = collector.analyze_preset_performance(preset)
        if "error" not in analysis:
            report["presets"][preset] = analysis

    # Recommendations for different file sizes
    report["size_recommendations"] = {}

    size_ranges = [
        ("tiny", 100 * 1024),           # 100KB
        ("small", 1 * 1024 * 1024),     # 1MB
        ("medium", 10 * 1024 * 1024),   # 10MB
        ("large", 100 * 1024 * 1024),   # 100MB
        ("huge", 500 * 1024 * 1024)     # 500MB
    ]

    for label, size in size_ranges:
        rec = collector.recommend_optimal_settings(size)
        report["size_recommendations"][label] = rec

    if output_path:
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"✅ Telemetry report saved to: {output_path}")

    return report
