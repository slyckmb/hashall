"""Tests for filesystem UUID detection utilities."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hashall.fs_utils import (
    get_filesystem_uuid,
    get_mount_point,
    get_mount_source,
    get_zfs_metadata,
    _try_findmnt,
    _try_zfs_guid,
)


class TestGetFilesystemUuid:
    """Test suite for get_filesystem_uuid() function."""

    def test_findmnt_success(self):
        """Test successful UUID detection via findmnt."""
        test_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        with patch('subprocess.run') as mock_run:
            # Mock successful findmnt call
            mock_run.return_value = MagicMock(
                stdout=f"{test_uuid}\n",
                returncode=0
            )

            result = get_filesystem_uuid("/some/path")
            assert result == test_uuid

            # Verify findmnt was called with correct arguments
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert Path(args[0]).name == 'findmnt'
            assert '-no' in args
            assert 'UUID' in args
            assert '/some/path' in args

    def test_zfs_guid_success(self):
        """Test successful GUID detection for ZFS filesystem."""
        test_guid = "12345678901234567890"

        with patch('subprocess.run') as mock_run:
            # First call (findmnt) fails
            # Second call (zfs) succeeds
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, 'findmnt'),
                MagicMock(stdout=f"{test_guid}\n", returncode=0)
            ]

            result = get_filesystem_uuid("/pool/torrents")
            assert result == f"zfs-{test_guid}"

            # Verify both commands were attempted
            assert mock_run.call_count == 2

    def test_device_id_fallback(self):
        """Test fallback to device_id when both findmnt and zfs fail."""
        with patch('subprocess.run') as mock_run:
            # Both findmnt and zfs fail
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, 'findmnt'),
                subprocess.CalledProcessError(1, 'zfs')
            ]

            # Use a real path that we know exists
            with tempfile.TemporaryDirectory() as tmpdir:
                result = get_filesystem_uuid(tmpdir)

                # Should return dev-{device_id} format
                assert result.startswith("dev-")
                device_id = result[4:]  # Remove "dev-" prefix
                assert device_id.isdigit()

                # Verify the device_id matches actual st_dev
                actual_device_id = os.stat(tmpdir).st_dev
                assert result == f"dev-{actual_device_id}"

    def test_findmnt_empty_response(self):
        """Test handling of findmnt returning empty UUID (e.g., tmpfs)."""
        with patch('subprocess.run') as mock_run:
            # findmnt returns empty string (filesystem has no UUID)
            # zfs also fails
            mock_run.side_effect = [
                MagicMock(stdout="\n", returncode=0),
                subprocess.CalledProcessError(1, 'zfs')
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                result = get_filesystem_uuid(tmpdir)
                assert result.startswith("dev-")

    def test_findmnt_dash_response(self):
        """Test handling of findmnt returning '-' (no UUID available)."""
        with patch('subprocess.run') as mock_run:
            # findmnt returns '-' (common for filesystems without UUIDs)
            # zfs also fails
            mock_run.side_effect = [
                MagicMock(stdout="-\n", returncode=0),
                subprocess.CalledProcessError(1, 'zfs')
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                result = get_filesystem_uuid(tmpdir)
                assert result.startswith("dev-")

    def test_nonexistent_path(self):
        """Test handling of nonexistent path."""
        nonexistent = "/path/that/does/not/exist/at/all"

        with patch('subprocess.run') as mock_run:
            # subprocess calls fail
            mock_run.side_effect = subprocess.CalledProcessError(1, 'cmd')

            result = get_filesystem_uuid(nonexistent)
            # Should fallback to dev-unknown when stat fails
            assert result == "dev-unknown"

    def test_command_timeout(self):
        """Test handling of command timeout."""
        with patch('subprocess.run') as mock_run:
            # First call times out
            # Second call also times out
            mock_run.side_effect = [
                subprocess.TimeoutExpired('findmnt', 5),
                subprocess.TimeoutExpired('zfs', 5)
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                result = get_filesystem_uuid(tmpdir)
                # Should fallback to device_id
                assert result.startswith("dev-")

    def test_findmnt_not_installed(self):
        """Test handling when findmnt command is not available."""
        with patch('subprocess.run') as mock_run:
            # findmnt not found
            # zfs also not found
            mock_run.side_effect = [
                FileNotFoundError(),
                FileNotFoundError()
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                result = get_filesystem_uuid(tmpdir)
                assert result.startswith("dev-")

    def test_real_filesystem(self):
        """Test with real filesystem (integration test)."""
        # Use /tmp which should always exist
        result = get_filesystem_uuid("/tmp")

        # Should return some valid identifier
        assert isinstance(result, str)
        assert len(result) > 0

        # Should be one of the three formats
        assert (
            # UUID format (with dashes)
            ("-" in result and len(result) == 36) or
            # ZFS GUID format
            result.startswith("zfs-") or
            # Device ID fallback
            result.startswith("dev-")
        )


class TestTryFindmnt:
    """Test suite for _try_findmnt() helper function."""

    def test_success(self):
        """Test successful findmnt execution."""
        test_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout=f"{test_uuid}\n",
                returncode=0
            )

            result = _try_findmnt("/some/path")
            assert result == test_uuid

    def test_returns_none_on_failure(self):
        """Test that function returns None on command failure."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, 'findmnt')

            result = _try_findmnt("/some/path")
            assert result is None

    def test_returns_none_on_empty_output(self):
        """Test that function returns None when UUID is empty."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="\n", returncode=0)

            result = _try_findmnt("/some/path")
            assert result is None

    def test_returns_none_on_dash_output(self):
        """Test that function returns None when UUID is '-'."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="-\n", returncode=0)

            result = _try_findmnt("/some/path")
            assert result is None

    def test_timeout_handling(self):
        """Test handling of command timeout."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired('findmnt', 5)

            result = _try_findmnt("/some/path")
            assert result is None

    def test_timeout_parameter(self):
        """Test that timeout is set on subprocess call."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="uuid\n", returncode=0)

            _try_findmnt("/some/path")

            # Verify timeout was specified
            mock_run.assert_called_once()
            kwargs = mock_run.call_args[1]
            assert 'timeout' in kwargs
            assert kwargs['timeout'] == 5


