"""
Tests for device management functionality.
"""

import pytest
import sqlite3
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from hashall.device import (
    ensure_files_table,
    rename_files_table,
    suggest_device_alias,
    register_or_update_device,
    _get_fs_type
)
from hashall.model import connect_db


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)

    # Connect and initialize
    conn = connect_db(db_path)
    cursor = conn.cursor()

    yield cursor

    conn.close()
    db_path.unlink()


def test_ensure_files_table_creates_table(test_db):
    """Test that ensure_files_table creates a new table."""
    cursor = test_db
    device_id = 49

    # Verify table doesn't exist initially
    result = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (f"files_{device_id}",)).fetchone()
    assert result is None

    # Create the table
    table_name = ensure_files_table(cursor, device_id)

    # Verify table was created
    assert table_name == f"files_{device_id}"
    result = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (table_name,)).fetchone()
    assert result is not None
    assert result[0] == table_name


def test_ensure_files_table_has_correct_schema(test_db):
    """Test that the created table has the correct schema."""
    cursor = test_db
    device_id = 50
    table_name = ensure_files_table(cursor, device_id)

    # Get table info
    columns = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    column_dict = {col[1]: col for col in columns}

    # Verify required columns exist
    required_columns = [
        'path', 'size', 'mtime', 'sha1', 'sha256', 'inode',
        'first_seen_at', 'last_seen_at', 'last_modified_at',
        'status', 'discovered_under'
    ]

    for col_name in required_columns:
        assert col_name in column_dict, f"Missing column: {col_name}"

    # Verify path is PRIMARY KEY
    assert column_dict['path'][5] == 1, "path should be PRIMARY KEY"

    # Verify NOT NULL constraints
    assert column_dict['size'][3] == 1, "size should be NOT NULL"
    assert column_dict['mtime'][3] == 1, "mtime should be NOT NULL"
    assert column_dict['sha1'][3] == 0, "sha1 should be nullable"
    assert column_dict['sha256'][3] == 0, "sha256 should be nullable"
    assert column_dict['inode'][3] == 1, "inode should be NOT NULL"

    # Verify default values
    assert column_dict['status'][4] == "'active'", "status should default to 'active'"


def test_ensure_files_table_creates_indexes(test_db):
    """Test that ensure_files_table creates the required indexes."""
    cursor = test_db
    device_id = 51
    table_name = ensure_files_table(cursor, device_id)

    # Get all indexes for the table
    indexes = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='index' AND tbl_name=?
    """, (table_name,)).fetchall()

    index_names = {idx[0] for idx in indexes}

    # Verify required indexes exist
    expected_indexes = {
        f"idx_{table_name}_sha1",
        f"idx_{table_name}_sha256",
        f"idx_{table_name}_inode",
        f"idx_{table_name}_status"
    }

    for expected_idx in expected_indexes:
        assert expected_idx in index_names, f"Missing index: {expected_idx}"


def test_ensure_files_table_is_idempotent(test_db):
    """Test that calling ensure_files_table multiple times doesn't fail."""
    cursor = test_db
    device_id = 52

    # Call the function multiple times
    table_name_1 = ensure_files_table(cursor, device_id)
    table_name_2 = ensure_files_table(cursor, device_id)
    table_name_3 = ensure_files_table(cursor, device_id)

    # All calls should return the same table name
    assert table_name_1 == table_name_2 == table_name_3

    # Verify table still exists and is functional
    result = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (table_name_1,)).fetchone()
    assert result is not None


def test_ensure_files_table_can_insert_data(test_db):
    """Test that we can insert data into the created table."""
    cursor = test_db
    device_id = 53
    table_name = ensure_files_table(cursor, device_id)

    # Insert test data
    cursor.execute(f"""
        INSERT INTO {table_name}
        (path, size, mtime, sha1, inode, discovered_under)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("test/file.txt", 1024, 1234567890.0, "abc123def456", 98765, "/test"))

    # Verify data was inserted
    result = cursor.execute(f"""
        SELECT path, size, mtime, sha1, inode, status, discovered_under
        FROM {table_name}
        WHERE path = ?
    """, ("test/file.txt",)).fetchone()

    assert result is not None
    assert result[0] == "test/file.txt"
    assert result[1] == 1024
    assert result[2] == 1234567890.0
    assert result[3] == "abc123def456"
    assert result[4] == 98765
    assert result[5] == "active"  # Default value
    assert result[6] == "/test"


def test_ensure_files_table_multiple_devices(test_db):
    """Test that we can create tables for multiple devices."""
    cursor = test_db

    # Create tables for different devices
    device_ids = [49, 50, 51]
    table_names = [ensure_files_table(cursor, dev_id) for dev_id in device_ids]

    # Verify all tables were created
    for table_name in table_names:
        result = cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name=?
        """, (table_name,)).fetchone()
        assert result is not None

    # Verify each table is independent
    for i, device_id in enumerate(device_ids):
        table_name = table_names[i]
        cursor.execute(f"""
            INSERT INTO {table_name}
            (path, size, mtime, sha1, inode)
            VALUES (?, ?, ?, ?, ?)
        """, (f"file_{device_id}.txt", 100 * device_id, 1.0, f"sha{device_id}", device_id))

    # Verify data isolation
    for i, device_id in enumerate(device_ids):
        table_name = table_names[i]
        count = cursor.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        assert count == 1, f"Table {table_name} should have exactly 1 row"


