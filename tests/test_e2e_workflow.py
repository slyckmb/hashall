"""End-to-end integration test for scan → export → verify workflow."""
import tempfile
import shutil
from pathlib import Path
import sqlite3
import json

from hashall.scan import scan_path
from hashall.export import export_json
from hashall.model import load_json_scan_into_db, connect_db


def test_scan_export_verify_roundtrip():
    """Test complete workflow: scan source, export, scan dest, verify."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        src = base / "src"
        dst = base / "dst"
        db_path = base / "test.db"

        # Create source tree
        src.mkdir()
        (src / "file1.txt").write_text("content1")
        (src / "file2.txt").write_text("content2")
        (src / "subdir").mkdir()
        (src / "subdir" / "file3.txt").write_text("content3")

        # Create destination tree (identical)
        dst.mkdir()
        (dst / "file1.txt").write_text("content1")
        (dst / "file2.txt").write_text("content2")
        (dst / "subdir").mkdir()
        (dst / "subdir" / "file3.txt").write_text("content3")

        # Step 1: Scan source
        scan_path(db_path=db_path, root_path=src)

        # Step 2: Export source
        export_json(db_path=db_path, root_path=src)

        # Verify export created correct path
        export_file = src / ".hashall" / "hashall.json"
        assert export_file.exists(), "Export should create <root>/.hashall/hashall.json"

        # Step 3: Load export back into DB
        conn = connect_db(db_path)
        scan_id = load_json_scan_into_db(conn, str(export_file))
        assert scan_id is not None, "Should load scan_id from JSON"

        # Step 4: Verify JSON contains expected data
        export_data = json.loads(export_file.read_text())
        assert "scan_id" in export_data
        assert "root_path" in export_data
        assert "files" in export_data
        assert len(export_data["files"]) == 3, "Should have 3 files"

        # Step 5: Verify all files have required fields including hardlink data
        for file_entry in export_data["files"]:
            assert "path" in file_entry
            assert "size" in file_entry
            assert "mtime" in file_entry
            assert "sha1" in file_entry
            assert "sha256" in file_entry
            assert "inode" in file_entry, "Export should include inode"
            assert "device_id" in file_entry, "Export should include device_id"

        # Step 6: Scan destination
        scan_path(db_path=db_path, root_path=dst)

        # Step 7: Export destination
        export_json(db_path=db_path, root_path=dst)

        # Verify destination export also created correct path
        dst_export_file = dst / ".hashall" / "hashall.json"
        assert dst_export_file.exists(), "Dest export should create <root>/.hashall/hashall.json"

        # Step 8: Verify both exports are independent (different scan_ids)
        dst_export_data = json.loads(dst_export_file.read_text())
        assert export_data["scan_id"] != dst_export_data["scan_id"], "Each scan should have unique ID"

        # Step 9: Verify file counts match
        cursor = conn.cursor()
        src_session = conn.execute(
            "SELECT id FROM scan_sessions WHERE root_path = ? ORDER BY id DESC LIMIT 1",
            (str(src),)
        ).fetchone()
        dst_session = conn.execute(
            "SELECT id FROM scan_sessions WHERE root_path = ? ORDER BY id DESC LIMIT 1",
            (str(dst),)
        ).fetchone()

        src_device_id = conn.execute(
            "SELECT device_id FROM scan_sessions WHERE id = ?",
            (src_session["id"],)
        ).fetchone()[0]
        dst_device_id = conn.execute(
            "SELECT device_id FROM scan_sessions WHERE id = ?",
            (dst_session["id"],)
        ).fetchone()[0]

        src_count = cursor.execute(
            f"SELECT COUNT(*) FROM files_{src_device_id} WHERE status = 'active'"
        ).fetchone()[0]
        dst_count = cursor.execute(
            f"SELECT COUNT(*) FROM files_{dst_device_id} WHERE status = 'active'"
        ).fetchone()[0]

        assert src_count == 3, "Source should have 3 files"
        assert dst_count == 3, "Destination should have 3 files"

        conn.close()
        print("✅ E2E test passed: scan → export → verify workflow works correctly")


def test_hardlink_detection():
    """Test that hardlinks are properly detected and exported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        root = base / "hardlink_test"
        db_path = base / "test.db"

        root.mkdir()

        # Create original file
        original = root / "original.txt"
        original.write_text("shared content")

        # Create hardlink
        hardlink = root / "hardlink.txt"
        hardlink.hardlink_to(original)

        # Create unique file
        unique = root / "unique.txt"
        unique.write_text("different content")

        # Scan and export
        scan_path(db_path=db_path, root_path=root)
        export_json(db_path=db_path, root_path=root)

        # Load export
        export_file = root / ".hashall" / "hashall.json"
        export_data = json.loads(export_file.read_text())

        # Find the files in export
        files_by_path = {f["path"]: f for f in export_data["files"]}

        assert "original.txt" in files_by_path
        assert "hardlink.txt" in files_by_path
        assert "unique.txt" in files_by_path

        # Verify hardlinked files have same inode
        original_inode = files_by_path["original.txt"]["inode"]
        hardlink_inode = files_by_path["hardlink.txt"]["inode"]
        unique_inode = files_by_path["unique.txt"]["inode"]

        assert original_inode == hardlink_inode, "Hardlinked files should have same inode"
        assert original_inode != unique_inode, "Unique file should have different inode"

        # Verify they also have same device_id
        assert files_by_path["original.txt"]["device_id"] == files_by_path["hardlink.txt"]["device_id"]

        print("✅ Hardlink detection test passed: inodes correctly tracked")


if __name__ == "__main__":
    test_scan_export_verify_roundtrip()
    test_hardlink_detection()
    print("\n✅ All E2E tests passed")
