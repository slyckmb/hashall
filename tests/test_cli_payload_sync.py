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

    def test_payload_sync_remaps_alternate_mountpoints_for_prefix_filtering(self):
        """
        qBittorrent may report torrent roots under an alternate mount target
        (ex: /data/media) while scans were done under a preferred mount target
        (ex: /stash/media). The CLI should remap roots so --path-prefix works.
        """
        stash_mount = self.tmp_path / "stash" / "media"
        data_mount = self.tmp_path / "data" / "media"
        stash_mount.mkdir(parents=True)
        data_mount.mkdir(parents=True)

        # Simulate a payload scanned under the preferred mount.
        payload_rel = Path("payload")
        payload_root_stash = stash_mount / payload_rel
        payload_root_data = data_mount / payload_rel
        payload_root_stash.mkdir(parents=True)
        payload_root_data.mkdir(parents=True)
        (payload_root_stash / "a.bin").write_bytes(b"a")
        (payload_root_stash / "b.bin").write_bytes(b"b")

        device_id = os.stat(stash_mount).st_dev

        conn = connect_db(self.db_path)
        cur = conn.cursor()
        ensure_files_table(cur, device_id)

        # Register device with preferred mount = stash_mount
        conn.execute(
            """
            INSERT OR REPLACE INTO devices (fs_uuid, device_id, device_alias, mount_point, preferred_mount_point)
            VALUES (?, ?, ?, ?, ?)
            """,
            (f"dev-{device_id}", device_id, "stash", str(stash_mount), str(stash_mount)),
        )

        now = time.time()
        for p in [payload_root_stash / "a.bin", payload_root_stash / "b.bin"]:
            st = p.stat()
            cur.execute(
                f"""
                INSERT INTO files_{device_id} (path, size, mtime, sha256, inode, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (str(payload_rel / p.name), st.st_size, now, f"sha256-{p.name}", st.st_ino),
            )
        conn.commit()
        conn.close()

        torrents = [
            QBitTorrent(
                hash="t1",
                name="torrent-1",
                save_path=str(data_mount),
                content_path=str(payload_root_data),
                category="",
                tags="",
                state="",
                size=0,
                progress=1.0,
            ),
        ]
        fake = _FakeQbit(torrents)

        def fake_get_mount_point(p: str):
            p = str(Path(p))
            if p.startswith(str(data_mount)):
                return str(data_mount)
            if p.startswith(str(stash_mount)):
                return str(stash_mount)
            return None

        def fake_get_mount_source(p: str):
            p = str(Path(p))
            if p.startswith(str(data_mount)) or p.startswith(str(stash_mount)):
                return "stash/media"
            return None

        runner = CliRunner()
        with (
            patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake),
            patch("hashall.pathing.get_mount_point", side_effect=fake_get_mount_point),
            patch("hashall.pathing.get_mount_source", side_effect=fake_get_mount_source),
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--dry-run",
                    "--path-prefix",
                    str(stash_mount),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("processed: 1", result.output)
        self.assertIn("skipped (path-prefix): 0", result.output)
        self.assertIn("complete payloads: 1", result.output)
        self.assertIn("missing in catalog: 0", result.output)

    def test_payload_sync_limit_stops_after_n(self):
        """--limit N stops processing after N torrents (post-filter)."""
        torrents = [
            QBitTorrent(
                hash=f"t{i}",
                name=f"torrent-{i}",
                save_path=str(self.tmp_path),
                content_path=str(self.payload_root),
                category="",
                tags="",
                state="",
                size=0,
                progress=1.0,
            )
            for i in range(5)
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
                    "--limit",
                    "2",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("processed: 2", result.output)

    def test_payload_sync_path_prefix_skips_out_of_scope(self):
        """Torrents whose root is not under --path-prefix are skipped."""
        torrents = [
            QBitTorrent(
                hash="in-scope",
                name="torrent-in",
                save_path=str(self.tmp_path),
                content_path=str(self.payload_root),
                category="",
                tags="",
                state="",
                size=0,
                progress=1.0,
            ),
            QBitTorrent(
                hash="out-of-scope",
                name="torrent-out",
                save_path="/",
                content_path="/totally/different/path",
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
        self.assertIn("processed: 1", result.output)
        self.assertIn("skipped (path-prefix): 1", result.output)


class TestPayloadSyncQbitFailFast(unittest.TestCase):
    """Test that qBittorrent connect/auth failures raise ClickException (exit 1)."""

    def setUp(self):
        fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        self.db_path = Path(db_path)
        # Initialize minimal schema
        conn = connect_db(self.db_path)
        conn.close()

    def tearDown(self):
        try:
            self.db_path.unlink()
        except FileNotFoundError:
            pass

    def test_qbit_connection_failure_exits_nonzero(self):
        """When qBittorrent connection fails, CLI exits non-zero with error message."""

        class _FailConnect:
            base_url = "http://fake:9999"
            last_error = "Connection refused"

            def test_connection(self):
                return False

            def login(self):
                return False

            def get_torrents(self, **kw):
                return []

        runner = CliRunner()
        with patch(
            "hashall.qbittorrent.get_qbittorrent_client",
            return_value=_FailConnect(),
        ):
            result = runner.invoke(
                cli,
                ["payload", "sync", "--db", str(self.db_path)],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Failed to connect", result.output)

    def test_qbit_auth_failure_exits_nonzero(self):
        """When qBittorrent auth fails, CLI exits non-zero with error message."""

        class _FailAuth:
            base_url = "http://fake:9999"
            last_error = "Forbidden"

            def test_connection(self):
                return True

            def login(self):
                return False

            def get_torrents(self, **kw):
                return []

        runner = CliRunner()
        with patch(
            "hashall.qbittorrent.get_qbittorrent_client",
            return_value=_FailAuth(),
        ):
            result = runner.invoke(
                cli,
                ["payload", "sync", "--db", str(self.db_path)],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Failed to authenticate", result.output)


if __name__ == "__main__":
    unittest.main()
