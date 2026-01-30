# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
from pathlib import Path
import orjson
import sqlite3

def export_json(db_path: Path, root_path: Path = None, out_path: Path = None):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    if root_path:
        cursor = conn.execute("SELECT id, scan_id FROM scan_sessions WHERE root_path = ? ORDER BY started_at DESC LIMIT 1", (str(root_path),))
        row = cursor.fetchone()
        if not row:
            print(f"❌ No scan session found for: {root_path}")
            return
        scan_session_id = row["id"]
        scan_id = row["scan_id"]
    else:
        cursor = conn.execute("SELECT id, scan_id FROM scan_sessions ORDER BY started_at DESC LIMIT 1")
        row = cursor.fetchone()
        scan_session_id = row["id"]
        scan_id = row["scan_id"]

    files = conn.execute("SELECT path, size, mtime, sha1 FROM files WHERE scan_session_id = ?", (scan_session_id,))
    data = {
        "scan_id": scan_id,
        "root_path": str(root_path) if root_path else None,
        "files": [dict(row) for row in files],
    }

    out = Path(out_path) if out_path else Path.home() / ".hashall" / "hashall.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
    print(f"✅ Exported {len(data['files'])} records to: {out}")
