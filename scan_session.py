#!/usr/bin/env python3
"""
scan_session.py – Scans files and records results in a SQLite DB.
"""

import os
import uuid
import time
import socket
import getpass
import threading
from pathlib import Path
from queue import Queue
from datetime import datetime
from hashlib import sha1
import sqlite3
import logging

logger = logging.getLogger("hashall.scan")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Global lock for DB access
db_lock = threading.Lock()

def hash_file(path, mode="full"):
    h = sha1()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.warning(f"Could not hash {path}: {e}")
        return None

def db_writer(conn, file_queue, scan_id):
    cursor = conn.cursor()
    while True:
        item = file_queue.get()
        if item is None:
            break
        rel_path, full_path = item
        try:
            stat = os.stat(full_path)
            size = stat.st_size
            mtime = stat.st_mtime
            sha1_hash = hash_file(full_path, mode="full")
            if sha1_hash is None:
                logger.warning(f"Skipping: {rel_path} (hashing failed)")
                file_queue.task_done()
                continue

            with db_lock:
                cursor.execute("""
                    INSERT INTO files (scan_id, rel_path, size, mtime, sha1)
                    VALUES (?, ?, ?, ?, ?)
                """, (scan_id, rel_path, size, mtime, sha1_hash))
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to process {full_path}: {e}")
        file_queue.task_done()

def scan_files(root_path, db_path, mode="verify", workers=4):
    abs_root = Path(root_path).resolve()
    scan_id = str(uuid.uuid4())
    start_time = datetime.utcnow().isoformat()

    # Create connection with thread safety
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()

    # Create tables if needed
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scan_session (
            scan_id TEXT PRIMARY KEY,
            root_path TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            mode TEXT NOT NULL,
            workers INTEGER,
            host TEXT,
            user TEXT
        )
    """)
    logger.info("🆕 Created table: scan_session")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            scan_id TEXT,
            rel_path TEXT,
            size INTEGER,
            mtime REAL,
            sha1 TEXT
        )
    """)
    logger.info("🆕 Created table: files")

    # Add scan session record
    cursor.execute("""
        INSERT INTO scan_session (scan_id, root_path, start_time, mode, workers, host, user)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        scan_id,
        str(abs_root),
        start_time,
        mode,
        workers,
        socket.gethostname(),
        getpass.getuser()
    ))
    conn.commit()

    logger.info(f"📁 Scanning: {abs_root}")
    logger.info(f"🧠 DB: {db_path}")

    file_queue = Queue()
    threads = []

    for _ in range(workers):
        t = threading.Thread(target=db_writer, args=(conn, file_queue, scan_id))
        t.start()
        threads.append(t)

    for dirpath, _, filenames in os.walk(abs_root):
        for name in filenames:
            full_path = os.path.join(dirpath, name)
            rel_path = os.path.relpath(full_path, abs_root)
            file_queue.put((rel_path, full_path))

    file_queue.join()

    for _ in threads:
        file_queue.put(None)
    for t in threads:
        t.join()

    end_time = datetime.utcnow().isoformat()
    cursor.execute("""
        UPDATE scan_session SET end_time = ? WHERE scan_id = ?
    """, (end_time, scan_id))
    conn.commit()
    conn.close()

    logger.info(f"✅ Scan complete: {scan_id}")
