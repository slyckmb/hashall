#!/usr/bin/env python3
"""
hashall json_export.py – Export verified hash data to .hashall/hashall.json
"""

import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime
import getpass
import socket
import logging
import sys

logger = logging.getLogger("hashall.export")
logging.basicConfig(level=logging.INFO, format="%(message)s")

def export_json(root_path, db_path):
    abs_root = Path(root_path).resolve()
    export_dir = abs_root / ".hashall"
    export_file = export_dir / "hashall.json"

    export_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get latest scan session for this root
    cursor.execute("""
        SELECT scan_id, start_time, end_time, mode, workers, host, user
        FROM scan_session
        WHERE root_path = ?
        ORDER BY start_time DESC
        LIMIT 1
    """, (str(abs_root),))
    row = cursor.fetchone()
    if not row:
        logger.error(f"No scan session found for root: {abs_root}")
        return

    scan_id, start_time, end_time, mode, workers, host, user = row

    # Query all files for this scan_id
    cursor.execute("""
        SELECT rel_path, size, mtime, sha1
        FROM files
        WHERE scan_id = ?
    """, (scan_id,))
    files = []
    missing_sha1 = 0
    for rel_path, size, mtime, sha1 in cursor.fetchall():
        if not sha1:
            logger.warning(f"Skipping file with missing SHA1: {rel_path}")
            missing_sha1 += 1
            continue
        files.append({
            "rel_path": rel_path,
            "size": size,
            "mtime": mtime,
            "sha1": sha1
        })

    logger.info(f"Exporting {len(files)} files to {export_file}")
    if missing_sha1 > 0:
        print(f"⚠️  Skipped {missing_sha1} files missing SHA1 values.", file=sys.stderr)

    data = {
        "meta": {
            "version": "0.3.8-dev",
            "scan_id": scan_id,
            "scan_root": str(abs_root),
            "start_time": start_time,
            "end_time": end_time or datetime.utcnow().isoformat(),
            "mode": mode,
            "workers": workers,
            "host": host or socket.gethostname(),
            "user": user or getpass.getuser()
        },
        "files": files
    }

    with export_file.open("w") as f:
        json.dump(data, f, indent=2)

    logger.info("Export complete.")
