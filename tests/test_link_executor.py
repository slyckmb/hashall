"""
Unit tests for link_executor module.

IMPORTANT: These tests create actual files and hardlinks to verify safety features.
"""

import sqlite3
import tempfile
import shutil
from pathlib import Path
import pytest

from hashall.link_executor import (
    compute_sha256,
    compute_fast_hash_sample,
    verify_files_exist,
    verify_file_unchanged,
    verify_hash_matches,
    verify_same_filesystem,
    verify_not_already_linked,
    create_hardlink_atomic,
    execute_action,
    ExecutionResult
)
from hashall.link_query import ActionInfo


def test_compute_sha256():
    """Test SHA256 hash computation."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("test content\n")
        temp_path = Path(f.name)

    try:
        hash_val = compute_sha256(temp_path)
        assert hash_val == "a1fff0ffefb9eace7230c24e50731f0a91c62f9cefdfe77121c2f607125dffae"
    finally:
        temp_path.unlink()


def test_compute_sha256_file_not_found():
    """Test SHA256 computation with missing file."""
    hash_val = compute_sha256(Path("/nonexistent/file.txt"))
    assert hash_val is None


def test_verify_files_exist_success():
    """Test file existence verification."""
    with tempfile.NamedTemporaryFile(delete=False) as f1, \
         tempfile.NamedTemporaryFile(delete=False) as f2:
        path1, path2 = Path(f1.name), Path(f2.name)

    try:
        success, error = verify_files_exist(path1, path2)
        assert success is True
        assert error is None
    finally:
        path1.unlink()
        path2.unlink()


def test_verify_files_exist_missing():
    """Test file existence verification with missing file."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        existing_path = Path(f.name)
        missing_path = Path("/nonexistent/file.txt")

    try:
        success, error = verify_files_exist(existing_path, missing_path)
        assert success is False
        assert "not found" in error.lower()
    finally:
        existing_path.unlink()


def test_verify_hash_matches_success():
    """Test hash verification."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("test content\n")
        temp_path = Path(f.name)

    try:
        expected_hash = "a1fff0ffefb9eace7230c24e50731f0a91c62f9cefdfe77121c2f607125dffae"
        success, error = verify_hash_matches(temp_path, expected_hash)
        assert success is True
        assert error is None
    finally:
        temp_path.unlink()


def test_verify_hash_matches_mismatch():
    """Test hash verification with mismatch."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("test content\n")
        temp_path = Path(f.name)

    try:
        wrong_hash = "0" * 64
        success, error = verify_hash_matches(temp_path, wrong_hash)
        assert success is False
        assert "mismatch" in error.lower()
    finally:
        temp_path.unlink()


def test_verify_not_already_linked_different_inodes():
    """Test verification that files are not already linked."""
    with tempfile.NamedTemporaryFile(delete=False) as f1, \
         tempfile.NamedTemporaryFile(delete=False) as f2:
        path1, path2 = Path(f1.name), Path(f2.name)

    try:
        success, error = verify_not_already_linked(path1, path2)
        assert success is True
        assert error is None
    finally:
        path1.unlink()
        path2.unlink()


def test_verify_not_already_linked_same_inode():
    """Test verification with already linked files."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        original_path = Path(f.name)
        link_path = original_path.parent / f"{original_path.name}.link"

    try:
        # Create hardlink
        import os
        os.link(original_path, link_path)

        success, error = verify_not_already_linked(original_path, link_path)
        assert success is False
        assert "already hardlinked" in error.lower()
    finally:
        original_path.unlink()
        if link_path.exists():
            link_path.unlink()


def test_create_hardlink_atomic_success():
    """Test atomic hardlink creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create canonical file
        canonical = tmpdir_path / "canonical.txt"
        canonical.write_text("test content")

        # Create duplicate file
        duplicate = tmpdir_path / "duplicate.txt"
        duplicate.write_text("test content")

        # Get original inodes
        canonical_inode = canonical.stat().st_ino
        duplicate_inode_before = duplicate.stat().st_ino

        # Create hardlink
        success, error, backup_path = create_hardlink_atomic(
            canonical, duplicate, create_backup=True
        )

        assert success is True
        assert error is None
        assert backup_path is None

        # Verify hardlink created (same inode now)
        assert duplicate.exists()
        assert duplicate.stat().st_ino == canonical_inode
        assert duplicate.stat().st_ino != duplicate_inode_before

        # Verify backup was cleaned up
        backup = tmpdir_path / "duplicate.txt.bak"
        assert not backup.exists()


def test_create_hardlink_atomic_no_backup():
    """Test hardlink creation without backup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        canonical = tmpdir_path / "canonical.txt"
        canonical.write_text("test content")

        duplicate = tmpdir_path / "duplicate.txt"
        duplicate.write_text("test content")

        canonical_inode = canonical.stat().st_ino

        success, error, backup_path = create_hardlink_atomic(
            canonical, duplicate, create_backup=False
        )

        assert success is True
        assert duplicate.stat().st_ino == canonical_inode


def test_create_hardlink_atomic_already_linked():
    """Test hardlink creation when files are already linked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        canonical = tmpdir_path / "canonical.txt"
        canonical.write_text("test content")

        duplicate = tmpdir_path / "duplicate.txt"

        # Create hardlink manually
        import os
        os.link(canonical, duplicate)

        # Try to create hardlink again (should succeed, but is a no-op internally)
        # Actually, our function will try to unlink and re-link, which should work
        success, error, backup_path = create_hardlink_atomic(
            canonical, duplicate, create_backup=True
        )

        assert success is True