def test_ensure_files_table_primary_key_constraint(test_db):
    """Test that the PRIMARY KEY constraint on path is enforced."""
    cursor = test_db
    device_id = 54
    table_name = ensure_files_table(cursor, device_id)

    # Insert first record
    cursor.execute(f"""
        INSERT INTO {table_name}
        (path, size, mtime, sha1, inode)
        VALUES (?, ?, ?, ?, ?)
    """, ("duplicate.txt", 100, 1.0, "sha1", 1000))

    # Try to insert duplicate path - should fail
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(f"""
            INSERT INTO {table_name}
            (path, size, mtime, sha1, inode)
            VALUES (?, ?, ?, ?, ?)
        """, ("duplicate.txt", 200, 2.0, "sha2", 2000))


# Tests for rename_files_table()


def test_rename_files_table_when_old_exists(test_db):
    """Test that table is renamed when old table exists."""
    cursor = test_db
    old_device_id = 100
    new_device_id = 200

    # Create old table
    old_table_name = ensure_files_table(cursor, old_device_id)

    # Add some test data
    cursor.execute(f"""
        INSERT INTO {old_table_name} (path, size, mtime, sha1, inode)
        VALUES ('test/file.txt', 1024, 1234567890.0, 'abc123', 12345)
    """)
    cursor.connection.commit()

    # Rename the table
    rename_files_table(cursor, old_device_id, new_device_id)
    cursor.connection.commit()

    # Verify old table no longer exists
    result = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (f"files_{old_device_id}",)).fetchone()
    assert result is None

    # Verify new table exists
    new_table_name = f"files_{new_device_id}"
    result = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (new_table_name,)).fetchone()
    assert result is not None

    # Verify data was preserved
    result = cursor.execute(f"""
        SELECT path, size, sha1 FROM {new_table_name}
        WHERE path='test/file.txt'
    """).fetchone()
    assert result is not None
    assert result[0] == 'test/file.txt'
    assert result[1] == 1024
    assert result[2] == 'abc123'


def test_rename_files_table_noop_when_old_not_exists(test_db):
    """Test that function is a no-op when old table doesn't exist."""
    cursor = test_db
    old_device_id = 300
    new_device_id = 400

    # Don't create old table, just call rename
    rename_files_table(cursor, old_device_id, new_device_id)
    cursor.connection.commit()

    # Verify neither table exists
    result = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN (?, ?)
    """, (f"files_{old_device_id}", f"files_{new_device_id}")).fetchall()
    assert len(result) == 0


def test_rename_files_table_preserves_indexes(test_db):
    """Test that indexes are preserved when renaming table."""
    cursor = test_db
    old_device_id = 500
    new_device_id = 600

    # Create table with indexes
    ensure_files_table(cursor, old_device_id)
    cursor.connection.commit()

    # Rename the table
    rename_files_table(cursor, old_device_id, new_device_id)
    cursor.connection.commit()

    # Verify indexes exist for new table
    # Note: SQLite ALTER TABLE RENAME only updates the tbl_name in index metadata,
    # but keeps the original index names (idx_files_500_*). This is expected behavior.
    new_table_name = f"files_{new_device_id}"
    indexes = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='index' AND tbl_name=?
        ORDER BY name
    """, (new_table_name,)).fetchall()

    # Should have at least 3 indexes: sha1, inode, status
    # (SQLite may create additional indexes like autoindex for PRIMARY KEY)
    assert len(indexes) >= 3

    # Verify the indexes still reference the old device_id in their names
    # (SQLite doesn't rename index names, only updates tbl_name)
    index_names = [idx[0] for idx in indexes]
    assert f"idx_files_{old_device_id}_inode" in index_names
    assert f"idx_files_{old_device_id}_sha1" in index_names
    assert f"idx_files_{old_device_id}_status" in index_names

    # Most importantly, verify the indexes are functional on the new table
    # Try to use one of the indexes
    cursor.execute(f"""
        SELECT * FROM {new_table_name} WHERE sha1 = 'test'
    """)
    # If indexes weren't working, this would still succeed but be slower


