"""
Tests for hashall devices CLI commands.
"""

import unittest
import tempfile
import sqlite3
from pathlib import Path
from click.testing import CliRunner
from hashall.cli import cli


class TestDevicesCLI(unittest.TestCase):
    """Test cases for 'hashall devices' command group."""

    def setUp(self):
        """Create a temporary database for testing."""
        self.temp_db = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.sqlite3')
        self.temp_db.close()
        self.db_path = Path(self.temp_db.name)

        # Initialize database with schema
        from hashall.model import connect_db
        self.conn = connect_db(self.db_path)

    def tearDown(self):
        """Clean up temporary database."""
        self.conn.close()
        self.db_path.unlink()

    def test_devices_list_command_exists(self):
        """Test that 'devices list' command exists and runs."""
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'list', '--db', str(self.db_path)])

        # Command should run successfully
        self.assertEqual(result.exit_code, 0)

    def test_devices_list_empty_database(self):
        """Test 'devices list' with no devices registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'list', '--db', str(self.db_path)])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("No devices registered", result.output)

    def test_devices_list_with_data(self):
        """Test 'devices list' with populated database."""
        # Insert test device data
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                total_files, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            49,
            "pool",
            "/pool",
            "zfs",
            12345,
            1234567890123  # ~1.1 TB
        ))

        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                total_files, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "b2c3d4e5-f6a7-8901-bcde-f12345678901",
            51,
            "stash",
            "/stash",
            "zfs",
            45678,
            3456789012345  # ~3.1 TB
        ))
        self.conn.commit()

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'list', '--db', str(self.db_path)])

        # Check output
        self.assertEqual(result.exit_code, 0)
        self.assertIn("pool", result.output)
        self.assertIn("stash", result.output)
        self.assertIn("a1b2c3d4", result.output)  # UUID first 8 chars
        self.assertIn("b2c3d4e5", result.output)
        self.assertIn("49", result.output)  # device_id
        self.assertIn("51", result.output)
        self.assertIn("/pool", result.output)
        self.assertIn("/stash", result.output)
        self.assertIn("zfs", result.output)
        self.assertIn("12,345", result.output)  # formatted file count
        self.assertIn("45,678", result.output)
        # Size formatting (should show TB)
        self.assertIn("TB", result.output)

    def test_devices_list_formatting(self):
        """Test that output is properly formatted as a table."""
        # Insert test device
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                total_files, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "test-uuid-1234",
            100,
            "test",
            "/mnt/test",
            "ext4",
            1000,
            50000000000  # ~50 GB
        ))
        self.conn.commit()

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'list', '--db', str(self.db_path)])

        # Check that headers are present
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Alias", result.output)
        self.assertIn("UUID (first 8)", result.output)
        self.assertIn("Device ID", result.output)
        self.assertIn("Mount Point", result.output)
        self.assertIn("Type", result.output)
        self.assertIn("Files", result.output)
        self.assertIn("Size", result.output)

        # Check data formatting
        self.assertIn("test", result.output)
        self.assertIn("test-uui", result.output)  # First 8 chars
        self.assertIn("1,000", result.output)  # Comma-separated count
        self.assertIn("46.6 GB", result.output)  # Human-readable size

    def test_devices_list_null_fields(self):
        """Test handling of NULL fields in devices table."""
        # Insert device with some NULL fields
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, mount_point
            ) VALUES (?, ?, ?)
        """, (
            "minimal-uuid",
            200,
            "/minimal"
        ))
        self.conn.commit()

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'list', '--db', str(self.db_path)])

        # Should handle NULLs gracefully
        self.assertEqual(result.exit_code, 0)
        self.assertIn("minimal-", result.output)  # UUID first 8 chars
        self.assertIn("200", result.output)  # device_id
        self.assertIn("/minimal", result.output)

    def test_devices_alias_by_existing_alias(self):
        """Test updating alias using current alias name."""
        # Insert test device
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point
            ) VALUES (?, ?, ?, ?)
        """, (
            "test-uuid-1",
            49,
            "pool",
            "/pool"
        ))
        self.conn.commit()

        # Update alias: pool -> main_pool
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'alias', 'pool', 'main_pool', '--db', str(self.db_path)])

        # Check success
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Updated alias: pool -> main_pool", result.output)

        # Verify in database
        cursor.execute("SELECT device_alias FROM devices WHERE fs_uuid = ?", ("test-uuid-1",))
        new_alias = cursor.fetchone()[0]
        self.assertEqual(new_alias, "main_pool")

    def test_devices_alias_by_device_id(self):
        """Test updating alias using device_id."""
        # Insert test device without initial alias
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, mount_point
            ) VALUES (?, ?, ?)
        """, (
            "test-uuid-2",
            50,
            "/stash"
        ))
        self.conn.commit()

        # Update alias: 50 -> stash
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'alias', '50', 'stash', '--db', str(self.db_path)])

        # Check success
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Updated alias: 50 -> stash", result.output)

        # Verify in database
        cursor.execute("SELECT device_alias FROM devices WHERE fs_uuid = ?", ("test-uuid-2",))
        new_alias = cursor.fetchone()[0]
        self.assertEqual(new_alias, "stash")

    def test_devices_alias_not_found(self):
        """Test error when device is not found."""
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'alias', 'nonexistent', 'new_name', '--db', str(self.db_path)])

        # Should fail gracefully
        self.assertEqual(result.exit_code, 0)  # Click commands return 0 even on logical errors
        self.assertIn("Device 'nonexistent' not found", result.output)

    def test_devices_alias_already_taken(self):
        """Test error when new alias is already in use."""
        # Insert two test devices
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point
            ) VALUES (?, ?, ?, ?)
        """, (
            "test-uuid-3",
            51,
            "pool",
            "/pool"
        ))
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point
            ) VALUES (?, ?, ?, ?)
        """, (
            "test-uuid-4",
            52,
            "stash",
            "/stash"
        ))
        self.conn.commit()

        # Try to rename pool -> stash (already taken)
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'alias', 'pool', 'stash', '--db', str(self.db_path)])

        # Should fail with appropriate error
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Alias 'stash' already taken by device 52", result.output)

        # Verify database unchanged
        cursor.execute("SELECT device_alias FROM devices WHERE fs_uuid = ?", ("test-uuid-3",))
        alias = cursor.fetchone()[0]
        self.assertEqual(alias, "pool")  # Should still be "pool"

    def test_devices_alias_updates_timestamp(self):
        """Test that updated_at timestamp is updated."""
        # Insert test device
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, updated_at
            ) VALUES (?, ?, ?, ?, datetime('2020-01-01'))
        """, (
            "test-uuid-5",
            53,
            "old_alias",
            "/test"
        ))
        self.conn.commit()

        # Get initial timestamp
        cursor.execute("SELECT updated_at FROM devices WHERE fs_uuid = ?", ("test-uuid-5",))
        old_timestamp = cursor.fetchone()[0]

        # Update alias
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'alias', 'old_alias', 'new_alias', '--db', str(self.db_path)])

        # Check success
        self.assertEqual(result.exit_code, 0)

        # Verify timestamp was updated
        cursor.execute("SELECT updated_at FROM devices WHERE fs_uuid = ?", ("test-uuid-5",))
        new_timestamp = cursor.fetchone()[0]
        self.assertNotEqual(old_timestamp, new_timestamp)

    def test_devices_show_by_alias(self):
        """Test 'devices show' command with device alias."""
        # Insert test device
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                zfs_pool_name, zfs_dataset_name, zfs_pool_guid,
                first_scanned_at, last_scanned_at, scan_count,
                total_files, total_bytes, device_id_history
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            49,
            "pool",
            "/pool",
            "zfs",
            "pool",
            "pool/torrents",
            "12345678901234567890",
            "2026-01-15 10:30:00",
            "2026-01-31 14:22:15",
            47,
            12345,
            1200000000000,  # ~1.2 TB
            '[]'
        ))
        self.conn.commit()

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'show', 'pool', '--db', str(self.db_path)])

        # Check output
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Device: pool", result.output)
        self.assertIn("a1b2c3d4-e5f6-7890-abcd-ef1234567890", result.output)
        self.assertIn("Current Device ID: 49", result.output)
        self.assertIn("Mount Point: /pool", result.output)
        self.assertIn("Filesystem Type: zfs", result.output)
        self.assertIn("ZFS Metadata:", result.output)
        self.assertIn("Pool Name: pool", result.output)
        self.assertIn("Dataset Name: pool/torrents", result.output)
        self.assertIn("Pool GUID: 12345678901234567890", result.output)
        self.assertIn("Statistics:", result.output)
        self.assertIn("12,345 active", result.output)
        self.assertIn("First Scanned: 2026-01-15 10:30:00", result.output)
        self.assertIn("Last Scanned: 2026-01-31 14:22:15", result.output)
        self.assertIn("Scan Count: 47", result.output)
        self.assertIn("1.2 TB", result.output)

    def test_devices_show_by_device_id(self):
        """Test 'devices show' command with device_id."""
        # Insert test device
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                total_files, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "b2c3d4e5-f6a7-8901-bcde-f12345678901",
            51,
            "stash",
            "/stash",
            "ext4",
            5000,
            500000000  # 500 MB
        ))
        self.conn.commit()

        # Run command with device_id
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'show', '51', '--db', str(self.db_path)])

        # Check output
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Device: stash", result.output)
        self.assertIn("b2c3d4e5-f6a7-8901-bcde-f12345678901", result.output)
        self.assertIn("Current Device ID: 51", result.output)
        self.assertIn("Mount Point: /stash", result.output)
        self.assertIn("Filesystem Type: ext4", result.output)
        self.assertIn("5,000 active", result.output)
        self.assertIn("500.0 MB", result.output)

    def test_devices_show_not_found(self):
        """Test 'devices show' with non-existent device."""
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'show', 'nonexistent', '--db', str(self.db_path)])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Device not found: nonexistent", result.output)

    def test_devices_show_with_history(self):
        """Test 'devices show' displays device ID history."""
        import json

        # Insert test device with history
        cursor = self.conn.cursor()
        history = [
            {'device_id': 48, 'changed_at': '2026-01-15T10:30:00'},
            {'device_id': 49, 'changed_at': '2026-01-20T08:15:00'}
        ]
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                last_scanned_at, device_id_history
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "test-uuid-with-history",
            50,
            "test-dev",
            "/test",
            "zfs",
            "2026-01-25 12:00:00",
            json.dumps(history)
        ))
        self.conn.commit()

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'show', 'test-dev', '--db', str(self.db_path)])

        # Check output includes history
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Device ID History:", result.output)
        self.assertIn("2026-01-15: device_id 48", result.output)
        self.assertIn("2026-01-20: device_id 49", result.output)
        self.assertIn("2026-01-25: device_id 50", result.output)

    def test_devices_show_non_zfs(self):
        """Test 'devices show' does not display ZFS section for non-ZFS devices."""
        # Insert test device without ZFS metadata
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                total_files, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "ext4-uuid",
            100,
            "ext4-dev",
            "/mnt/ext4",
            "ext4",
            100,
            1000000
        ))
        self.conn.commit()

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ['devices', 'show', 'ext4-dev', '--db', str(self.db_path)])

        # Check output does NOT include ZFS metadata
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Device: ext4-dev", result.output)
        self.assertIn("Filesystem Type: ext4", result.output)
        self.assertNotIn("ZFS Metadata:", result.output)

    def test_stats_command_empty_database(self):
        """Test 'stats' command with no devices."""
        runner = CliRunner()
        result = runner.invoke(cli, ['stats', '--db', str(self.db_path)])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Hashall Catalog Statistics", result.output)
        self.assertIn("Database:", result.output)
        self.assertIn("Database Size:", result.output)
        self.assertIn("Devices: 0", result.output)
        self.assertIn("(No devices scanned yet)", result.output)
        self.assertIn("Scan History:", result.output)
        self.assertIn("(No completed scans yet)", result.output)

    def test_stats_command_with_devices(self):
        """Test 'stats' command with populated database."""
        # Insert test devices
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                total_files, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "uuid-pool",
            49,
            "pool",
            "/pool",
            "zfs",
            12345,
            1200000000000  # ~1.2 TB
        ))

        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, fs_type,
                total_files, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "uuid-stash",
            51,
            "stash",
            "/stash",
            "zfs",
            45678,
            3400000000000  # ~3.4 TB
        ))
        self.conn.commit()

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ['stats', '--db', str(self.db_path)])

        # Check output
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Hashall Catalog Statistics", result.output)
        self.assertIn("Devices: 2", result.output)
        self.assertIn("pool", result.output)
        self.assertIn("stash", result.output)
        self.assertIn("(49)", result.output)
        self.assertIn("(51)", result.output)
        self.assertIn("12,345 files", result.output)
        self.assertIn("45,678 files", result.output)
        self.assertIn("Total Files:", result.output)
        self.assertIn("58,023 active", result.output)
        self.assertIn("Total Size:", result.output)
        self.assertIn("TB", result.output)

    def test_stats_command_with_scan_history(self):
        """Test 'stats' command displays scan history."""
        # Insert test device
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO devices (
                fs_uuid, device_id, device_alias, mount_point, total_files, total_bytes
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "uuid-test",
            50,
            "pool",
            "/pool",
            1000,
            10000000
        ))

        # Insert scan session
        cursor.execute("""
            INSERT INTO scan_sessions (
                scan_id, fs_uuid, device_id, root_path, status,
                completed_at, files_scanned
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "scan-123",
            "uuid-test",
            50,
            "/pool",
            "completed",
            "2026-01-31 14:22:15",
            1000
        ))
        self.conn.commit()

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ['stats', '--db', str(self.db_path)])

        # Check output
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Scan History:", result.output)
        self.assertIn("Last Scan: 2026-01-31 14:22:15", result.output)
        self.assertIn("(pool)", result.output)
        self.assertIn("Total Scans: 1", result.output)

    def test_stats_command_nonexistent_database(self):
        """Test 'stats' command with nonexistent database."""
        runner = CliRunner()
        result = runner.invoke(cli, ['stats', '--db', '/tmp/nonexistent-hashall-db.sqlite3'])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Database not found:", result.output)
        self.assertIn("Run 'hashall scan <path>' to create a catalog", result.output)


if __name__ == "__main__":
    unittest.main()
