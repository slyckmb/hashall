# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import os
import hashlib
import sqlite3
import uuid
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from tqdm import tqdm
from hashall.model import connect_db, init_db_schema

BATCH_SIZE = 500

def compute_sha1(file_path):
    h = hashlib.sha1()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def _hash_file_worker(file_path: str, root_path: Path):
    try:
        stat = os.stat(file_path)
        rel_path = str(Path(file_path).relative_to(root_path))
        sha1 = compute_sha1(file_path)
        return (rel_path, stat.st_size, stat.st_mtime, sha1, stat.st_ino, stat.st_dev)
    except Exception as e:
        print(f"⚠️ Could not process: {file_path} ({e})")
        return None

def _write_batch(cursor, scan_session_id: int, rows: list[tuple]):
    if not rows:
        return
    cursor.executemany("""
        INSERT OR REPLACE INTO files (path, size, mtime, sha1, scan_session_id, inode, device_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [(rel_path, size, mtime, sha1, scan_session_id, inode, device_id) for (
        rel_path, size, mtime, sha1, inode, device_id
    ) in rows])

def scan_path(db_path: Path, root_path: Path, parallel: bool = False,
              workers: int | None = None, batch_size: int | None = None):
    conn = connect_db(db_path)
    init_db_schema(conn)
    cursor = conn.cursor()
    scan_id = str(uuid.uuid4())
    root_str = str(root_path)

    cursor.execute(
        "INSERT INTO scan_sessions (scan_id, root_path) VALUES (?, ?)",
        (scan_id, root_str),
    )
    scan_session_id = cursor.lastrowid

    print(f"✅ Scan session started: {scan_id} — {root_path}")
    file_paths = [
        os.path.join(dirpath, filename)
        for dirpath, _, filenames in os.walk(root_path)
        for filename in filenames
    ]

    if not parallel:
        for file_path in tqdm(file_paths, desc="📦 Scanning"):
            result = _hash_file_worker(file_path, root_path)
            if result is None:
                continue
            rel_path, size, mtime, sha1, inode, device_id = result
            cursor.execute("""
                INSERT OR REPLACE INTO files (path, size, mtime, sha1, scan_session_id, inode, device_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (rel_path, size, mtime, sha1, scan_session_id, inode, device_id))
        conn.commit()
        print("📦 Scan complete.")
        return

    workers = max(1, workers or (os.cpu_count() or 1))
    max_inflight = workers * 10
    batch_size = batch_size or BATCH_SIZE
    pending = set()
    batch_rows = []
    file_iter = iter(file_paths)
    interrupted = False
    drain_deadline = None
    drain_iters = 0

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Prime the queue
            while len(pending) < max_inflight:
                try:
                    file_path = next(file_iter)
                except StopIteration:
                    break
                pending.add(executor.submit(_hash_file_worker, file_path, root_path))

            with tqdm(total=len(file_paths), desc="📦 Scanning") as pbar:
                while pending:
                    try:
                        done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    except KeyboardInterrupt:
                        interrupted = True
                        drain_deadline = time.monotonic() + 1.0
                        drain_iters = 10
                        print("⚠️ Scan interrupted. Draining completed results...")
                        done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)

                    for fut in done:
                        result = fut.result()
                        if result is not None:
                            batch_rows.append(result)
                            if len(batch_rows) >= batch_size:
                                _write_batch(cursor, scan_session_id, batch_rows)
                                batch_rows.clear()
                        pbar.update(1)

                    # Refill
                    if interrupted:
                        if drain_deadline is None:
                            drain_deadline = time.monotonic() + 1.0
                            drain_iters = 10
                        drain_iters -= 1
                        if time.monotonic() >= drain_deadline or drain_iters <= 0:
                            break
                        continue

                    while len(pending) < max_inflight:
                        try:
                            file_path = next(file_iter)
                        except StopIteration:
                            break
                        pending.add(executor.submit(_hash_file_worker, file_path, root_path))

    except KeyboardInterrupt:
        interrupted = True
    finally:
        if interrupted and pending:
            for fut in list(pending):
                fut.cancel()
        if batch_rows:
            _write_batch(cursor, scan_session_id, batch_rows)
            batch_rows.clear()
        conn.commit()

    print("📦 Scan complete.")
