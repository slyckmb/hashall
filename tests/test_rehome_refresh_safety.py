import sqlite3
from pathlib import Path

from rehome.auto import _parse_upgrade_summary, _run_catalog_preflight


def test_parse_upgrade_summary_extracts_counts() -> None:
    parsed = _parse_upgrade_summary(
        "noise\nupgrade_summary queued=12 started=12 completed=9 failed=3 elapsed_s=55\n"
    )
    assert parsed == {"queued": 12, "started": 12, "completed": 9, "failed": 3}


def test_parse_upgrade_summary_returns_none_without_marker() -> None:
    assert _parse_upgrade_summary("no summary line") is None


def test_run_catalog_preflight_reports_unknown_device_refs(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE devices (device_id INTEGER PRIMARY KEY, device_alias TEXT)")
    conn.execute("CREATE TABLE payloads (payload_id INTEGER PRIMARY KEY, device_id INTEGER)")
    conn.execute("CREATE TABLE torrent_instances (torrent_hash TEXT PRIMARY KEY, device_id INTEGER)")
    conn.execute("INSERT INTO payloads (payload_id, device_id) VALUES (1, 999)")
    conn.commit()
    conn.close()

    ok, report = _run_catalog_preflight(Path(db_path))
    assert ok is False
    assert any(
        str(chk.get("name")) == "payload_device_refs_known" and not bool(chk.get("ok"))
        for chk in report.get("checks", [])
    )
