#!/usr/bin/env python3
import argparse
import time
from pathlib import Path

from hashall.scan import scan_path


def count_files(root: Path) -> int:
    return sum(1 for p in root.rglob('*') if p.is_file())


def run_scan(label: str, db_path: Path, root_path: Path, parallel: bool, workers: int | None, batch_size: int | None):
    start = time.perf_counter()
    scan_path(db_path=db_path, root_path=root_path, parallel=parallel,
              workers=workers, batch_size=batch_size)
    elapsed = time.perf_counter() - start
    return elapsed


def main():
    parser = argparse.ArgumentParser(description="Benchmark hashall scan sequential vs parallel")
    parser.add_argument("--path", required=True, help="Root path to scan")
    parser.add_argument("--db-base", required=True, help="Base DB path (suffixes -seq/-par are added)")
    parser.add_argument("--parallel", action="store_true", help="Run parallel scan (after sequential)")
    parser.add_argument("--workers", type=int, default=None, help="Parallel worker count")
    parser.add_argument("--batch-size", type=int, default=None, help="Parallel batch size")
    args = parser.parse_args()

    root = Path(args.path)
    file_count = count_files(root)
    if file_count == 0:
        print("No files found. Exiting.")
        return

    db_base = Path(args.db_base)
    seq_db = db_base.with_suffix(db_base.suffix + ".seq") if db_base.suffix else Path(str(db_base) + ".seq")
    par_db = db_base.with_suffix(db_base.suffix + ".par") if db_base.suffix else Path(str(db_base) + ".par")

    print(f"Files: {file_count}")

    seq_elapsed = run_scan("sequential", seq_db, root, False, None, None)
    seq_fps = file_count / seq_elapsed
    print(f"sequential: {seq_elapsed:.3f}s, {seq_fps:.1f} files/sec")

    if args.parallel:
        par_elapsed = run_scan("parallel", par_db, root, True, args.workers, args.batch_size)
        par_fps = file_count / par_elapsed
        speedup = par_fps / seq_fps
        print(f"parallel:   {par_elapsed:.3f}s, {par_fps:.1f} files/sec")
        print(f"speedup:    {speedup:.2f}x")


if __name__ == "__main__":
    main()
