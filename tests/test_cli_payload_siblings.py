import os
import time

from click.testing import CliRunner

from hashall.cli import cli
from hashall.model import connect_db
from hashall.payload import Payload, TorrentInstance, upsert_payload, upsert_torrent_instance


def test_payload_siblings_uses_read_only_db_connection(tmp_path):
    db_path = tmp_path / "catalog.db"
    conn = connect_db(db_path)

    payload = Payload(
        payload_id=None,
        payload_hash="shared_cli_hash",
        device_id=49,
        root_path="/test/shared",
        file_count=2,
        total_bytes=200,
        status="complete",
        last_built_at=time.time(),
    )
    payload_id = upsert_payload(conn, payload)

    upsert_torrent_instance(
        conn,
        TorrentInstance(
            torrent_hash="hash_a",
            payload_id=payload_id,
            device_id=49,
            save_path="/test",
            root_name="torrent_a",
            category="tv",
            tags="tag_a",
            last_seen_at=time.time(),
        ),
    )
    upsert_torrent_instance(
        conn,
        TorrentInstance(
            torrent_hash="hash_b",
            payload_id=payload_id,
            device_id=49,
            save_path="/test",
            root_name="torrent_b",
            category="movies",
            tags="tag_b",
            last_seen_at=time.time(),
        ),
    )
    conn.close()

    os.chmod(db_path, 0o444)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["payload", "siblings", "--db", str(db_path), "hash_a"],
    )

    assert result.exit_code == 0, result.output
    assert "Torrent siblings for: hash_a" in result.output
    assert "Found 2 torrent(s) with same payload" in result.output
    assert "hash_b" in result.output
