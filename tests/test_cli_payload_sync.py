"""
Tests for `hashall payload sync` CLI.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from hashall.cli import cli
from hashall.device import ensure_files_table
from hashall.model import connect_db
from hashall.qbittorrent import QBitTorrent


class _FakeQbit:
    def __init__(self, torrents):
        self.base_url = "http://fake"
        self._torrents = list(torrents)

    def test_connection(self) -> bool:
        return True

    def login(self) -> bool:
        return True

    def get_torrents(self, category=None, tag=None):
        return self._torrents

    def get_torrent_root_path(self, torrent):
        return torrent.content_path


class TestPayloadSyncCLI(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

        # Create payload root with a couple files
        self.payload_root = self.tmp_path / "payload"
        self.payload_root.mkdir(parents=True)
        (self.payload_root / "a.bin").write_bytes(b"a")
        (self.payload_root / "b.bin").write_bytes(b"b")

        # Create temp DB
        fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        self.db_path = Path(db_path)

        # Initialize schema + insert file rows (absolute paths for test simplicity)
        conn = connect_db(self.db_path)
        device_id = os.stat(self.payload_root).st_dev
        cur = conn.cursor()
        ensure_files_table(cur, device_id)

        now = time.time()
        for p in [self.payload_root / "a.bin", self.payload_root / "b.bin"]:
            st = p.stat()
            cur.execute(
                f"""
                INSERT INTO files_{device_id} (path, size, mtime, sha256, inode, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (str(p), st.st_size, now, f"sha256-{p.name}", st.st_ino),
            )
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            self.db_path.unlink()
        except FileNotFoundError:
            pass
        self._tmpdir.cleanup()

    def test_payload_sync_dry_run_no_db_writes(self):
        torrents = [
            QBitTorrent(
                hash="t1",
                name="torrent-1",
                save_path=str(self.tmp_path),
                content_path=str(self.payload_root),
                category="",
                tags="",
                state="",
                size=0,
                progress=1.0,
            ),
            QBitTorrent(
                hash="t2",
                name="torrent-2",
                save_path="/",
                content_path="/not/under/prefix",
                category="",
                tags="",
                state="",
                size=0,
                progress=1.0,
            ),
        ]
        fake = _FakeQbit(torrents)

        runner = CliRunner()
        with patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--dry-run",
                    "--path-prefix",
                    str(self.tmp_path),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("DRY-RUN complete", result.output)
        self.assertIn("processed: 1", result.output)
        self.assertIn("skipped (path-prefix): 1", result.output)
        self.assertIn("complete payloads: 1", result.output)

        # Verify dry-run did not insert payloads or torrent instances
        conn = connect_db(self.db_path)
        payloads = conn.execute("SELECT COUNT(*) FROM payloads").fetchone()[0]
        instances = conn.execute("SELECT COUNT(*) FROM torrent_instances").fetchone()[0]
        conn.close()

        self.assertEqual(payloads, 0)
        self.assertEqual(instances, 0)


if __name__ == "__main__":
    unittest.main()

