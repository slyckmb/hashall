#!/usr/bin/env python3
"""
db_migration.py – Ensure SQLite schema and perform safe upgrades
"""

import sqlite3
import logging
import shutil
import os
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("hashall.migrate")
logging.basicConfig(level=logging.INFO, format="%(message)s")

def backup_db(db_path):
    """Create a timestamped backup before modifying the schema."""
    if not db_path or not os.path.isfile(db_path):
        return  # Nothing to back up

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    db_path = Path(db_path)
    backup_path = db_path.with_name(f"{db_path.stem}.backup.{timestamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    logger.info(f"💾 Backup created: {backup_path}")

def apply_migrations(conn):
    """Create or alter DB schema safely for current version."""
    cursor = conn.cursor()

    # Create tables if missing
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
    );
    """)
    logger.info("🆕 Created table: scan_session")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id TEXT,
        rel_path TEXT,
        size INTEGER,
        mtime REAL,
        sha1 TEXT
    );
    """)
    logger.info("🆕 Created table: files")

    # Ensure required columns exist (idempotent)
    def add_column_safe(table, column, coltype):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype};")
            logger.info(f"🩹 Added column: {table}.{column}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                pass  # Column already exists
            else:
                raise

    add_column_safe("files", "scan_id", "TEXT")
    add_column_safe("files", "rel_path", "TEXT")
    add_column_safe("files", "sha1", "TEXT")

    conn.commit()
