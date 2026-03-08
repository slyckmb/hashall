-- Migration 0012: Add first-class fs_uuid identity to payload/torrent records
-- Date: 2026-03-06
-- Description:
--   - Adds fs_uuid columns to payloads and torrent_instances.
--   - Backfills fs_uuid from devices(device_id) and payload/torrent linkage.
--   - Adds indexes for fs_uuid-scoped lookups.

ALTER TABLE payloads ADD COLUMN fs_uuid TEXT;
ALTER TABLE torrent_instances ADD COLUMN fs_uuid TEXT;

CREATE INDEX IF NOT EXISTS idx_payloads_fs_uuid ON payloads(fs_uuid);
CREATE INDEX IF NOT EXISTS idx_payloads_fs_uuid_root ON payloads(fs_uuid, root_path);
CREATE INDEX IF NOT EXISTS idx_torrent_instances_fs_uuid ON torrent_instances(fs_uuid);

-- Backfill payload fs_uuid from current device mapping.
UPDATE payloads
SET fs_uuid = (
    SELECT d.fs_uuid
    FROM devices d
    WHERE d.device_id = payloads.device_id
)
WHERE (payloads.fs_uuid IS NULL OR payloads.fs_uuid = '')
  AND payloads.device_id IS NOT NULL;

-- Backfill torrent fs_uuid from current device mapping.
UPDATE torrent_instances
SET fs_uuid = (
    SELECT d.fs_uuid
    FROM devices d
    WHERE d.device_id = torrent_instances.device_id
)
WHERE (torrent_instances.fs_uuid IS NULL OR torrent_instances.fs_uuid = '')
  AND torrent_instances.device_id IS NOT NULL;

-- Fill remaining torrent fs_uuid via payload linkage.
UPDATE torrent_instances
SET fs_uuid = (
    SELECT p.fs_uuid
    FROM payloads p
    WHERE p.payload_id = torrent_instances.payload_id
      AND p.fs_uuid IS NOT NULL
    LIMIT 1
)
WHERE (torrent_instances.fs_uuid IS NULL OR torrent_instances.fs_uuid = '')
  AND torrent_instances.payload_id IS NOT NULL;

-- Fill remaining payload fs_uuid via torrent linkage.
UPDATE payloads
SET fs_uuid = (
    SELECT ti.fs_uuid
    FROM torrent_instances ti
    WHERE ti.payload_id = payloads.payload_id
      AND ti.fs_uuid IS NOT NULL
    LIMIT 1
)
WHERE (payloads.fs_uuid IS NULL OR payloads.fs_uuid = '');
