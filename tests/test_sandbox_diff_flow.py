import os
from pathlib import Path

from hashall.model import connect_db
from hashall.scan import scan_path
from hashall.diff import diff_sessions


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_file_map(conn, device_id: int, prefix: str) -> dict:
    table_name = f"files_{device_id}"
    prefix = prefix.rstrip("/")
    rows = conn.execute(
        f"""
        SELECT path, sha256, sha1, inode
        FROM {table_name}
        WHERE status = 'active' AND (path = ? OR path LIKE ?)
        """,
        (prefix, f"{prefix}/%"),
    ).fetchall()

    files = {}
    for row in rows:
        path = row["path"]
        if path == prefix:
            rel_path = Path(path).name
        elif path.startswith(prefix + "/"):
            rel_path = path[len(prefix) + 1 :]
        else:
            rel_path = path
        display_path = "/" + rel_path.lstrip("/")
        file_hash = row["sha256"] or row["sha1"]
        files[display_path] = {
            "hash": file_hash,
            "inode": row["inode"],
            "device_id": device_id,
        }
    return files


def test_sandbox_diff_hardlink_equivalence(tmp_path: Path) -> None:
    sandbox_root = tmp_path / "sandbox"
    src_root = sandbox_root / "src"
    dst_root = sandbox_root / "dst"

    _write_text(src_root / "file1.txt", "alpha")
    _write_text(src_root / "file2.txt", "beta")
    _write_text(src_root / "subdir" / "file3.txt", "gamma")

    dst_root.mkdir(parents=True, exist_ok=True)
    os.link(src_root / "file1.txt", dst_root / "linked_alpha.txt")
    _write_text(dst_root / "file2.txt", "beta v2")
    _write_text(dst_root / "extra.txt", "delta")

    db_path = tmp_path / "catalog.db"
    scan_path(db_path=db_path, root_path=sandbox_root, hash_mode="full")

    conn = connect_db(db_path)
    device_id = os.stat(sandbox_root).st_dev

    src_files = _load_file_map(conn, device_id, "src")
    dst_files = _load_file_map(conn, device_id, "dst")

    diff = diff_sessions(src_files, dst_files)

    assert "/file2.txt" in diff["changed"]
    assert "/extra.txt" in diff["added"]
    assert "/linked_alpha.txt" not in diff["added"]
    assert "/subdir/file3.txt" in diff["removed"]