def test_get_mount_point_uses_findmnt_target():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="/mnt/data\n", returncode=0)
        result = get_mount_point("/some/file/under/mount")
        assert result == "/mnt/data"

        args = mock_run.call_args[0][0]
        assert Path(args[0]).name == "findmnt"
        assert "-T" in args
        assert "/some/file/under/mount" in args


def test_get_mount_source_uses_findmnt_target():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="stash/media\n", returncode=0)
        result = get_mount_source("/some/file/under/mount")
        assert result == "stash/media"

        args = mock_run.call_args[0][0]
        assert Path(args[0]).name == "findmnt"
        assert "-T" in args
        assert "/some/file/under/mount" in args


class TestTryZfsGuid:
    """Test suite for _try_zfs_guid() helper function."""

    def test_success(self):
        """Test successful ZFS GUID detection."""
        test_guid = "12345678901234567890"

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout=f"{test_guid}\n",
                returncode=0
            )

            result = _try_zfs_guid("/pool/dataset")
            assert result == test_guid

    def test_returns_none_on_failure(self):
        """Test that function returns None on command failure."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, 'zfs')

            result = _try_zfs_guid("/pool/dataset")
            assert result is None

    def test_returns_none_on_dash_output(self):
        """Test that function returns None when GUID is '-'."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="-\n", returncode=0)

            result = _try_zfs_guid("/pool/dataset")
            assert result is None

    def test_returns_none_on_empty_output(self):
        """Test that function returns None when output is empty."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="\n", returncode=0)

            result = _try_zfs_guid("/pool/dataset")
            assert result is None

    def test_returns_none_on_non_numeric_guid(self):
        """Test that function returns None for non-numeric GUID."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="not-a-guid\n", returncode=0)

            result = _try_zfs_guid("/pool/dataset")
            assert result is None

    def test_zfs_command_not_available(self):
        """Test handling when zfs command is not installed."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()

            result = _try_zfs_guid("/pool/dataset")
            assert result is None

    def test_timeout_handling(self):
        """Test handling of command timeout."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired('zfs', 5)

            result = _try_zfs_guid("/pool/dataset")
            assert result is None

    def test_correct_command_arguments(self):
        """Test that zfs command is called with correct arguments."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="123\n", returncode=0)

            _try_zfs_guid("/pool/dataset")

            # Verify command arguments
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args == ['zfs', 'get', '-H', '-o', 'value', 'guid', '/pool/dataset']


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_permission_denied(self):
        """Test handling of permission denied errors."""
        with patch('subprocess.run') as mock_run:
            # Simulate permission denied
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, 'findmnt'),
                subprocess.CalledProcessError(1, 'zfs')
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                result = get_filesystem_uuid(tmpdir)
                # Should fallback to device_id
                assert result.startswith("dev-")

    def test_unicode_path(self):
        """Test handling of paths with unicode characters."""
        unicode_path = "/tmp/测试/path"

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, 'findmnt'),
                subprocess.CalledProcessError(1, 'zfs')
            ]

            # Mock os.stat to avoid actual filesystem access
            with patch('os.stat') as mock_stat:
                mock_stat.return_value = MagicMock(st_dev=42)
                result = get_filesystem_uuid(unicode_path)
                assert result == "dev-42"

    def test_whitespace_in_uuid(self):
        """Test that whitespace is properly stripped from UUID."""
        test_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        with patch('subprocess.run') as mock_run:
            # UUID with extra whitespace
            mock_run.return_value = MagicMock(
                stdout=f"  {test_uuid}  \n",
                returncode=0
            )

            result = get_filesystem_uuid("/some/path")
            assert result == test_uuid

    def test_consistent_results(self):
        """Test that function returns consistent results for same path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result1 = get_filesystem_uuid(tmpdir)
            result2 = get_filesystem_uuid(tmpdir)

            # Should return identical results
            assert result1 == result2

    def test_symlink_resolution(self):
        """Test that symlinks are handled correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a symlink
            symlink_path = os.path.join(tmpdir, "symlink")
            target_path = os.path.join(tmpdir, "target")
            os.makedirs(target_path)
            os.symlink(target_path, symlink_path)

            # Get UUID for both symlink and target
            uuid_symlink = get_filesystem_uuid(symlink_path)
            uuid_target = get_filesystem_uuid(target_path)

            # Both should return the same UUID (same filesystem)
            assert uuid_symlink == uuid_target


class TestGetZfsMetadata:
    """Test suite for get_zfs_metadata() function."""

    def test_success(self):
        """Test successful ZFS metadata extraction."""
        with patch('subprocess.run') as mock_run:
            # First call: zfs list
            # Second call: zpool get
            mock_run.side_effect = [
                MagicMock(stdout="tank/data/torrents\n", returncode=0),
                MagicMock(stdout="12345678901234567890\n", returncode=0)
            ]

            result = get_zfs_metadata("/tank/data/torrents")

            assert result == {
                'pool_name': 'tank',
                'dataset_name': 'tank/data/torrents',
                'pool_guid': '12345678901234567890'
            }

            # Verify both commands were called
            assert mock_run.call_count == 2

    def test_root_pool_dataset(self):
        """Test metadata for root pool dataset (no subdatasets)."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="pool\n", returncode=0),
                MagicMock(stdout="98765432109876543210\n", returncode=0)
            ]

            result = get_zfs_metadata("/pool")

            assert result == {
                'pool_name': 'pool',
                'dataset_name': 'pool',
                'pool_guid': '98765432109876543210'
            }

    def test_nested_dataset(self):
        """Test metadata for deeply nested dataset."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="tank/data/media/movies/recent\n", returncode=0),
                MagicMock(stdout="11111111111111111111\n", returncode=0)
            ]

            result = get_zfs_metadata("/tank/data/media/movies/recent")

            assert result['pool_name'] == 'tank'
            assert result['dataset_name'] == 'tank/data/media/movies/recent'

    def test_non_zfs_filesystem(self):
        """Test with non-ZFS filesystem path."""
        with patch('subprocess.run') as mock_run:
            # zfs list fails (not a ZFS dataset)
            mock_run.side_effect = subprocess.CalledProcessError(1, 'zfs')

            result = get_zfs_metadata("/mnt/ext4")
            assert result == {}

    def test_empty_dataset_name(self):
        """Test handling of empty dataset name."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="\n", returncode=0)

            result = get_zfs_metadata("/some/path")
            assert result == {}

    def test_empty_pool_guid(self):
        """Test handling of empty pool GUID."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="tank/data\n", returncode=0),
                MagicMock(stdout="\n", returncode=0)
            ]

            result = get_zfs_metadata("/tank/data")
            assert result == {
                'pool_name': 'tank',
                'dataset_name': 'tank/data',
                'pool_guid': None,
            }

    def test_dash_pool_guid(self):
        """Test handling of '-' as pool GUID."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="tank/data\n", returncode=0),
                MagicMock(stdout="-\n", returncode=0)
            ]

            result = get_zfs_metadata("/tank/data")
            assert result == {
                'pool_name': 'tank',
                'dataset_name': 'tank/data',
                'pool_guid': None,
            }

    def test_zfs_commands_not_available(self):
        """Test handling when ZFS commands are not installed."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError()

            result = get_zfs_metadata("/pool")
            assert result == {}

    def test_timeout_on_zfs_list(self):
        """Test handling of timeout on zfs list command."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired('zfs', 5)

            result = get_zfs_metadata("/pool")
            assert result == {}

    def test_timeout_on_zpool_get(self):
        """Test handling of timeout on zpool get command."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="tank/data\n", returncode=0),
                subprocess.TimeoutExpired('zpool', 5)
            ]

            result = get_zfs_metadata("/tank/data")
            assert result == {
                'pool_name': 'tank',
                'dataset_name': 'tank/data',
                'pool_guid': None,
            }

    def test_correct_command_arguments(self):
        """Test that ZFS commands are called with correct arguments."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="tank/data\n", returncode=0),
                MagicMock(stdout="12345\n", returncode=0)
            ]

            get_zfs_metadata("/tank/data")

            # Verify first call: zfs list
            first_call_args = mock_run.call_args_list[0][0][0]
            assert Path(first_call_args[0]).name == 'zfs'
            assert first_call_args[1:] == ['list', '-H', '-o', 'name', '/tank/data']

            # Verify second call: zpool get
            second_call_args = mock_run.call_args_list[1][0][0]
            assert Path(second_call_args[0]).name == 'zpool'
            assert second_call_args[1:] == ['get', '-H', '-o', 'value', 'guid', 'tank']

    def test_whitespace_handling(self):
        """Test that whitespace is properly stripped from output."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="  tank/data  \n", returncode=0),
                MagicMock(stdout="  12345  \n", returncode=0)
            ]

            result = get_zfs_metadata("/tank/data")

            assert result['dataset_name'] == 'tank/data'
            assert result['pool_guid'] == '12345'

    def test_exception_handling(self):
        """Test handling of unexpected exceptions."""
        with patch('subprocess.run') as mock_run:
            # Simulate unexpected exception
            mock_run.side_effect = RuntimeError("Unexpected error")

            result = get_zfs_metadata("/pool")
            assert result == {}

    def test_timeout_parameter(self):
        """Test that timeout is set on subprocess calls."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout="tank\n", returncode=0),
                MagicMock(stdout="12345\n", returncode=0)
            ]

            get_zfs_metadata("/tank")

            # Verify timeout on both calls
            assert mock_run.call_count == 2
            for call in mock_run.call_args_list:
                kwargs = call[1]
                assert 'timeout' in kwargs
                assert kwargs['timeout'] == 5
