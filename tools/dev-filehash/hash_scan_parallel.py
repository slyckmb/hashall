#!/usr/bin/env python3

# hash_scan_parallel.py
import os
import time
import hashlib
import sqlite3
from pathlib import Path
from multiprocessing import Process, Queue, cpu_count

def compute_partial_sha1(path):
    try:
        with open(path, 'rb') as f:
            size = os.path.getsize(path)
            if size < 8192:
                return hashlib.sha1(f.read()).hexdigest()

            head = f.read(4096)
            f.seek(size // 2)
            middle = f.read(4096)
            f.seek(-4096, os.SEEK_END)
            tail = f.read(4096)

        return hashlib.sha1(head + middle + tail).hexdigest()
    except Exception:
        return None

def scan_worker(base_dir, q):
    for root, _, files in os.walk(base_dir):
        for fname in files:
            path = os.path.join(root, fname)
            try:
                stat = os.stat(path)
                partial = compute_partial_sha1(path)
                if partial:
                    q.put({
                        'path': path,
                        'size': stat.st_size,
                        'mtime': int(stat.st_mtime),
                        'inode': stat.st_ino,
                        'partial_sha1': partial,
                        'scanned_at': int(time.time())
                    })
            except Exception:
                continue

def db_writer(q, db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    while True:
        item = q.get()
        if item == 'DONE':
            break
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO file_hashes (path, size, mtime, inode, partial_sha1, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                item['path'], item['size'], item['mtime'], item['inode'],
                item['partial_sha1'], item['scanned_at']
            ))
            conn.commit()
        except Exception:
            continue
    conn.close()

def main(base_dirs):
    db_path = str(Path.home() / ".filehash.db")
    q = Queue(maxsize=1000)

    writer = Process(target=db_writer, args=(q, db_path))
    writer.start()

    workers = []
    for base in base_dirs:
        p = Process(target=scan_worker, args=(base, q))
        p.start()
        workers.append(p)

    for w in workers:
        w.join()

    q.put('DONE')
    writer.join()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python hash_scan_parallel.py /path1 [/path2 ...]")
        exit(1)
    main(sys.argv[1:])