def test_rename_files_table_when_new_already_exists(test_db):
    """Test graceful handling when new table already exists."""
    cursor = test_db
    old_device_id = 700
    new_device_id = 800

    # Create both tables
    old_table_name = ensure_files_table(cursor, old_device_id)
    new_table_name = ensure_files_table(cursor, new_device_id)

    # Add different data to each table
    cursor.execute(f"""
        INSERT INTO {old_table_name} (path, size, mtime, sha1, inode)
        VALUES ('old/file.txt', 100, 1234567890.0, 'old123', 1001)
    """)
    cursor.execute(f"""
        INSERT INTO {new_table_name} (path, size, mtime, sha1, inode)
        VALUES ('new/file.txt', 200, 1234567890.0, 'new456', 2002)
    """)
    cursor.connection.commit()

    # Try to rename - should be no-op since new table exists
    rename_files_table(cursor, old_device_id, new_device_id)
    cursor.connection.commit()

    # Verify both tables still exist
    tables = cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN (?, ?)
        ORDER BY name
    """, (old_table_name, new_table_name)).fetchall()
    assert len(tables) == 2

    # Verify data in old table is unchanged
    result = cursor.execute(f"""
        SELECT path FROM {old_table_name}
    """).fetchone()
    assert result[0] == 'old/file.txt'

    # Verify data in new table is unchanged
    result = cursor.execute(f"""
        SELECT path FROM {new_table_name}
    """).fetchone()
    assert result[0] == 'new/file.txt'


# Tests for _get_fs_type()


def test_get_fs_type_returns_string():
    """Test that _get_fs_type returns a string for valid paths."""
    # Test with root directory (should always exist)
    fs_type = _get_fs_type('/')
    assert isinstance(fs_type, str)
    assert len(fs_type) > 0
    assert fs_type != 'unknown'  # Root should have a known fs type


def test_get_fs_type_handles_invalid_path():
    """Test that _get_fs_type handles invalid paths gracefully."""
    fs_type = _get_fs_type('/this/path/does/not/exist/at/all')
    assert fs_type == 'unknown'


# Tests for register_or_update_device()


@patch('hashall.fs_utils.get_zfs_metadata')
@patch('hashall.device._get_fs_type')
def test_register_new_device(mock_get_fs_type, mock_get_zfs_metadata, test_db):
    """Test registering a brand new device."""
    cursor = test_db
    mock_get_fs_type.return_value = 'zfs'
    mock_get_zfs_metadata.return_value = {
        'pool_name': 'testpool',
        'dataset_name': 'testpool/data',
        'pool_guid': '12345678901234567890'
    }

    # Register new device
    device = register_or_update_device(
        cursor,
        fs_uuid='zfs-12345',
        device_id=49,
        mount_point='/testpool'
    )

    # Verify returned dict
    assert device['device_id'] == 49
    assert device['fs_uuid'] == 'zfs-12345'
    assert device['device_alias'] == 'testpool'
    assert device['mount_point'] == '/testpool'
    assert device['preferred_mount_point'] == '/testpool'
    assert device['fs_type'] == 'zfs'
    assert device['zfs_pool_name'] == 'testpool'
    assert device['zfs_dataset_name'] == 'testpool/data'
    assert device['zfs_pool_guid'] == '12345678901234567890'
    assert device['scan_count'] == 1

    # Verify database record
    db_record = cursor.execute("""
        SELECT fs_uuid, device_id, device_alias, mount_point, preferred_mount_point, fs_type, scan_count
        FROM devices WHERE fs_uuid = ?
    """, ('zfs-12345',)).fetchone()

    assert db_record is not None
    assert db_record[0] == 'zfs-12345'
    assert db_record[1] == 49
    assert db_record[2] == 'testpool'
    assert db_record[3] == '/testpool'
    assert db_record[4] == '/testpool'
    assert db_record[5] == 'zfs'
    assert db_record[6] == 1


@patch('hashall.fs_utils.get_zfs_metadata')
@patch('hashall.device._get_fs_type')
def test_register_device_without_zfs_metadata(mock_get_fs_type, mock_get_zfs_metadata, test_db):
    """Test registering a non-ZFS device."""
    cursor = test_db
    mock_get_fs_type.return_value = 'ext4'
    mock_get_zfs_metadata.return_value = {}  # No ZFS metadata

    device = register_or_update_device(
        cursor,
        fs_uuid='a1b2c3d4-e5f6-7890-abcd-ef1234567890',
        device_id=50,
        mount_point='/mnt/data'
    )

    assert device['device_id'] == 50
    assert device['fs_uuid'] == 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    assert device['fs_type'] == 'ext4'
    assert device['zfs_pool_name'] is None
    assert device['zfs_dataset_name'] is None
    assert device['zfs_pool_guid'] is None


@patch('hashall.fs_utils.get_zfs_metadata')
@patch('hashall.device._get_fs_type')
def test_update_device_same_device_id(mock_get_fs_type, mock_get_zfs_metadata, test_db):
    """Test updating an existing device when device_id hasn't changed."""
    cursor = test_db
    mock_get_fs_type.return_value = 'zfs'
    mock_get_zfs_metadata.return_value = {}

    # Register device first time
    device1 = register_or_update_device(
        cursor,
        fs_uuid='zfs-99999',
        device_id=51,
        mount_point='/pool'
    )
    assert device1['scan_count'] == 1

    # Update device (same device_id)
    device2 = register_or_update_device(
        cursor,
        fs_uuid='zfs-99999',
        device_id=51,
        mount_point='/pool'
    )

    # Verify scan_count incremented
    assert device2['scan_count'] == 2
    assert device2['device_id'] == 51
    assert device2['fs_uuid'] == 'zfs-99999'

    # Verify only one record in database
    count = cursor.execute("""
        SELECT COUNT(*) FROM devices WHERE fs_uuid = ?
    """, ('zfs-99999',)).fetchone()[0]
    assert count == 1


