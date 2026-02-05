-- Migration 0009: SHA256 support for per-device file tables
-- Date: 2026-02-05
--
-- Per-device tables (files_{device_id}) are created and migrated dynamically
-- in application code via ensure_files_table(). This migration is a no-op
-- for static schema and exists to record the version bump.

SELECT 1;
