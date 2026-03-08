-- Migration 0013: stable files-table binding by fs_uuid
-- Date: 2026-03-06
-- Description:
--   - Adds devices.files_table as the stable physical table binding for each filesystem.
--   - Backfills files_table deterministically from fs_uuid.
--   - Adds a unique index so each filesystem owns exactly one physical files table.

ALTER TABLE devices ADD COLUMN files_table TEXT;

UPDATE devices
SET files_table = (
    'files_fs_' ||
    lower(
        replace(
            replace(
                replace(
                    replace(
                        replace(trim(fs_uuid), '-', '_'),
                    ':', '_'),
                '.', '_'),
            '/', '_'),
        ' ', '_')
    )
)
WHERE files_table IS NULL
  AND fs_uuid IS NOT NULL
  AND trim(fs_uuid) <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_files_table
ON devices(files_table);