@patch('hashall.fs_utils.get_zfs_metadata')
@patch('hashall.device._get_fs_type')
def test_update_device_changed_device_id(mock_get_fs_type, mock_get_zfs_metadata, test_db, capsys):
    """Test handling device_id change (e.g., after reboot)."""
    cursor = test_db
    mock_get_fs_type.return_value = 'zfs'
    mock_get_zfs_metadata.return_value = {}

    # Register device with device_id=52
    device1 = register_or_update_device(
        cursor,
        fs_uuid='zfs-88888',
        device_id=52,
        mount_point='/stash'
    )
    assert device1['device_id'] == 52

    # Create files table for old device_id
    ensure_files_table(cursor, 52)
    cursor.execute(f"""
        INSERT INTO files_52 (path, size, mtime, sha1, inode)
        VALUES ('test.txt', 100, 1234567890.0, 'abcdef', 9999)
    """)
    cursor.connection.commit()

    # Update with new device_id (simulating reboot)
    device2 = register_or_update_device(
        cursor,
        fs_uuid='zfs-88888',
        device_id=53,
        mount_point='/stash'
    )

    # Verify device_id updated
    assert device2['device_id'] == 53
    assert device2['fs_uuid'] == 'zfs-88888'

    # Verify warning was printed
    captured = capsys.readouterr()
    assert 'Device ID changed' in captured.out
    assert '52' in captured.out
    assert '53' in captured.out

    # Verify device_id_history was updated
    history_json = cursor.execute("""
        SELECT device_id_history FROM devices WHERE fs_uuid = ?
    """, ('zfs-88888',)).fetchone()[0]

    history = json.loads(history_json)
    assert len(history) == 1
    assert history[0]['device_id'] == 52
    assert 'changed_at' in history[0]

    # Verify files table was renamed
    old_table_exists = cursor.execute("""
        SELECT name FROM sqlite_master WHERE type='table' AND name='files_52'
    """).fetchone()
    assert old_table_exists is None

    new_table_exists = cursor.execute("""
        SELECT name FROM sqlite_master WHERE type='table' AND name='files_53'
    """).fetchone()
    assert new_table_exists is not None

    # Verify data was preserved in renamed table
    data = cursor.execute("""
        SELECT path, size FROM files_53 WHERE path='test.txt'
    """).fetchone()
    assert data is not None
    assert data[0] == 'test.txt'
    assert data[1] == 100


