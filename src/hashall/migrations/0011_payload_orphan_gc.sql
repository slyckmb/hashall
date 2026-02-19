-- Migration 0011: Track staged orphan payload cleanup state
-- Date: 2026-02-11
-- Description: Two-phase orphan GC markers to avoid unsafe bulk prune behavior

CREATE TABLE IF NOT EXISTS payload_orphan_gc (
    payload_id INTEGER PRIMARY KEY,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    last_root_path TEXT,
    last_device_id INTEGER,
    FOREIGN KEY (payload_id) REFERENCES payloads(payload_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_payload_orphan_gc_last_seen
ON payload_orphan_gc(last_seen_at);

