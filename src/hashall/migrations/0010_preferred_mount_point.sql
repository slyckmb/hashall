-- Migration 0010: Add preferred mount point for canonical path normalization
-- Date: 2026-02-05
-- Description: Store a stable, preferred mount point per filesystem to avoid mount point drift

ALTER TABLE devices ADD COLUMN preferred_mount_point TEXT;

-- Backfill existing devices to prefer their current mount point
UPDATE devices
SET preferred_mount_point = mount_point
WHERE preferred_mount_point IS NULL;

CREATE INDEX IF NOT EXISTS idx_devices_preferred_mount
ON devices(preferred_mount_point);