@patch('hashall.fs_utils.get_zfs_metadata')
@patch('hashall.device._get_fs_type')
def test_register_device_with_explicit_fs_type(mock_get_fs_type, mock_get_zfs_metadata, test_db):
    """Test that explicit fs_type in kwargs is used."""
    cursor = test_db
    mock_get_zfs_metadata.return_value = {}

    # Pass fs_type explicitly - should not call _get_fs_type
    device = register_or_update_device(
        cursor,
        fs_uuid='dev-123',
        device_id=54,
        mount_point='/custom',
        fs_type='btrfs'
    )

    assert device['fs_type'] == 'btrfs'
    # Verify _get_fs_type was not called
    mock_get_fs_type.assert_not_called()


@patch('hashall.fs_utils.get_zfs_metadata')
@patch('hashall.device._get_fs_type')
def test_register_device_generates_unique_alias(mock_get_fs_type, mock_get_zfs_metadata, test_db):
    """Test that alias collision is handled with numeric suffix."""
    cursor = test_db
    mock_get_fs_type.return_value = 'zfs'
    mock_get_zfs_metadata.return_value = {}

    # Register first device at /pool
    device1 = register_or_update_device(
        cursor,
        fs_uuid='zfs-11111',
        device_id=55,
        mount_point='/pool'
    )
    assert device1['device_alias'] == 'pool'

    # Register second device also at /pool (different fs_uuid)
    device2 = register_or_update_device(
        cursor,
        fs_uuid='zfs-22222',
        device_id=56,
        mount_point='/pool'
    )
    assert device2['device_alias'] == 'pool2'  # Should get numeric suffix

    # Register third device
    device3 = register_or_update_device(
        cursor,
        fs_uuid='zfs-33333',
        device_id=57,
        mount_point='/pool'
    )
    assert device3['device_alias'] == 'pool3'


@patch('hashall.fs_utils.get_zfs_metadata')
@patch('hashall.device._get_fs_type')
def test_device_id_history_tracks_multiple_changes(mock_get_fs_type, mock_get_zfs_metadata, test_db):
    """Test that device_id_history correctly tracks multiple changes."""
    cursor = test_db
    mock_get_fs_type.return_value = 'zfs'
    mock_get_zfs_metadata.return_value = {}

    # Initial registration
    register_or_update_device(cursor, 'zfs-history-test', 60, '/test')

    # First change
    register_or_update_device(cursor, 'zfs-history-test', 61, '/test')

    # Second change
    register_or_update_device(cursor, 'zfs-history-test', 62, '/test')

    # Verify history has two entries
    history_json = cursor.execute("""
        SELECT device_id_history FROM devices WHERE fs_uuid = ?
    """, ('zfs-history-test',)).fetchone()[0]

    history = json.loads(history_json)
    assert len(history) == 2
    assert history[0]['device_id'] == 60
    assert history[1]['device_id'] == 61
    assert 'changed_at' in history[0]
    assert 'changed_at' in history[1]

    # Verify current device_id is 62
    current_device_id = cursor.execute("""
        SELECT device_id FROM devices WHERE fs_uuid = ?
    """, ('zfs-history-test',)).fetchone()[0]
    assert current_device_id == 62


@patch('hashall.fs_utils.get_zfs_metadata')
@patch('hashall.device._get_fs_type')
def test_update_device_updates_mount_point(mock_get_fs_type, mock_get_zfs_metadata, test_db):
    """Test that mount_point is updated on subsequent scans."""
    cursor = test_db
    mock_get_fs_type.return_value = 'zfs'
    mock_get_zfs_metadata.return_value = {}

    # Initial registration
    device1 = register_or_update_device(cursor, 'zfs-mount-test', 70, '/old/mount')
    assert device1['mount_point'] == '/old/mount'
    assert device1['preferred_mount_point'] == '/old/mount'

    # Update with new mount point (same device_id)
    device2 = register_or_update_device(cursor, 'zfs-mount-test', 70, '/new/mount')
    assert device2['mount_point'] == '/new/mount'
    assert device2['preferred_mount_point'] == '/old/mount'

    # Verify in database
    mount_point, preferred_mount_point = cursor.execute("""
        SELECT mount_point, preferred_mount_point FROM devices WHERE fs_uuid = ?
    """, ('zfs-mount-test',)).fetchone()
    assert mount_point == '/new/mount'
    assert preferred_mount_point == '/old/mount'
