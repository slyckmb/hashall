-- Add inode and device_id columns to support hardlink detection
-- Required for ZFS environments and deduplication workflows

ALTER TABLE files ADD COLUMN inode INTEGER;
ALTER TABLE files ADD COLUMN device_id INTEGER;

-- Create index for fast hardlink lookups
CREATE INDEX IF NOT EXISTS idx_files_inode_device ON files(inode, device_id);