def test_execute_action_dry_run():
    """Test action execution in dry-run mode."""
    # Create in-memory database with minimal schema
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE files_99 (
            path TEXT,
            sha1 TEXT,
            sha256 TEXT,
            status TEXT
        )
    """)

    cursor.execute("""
        INSERT INTO files_99 (path, sha256, status)
        VALUES ('file.txt', '4ad3ef64dfb83f7a8f789bce6f30cc1f8d18491b14db4c875309b150d2a7f1d5', 'active')
    """)
    conn.commit()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        canonical = tmpdir_path / "canonical.txt"
        canonical.write_text("test content\n")

        duplicate = tmpdir_path / "duplicate.txt"
        duplicate.write_text("test content\n")

        action = ActionInfo(
            id=1,
            plan_id=1,
            action_type='HARDLINK',
            status='pending',
            canonical_path=str(canonical),
            duplicate_path=str(duplicate),
            canonical_inode=canonical.stat().st_ino,
            duplicate_inode=duplicate.stat().st_ino,
            device_id=99,
            file_size=1000,
            sha256=None,
            bytes_to_save=1000,
            bytes_saved=0,
            executed_at=None,
            error_message=None
        )

        # Dry-run should succeed without modifying files
        duplicate_inode_before = duplicate.stat().st_ino

        success, error, bytes_saved = execute_action(
            conn, action,
            mount_point=str(tmpdir_path),
            dry_run=True,
            verify_mode='none',  # Skip verification for this test
            create_backup=False
        )

        assert success is True
        assert error is None
        assert bytes_saved == 1000

        # Files should not be modified
        assert duplicate.stat().st_ino == duplicate_inode_before

    conn.close()


def test_execute_action_missing_file():
    """Test action execution with missing file."""
    conn = sqlite3.connect(":memory:")

    action = ActionInfo(
        id=1, plan_id=1, action_type='HARDLINK', status='pending',
        canonical_path="/nonexistent/canonical.txt",
        duplicate_path="/nonexistent/duplicate.txt",
        canonical_inode=None, duplicate_inode=None,
        device_id=99, file_size=1000, sha256=None,
        bytes_to_save=1000, bytes_saved=0,
        executed_at=None, error_message=None
    )

    success, error, bytes_saved = execute_action(
        conn, action, dry_run=True, verify_mode='none', create_backup=False
    )

    assert success is False
    assert "not found" in error.lower()
    assert bytes_saved == 0

    conn.close()


def test_execution_result_creation():
    """Test ExecutionResult dataclass."""
    result = ExecutionResult(
        plan_id=1,
        actions_executed=10,
        actions_failed=2,
        actions_skipped=1,
        bytes_saved=10000,
        errors=["Error 1", "Error 2"]
    )

    assert result.plan_id == 1
    assert result.actions_executed == 10
    assert result.actions_failed == 2
    assert len(result.errors) == 2


def test_compute_fast_hash_sample():
    """Test fast hash sampling."""
    with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
        # Write 10MB file
        f.write(b'A' * (1024 * 1024))  # First MB
        f.write(b'B' * (1024 * 1024 * 8))  # Middle 8MB
        f.write(b'C' * (1024 * 1024))  # Last MB
        temp_path = Path(f.name)

    try:
        # Compute fast hash (samples first, middle, last 1MB)
        hash1 = compute_fast_hash_sample(temp_path)
        assert hash1 is not None

        # Same file should produce same hash
        hash2 = compute_fast_hash_sample(temp_path)
        assert hash1 == hash2
    finally:
        temp_path.unlink()


def test_compute_fast_hash_sample_different_files():
    """Test fast hash detects different files."""
    with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f1:
        f1.write(b'A' * (1024 * 1024 * 10))
        path1 = Path(f1.name)

    with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f2:
        f2.write(b'B' * (1024 * 1024 * 10))
        path2 = Path(f2.name)

    try:
        hash1 = compute_fast_hash_sample(path1)
        hash2 = compute_fast_hash_sample(path2)

        # Different content should produce different hashes
        assert hash1 != hash2
    finally:
        path1.unlink()
        path2.unlink()


def test_verify_file_unchanged_success():
    """Test file unchanged verification."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("test content\n")
        temp_path = Path(f.name)

    try:
        stat = temp_path.stat()
        success, error = verify_file_unchanged(temp_path, stat.st_size, stat.st_mtime)

        assert success is True
        assert error is None
    finally:
        temp_path.unlink()


def test_verify_file_unchanged_size_mismatch():
    """Test file unchanged detection with size change."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("test content\n")
        temp_path = Path(f.name)

    try:
        stat = temp_path.stat()

        # Check with wrong size
        success, error = verify_file_unchanged(temp_path, stat.st_size + 100, stat.st_mtime)

        assert success is False
        assert "size changed" in error.lower()
    finally:
        temp_path.unlink()


def test_verify_file_unchanged_mtime_mismatch():
    """Test file unchanged detection with mtime change."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("test content\n")
        temp_path = Path(f.name)

    try:
        stat = temp_path.stat()

        # Check with wrong mtime
        success, error = verify_file_unchanged(temp_path, stat.st_size, stat.st_mtime + 1000)

        assert success is False
        assert "modified" in error.lower()
    finally:
        temp_path.unlink()
