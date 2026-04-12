"""
Tests for `hashall payload sync` CLI.
"""

import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

import hashall.cli as cli_mod
from hashall.cli import (
    cli,
    _build_rt_repair_assistant_row,
    _collect_complete_payload_candidates,
    _collect_sidecar_hits,
    _find_matching_complete_payload_id,
    _payload_sync_recount_for_hashes,
    _prune_unseen_incomplete_rt_instances,
)
from hashall.bencode import bencode_encode
from hashall.device import ensure_files_table
from hashall.model import connect_db
from hashall.payload import Payload, TorrentInstance, build_payload, upsert_payload, upsert_torrent_instance
from hashall.qbittorrent import QBitTorrent
from hashall.rtorrent import RTTorrentInventoryRow, load_rt_inventory_rows


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

    def _write_rt_session_pair(self, torrent_hash: str, directory: Path, info_name: str, *, multi_file: bool) -> None:
        session_dir = self.tmp_path / "rt-session"
        session_dir.mkdir(parents=True, exist_ok=True)

        rt_payload = {
            b"directory": str(directory).encode("utf-8"),
        }
        info_dict = {
            b"name": info_name.encode("utf-8"),
        }
        if multi_file:
            info_dict[b"files"] = [{b"path": [b"dummy.bin"], b"length": 1}]
        else:
            info_dict[b"length"] = 1

        (session_dir / f"{torrent_hash.upper()}.torrent.rtorrent").write_bytes(bencode_encode(rt_payload))
        (session_dir / f"{torrent_hash.upper()}.torrent").write_bytes(
            bencode_encode({b"info": info_dict})
        )

    def test_load_rt_inventory_rows_uses_directory_as_root_for_multi_file(self):
        root_name = "Example.Show.S01.1080p"
        payload_root = self.tmp_path / "library" / root_name
        payload_root.mkdir(parents=True)
        self._write_rt_session_pair("abc123", payload_root, root_name, multi_file=True)

        rows = load_rt_inventory_rows(self.tmp_path / "rt-session")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].save_path, str(payload_root))
        self.assertEqual(rows[0].content_path, str(payload_root))

    def test_load_rt_inventory_rows_appends_filename_for_single_file(self):
        file_name = "Example.Movie.2024.1080p.mkv"
        save_dir = self.tmp_path / "single"
        save_dir.mkdir(parents=True)
        self._write_rt_session_pair("def456", save_dir, file_name, multi_file=False)

        rows = load_rt_inventory_rows(self.tmp_path / "rt-session")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].save_path, str(save_dir))
        self.assertEqual(rows[0].content_path, str(save_dir / file_name))

    def test_prune_unseen_incomplete_rt_instances_removes_only_zero_file_rows(self):
        conn = connect_db(self.db_path)
        incomplete_payload_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash=None,
                device_id=None,
                root_path="/tmp/stale-root",
                file_count=0,
                total_bytes=0,
                status="incomplete",
                last_built_at=None,
            ),
            commit=False,
        )
        complete_payload_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="abc123",
                device_id=None,
                root_path="/tmp/live-root",
                file_count=1,
                total_bytes=1,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        upsert_torrent_instance(
            conn,
            TorrentInstance(
                torrent_hash="stale-hash",
                payload_id=incomplete_payload_id,
                device_id=None,
                save_path="/old",
                root_name="stale",
                category="",
                tags="",
                last_seen_at=time.time(),
            ),
            commit=False,
        )
        upsert_torrent_instance(
            conn,
            TorrentInstance(
                torrent_hash="live-hash",
                payload_id=complete_payload_id,
                device_id=None,
                save_path="/live",
                root_name="live",
                category="",
                tags="",
                last_seen_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()

        stats = _prune_unseen_incomplete_rt_instances(conn, seen_hashes={"live-hash"})
        conn.commit()

        self.assertEqual(stats["torrent_instances"], 1)
        self.assertEqual(stats["payload_candidates"], 1)
        remaining_hashes = {
            row[0] for row in conn.execute("SELECT torrent_hash FROM torrent_instances").fetchall()
        }
        self.assertEqual(remaining_hashes, {"live-hash"})
        conn.close()

    def test_payload_sync_recount_for_hashes_uses_current_payload_state(self):
        conn = connect_db(self.db_path)
        complete_payload_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="done",
                device_id=None,
                root_path="/tmp/done",
                file_count=1,
                total_bytes=1,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        incomplete_payload_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash=None,
                device_id=None,
                root_path="/tmp/missing",
                file_count=0,
                total_bytes=0,
                status="incomplete",
                last_built_at=None,
            ),
            commit=False,
        )
        upsert_torrent_instance(
            conn,
            TorrentInstance(
                torrent_hash="done-hash",
                payload_id=complete_payload_id,
                device_id=None,
                save_path="/tmp",
                root_name="done",
                category="",
                tags="",
                last_seen_at=time.time(),
            ),
            commit=False,
        )
        upsert_torrent_instance(
            conn,
            TorrentInstance(
                torrent_hash="missing-hash",
                payload_id=incomplete_payload_id,
                device_id=None,
                save_path="/tmp",
                root_name="missing",
                category="",
                tags="",
                last_seen_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()

        counts = _payload_sync_recount_for_hashes(
            conn, torrent_hashes={"done-hash", "missing-hash"}
        )
        self.assertEqual(counts, {"complete": 1, "incomplete": 1, "missing_in_catalog": 1})
        conn.close()

    def test_find_matching_complete_payload_id_uses_unique_size_and_count_match(self):
        conn = connect_db(self.db_path)
        matched_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="matched",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/TorrentLeech/The.World.At.War",
                file_count=26,
                total_bytes=1234,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="other",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/TorrentLeech/Other.Show",
                file_count=26,
                total_bytes=1234,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()

        resolved = _find_matching_complete_payload_id(
            conn,
            root_name="The.World.At.War",
            expected_file_count=26,
            expected_total_bytes=1234,
            save_path="/data/media/torrents/seeding/cross-seed/TorrentLeech/The.World.At.War",
            torrent_hash="",
        )
        self.assertEqual(resolved, matched_id)
        conn.close()

    def test_find_matching_complete_payload_id_requires_unique_match(self):
        conn = connect_db(self.db_path)
        upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="one",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/Aither (API)/Movie.mkv",
                file_count=1,
                total_bytes=42,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="two",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/seedpool (API)/Movie.mkv",
                file_count=1,
                total_bytes=42,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()

        resolved = _find_matching_complete_payload_id(
            conn,
            root_name="Movie.mkv",
            expected_file_count=1,
            expected_total_bytes=42,
            save_path="/downloads/complete/cross-seed/Movie.mkv",
            torrent_hash="",
        )
        self.assertIsNone(resolved)
        conn.close()

    def test_find_matching_complete_payload_id_prefers_hash_specific_rehome_candidate(self):
        conn = connect_db(self.db_path)
        matched_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="hash-specific",
                device_id=None,
                root_path="/pool/media/torrents/seeding/_rehome-unique/abc123/Movie.mkv",
                file_count=1,
                total_bytes=42,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="other-copy",
                device_id=None,
                root_path="/pool/media/torrents/seeding/cross-seed/seedpool (API)/Movie.mkv",
                file_count=1,
                total_bytes=42,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()

        resolved = _find_matching_complete_payload_id(
            conn,
            root_name="Movie.mkv",
            expected_file_count=1,
            expected_total_bytes=42,
            save_path="/downloads/complete/cross-seed/Movie.mkv",
            torrent_hash="abc123",
        )
        self.assertEqual(resolved, matched_id)
        conn.close()

    def test_find_matching_complete_payload_id_ignores_trailing_space_in_root_path(self):
        conn = connect_db(self.db_path)
        matched_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="trimmed",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/TorrentLeech/The.World.At.War ",
                file_count=26,
                total_bytes=999,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()

        resolved = _find_matching_complete_payload_id(
            conn,
            root_name="The.World.At.War",
            expected_file_count=26,
            expected_total_bytes=999,
            save_path="/data/media/torrents/seeding/cross-seed/TorrentLeech/The.World.At.War",
            torrent_hash="",
        )
        self.assertEqual(resolved, matched_id)
        conn.close()

    def test_collect_complete_payload_candidates_filters_by_count_size_and_name(self):
        conn = connect_db(self.db_path)
        matched_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="match",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/TorrentLeech/Show.Name",
                file_count=2,
                total_bytes=1234,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="other",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/TorrentLeech/Other.Name",
                file_count=2,
                total_bytes=1234,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()

        rows = _collect_complete_payload_candidates(
            conn,
            root_name="Show.Name",
            expected_file_count=2,
            expected_total_bytes=1234,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payload_id"], matched_id)
        conn.close()

    def test_collect_sidecar_hits_finds_nfo_txt_and_sample(self):
        sidecar_root = self.payload_root / "Movie.Name"
        sidecar_root.mkdir(parents=True, exist_ok=True)
        files = {
            sidecar_root / "Movie.Name.nfo": b"nfo",
            sidecar_root / "Movie.Name.txt": b"txt",
            sidecar_root / "Sample.mkv": b"sample",
        }
        conn = connect_db(self.db_path)
        device_id = os.stat(self.payload_root).st_dev
        now = time.time()
        for path, data in files.items():
            path.write_bytes(data)
            st = path.stat()
            conn.execute(
                f"""
                INSERT INTO files_{device_id} (path, size, mtime, sha256, inode, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                """,
                (str(path), st.st_size, now, f"sha256-{path.name}", st.st_ino),
            )
        conn.commit()

        hits = _collect_sidecar_hits(conn, root_name="Movie.Name")
        self.assertTrue(any(hit["size"] > 0 for hit in hits["nfo"]))
        self.assertTrue(any(hit["size"] > 0 for hit in hits["txt"]))
        self.assertTrue(any(hit["size"] > 0 for hit in hits["sample_mkv"]))
        conn.close()

    def test_rt_repair_worksheet_markdown_smoke(self):
        conn = connect_db(self.db_path)
        upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="candidate",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/TorrentLeech/Show.Name",
                file_count=2,
                total_bytes=1234,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash=None,
                device_id=None,
                root_path="/downloads/complete/cross-seed/Show.Name",
                file_count=0,
                total_bytes=0,
                status="incomplete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        upsert_torrent_instance(
            conn,
            TorrentInstance(
                torrent_hash="worksheet-hash",
                payload_id=2,
                device_id=None,
                save_path="/downloads/complete/cross-seed",
                root_name="Show.Name",
                category="",
                tags="",
                last_seen_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()
        conn.close()

        fake_rows = [
            RTTorrentInventoryRow(
                torrent_hash="worksheet-hash",
                root_name="Show.Name",
                save_path="/downloads/complete/cross-seed",
                content_path="/downloads/complete/cross-seed/Show.Name",
                expected_file_count=2,
                expected_total_bytes=1234,
            )
        ]
        runner = CliRunner()
        with patch("hashall.cli.load_rt_inventory_rows", return_value=fake_rows):
            result = runner.invoke(
                cli,
                [
                    "rt",
                    "repair-worksheet",
                    "--db",
                    str(self.db_path),
                    "--session-dir",
                    str(self.tmp_path),
                    "--markdown-output",
                ],
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("# RT Repair Worksheet", result.output)
        self.assertIn("worksheet-hash", result.output)

    def test_rt_repair_assistant_row_marks_healthy_item_not_broken(self):
        healthy_path = self.tmp_path / "healthy" / "Movie.mkv"
        healthy_path.parent.mkdir(parents=True, exist_ok=True)
        healthy_path.write_bytes(b"ok")

        decision = _build_rt_repair_assistant_row(
            {
                "rt_present": True,
                "rt_save_path": str(healthy_path.parent),
                "rt_content_path": str(healthy_path),
                "expected_file_count": 1,
                "expected_total_bytes": healthy_path.stat().st_size,
                "catalog_payload_status": "complete",
                "complete_candidates": [
                    {
                        "payload_id": 1,
                        "root_path": str(healthy_path),
                        "file_count": 1,
                        "total_bytes": healthy_path.stat().st_size,
                        "status": "complete",
                    }
                ],
            }
        )

        self.assertFalse(decision["broken_now"])
        self.assertEqual(decision["safe_to_mutate"], "no")
        self.assertEqual(decision["best_candidate_path"], "")

    def test_rt_repair_assistant_row_marks_exact_single_candidate_safe(self):
        current_path = self.tmp_path / "missing" / "Movie.mkv"
        candidate_path = self.tmp_path / "candidate" / "Movie.mkv"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_bytes(b"x" * 42)

        decision = _build_rt_repair_assistant_row(
            {
                "rt_present": True,
                "rt_save_path": str(current_path.parent),
                "rt_content_path": str(current_path),
                "expected_file_count": 1,
                "expected_total_bytes": 42,
                "catalog_payload_status": "incomplete",
                "complete_candidates": [
                    {
                        "payload_id": 2,
                        "root_path": str(candidate_path),
                        "file_count": 1,
                        "total_bytes": 42,
                        "status": "complete",
                    }
                ],
            }
        )

        self.assertTrue(decision["broken_now"])
        self.assertEqual(decision["best_candidate_path"], str(candidate_path))
        self.assertEqual(decision["confidence"], "high")
        self.assertEqual(decision["safe_to_mutate"], "yes")

    def test_rt_repair_assistant_row_marks_ambiguous_candidate_unsafe(self):
        current_path = self.tmp_path / "missing" / "Show.Name"
        candidate_a = self.tmp_path / "a" / "Show.Name"
        candidate_b = self.tmp_path / "b" / "Show.Name"
        candidate_a.parent.mkdir(parents=True, exist_ok=True)
        candidate_b.parent.mkdir(parents=True, exist_ok=True)
        candidate_a.write_bytes(b"a" * 10)
        candidate_b.write_bytes(b"b" * 10)

        decision = _build_rt_repair_assistant_row(
            {
                "rt_present": True,
                "rt_save_path": str(current_path.parent),
                "rt_content_path": str(current_path),
                "expected_file_count": 1,
                "expected_total_bytes": 10,
                "catalog_payload_status": "incomplete",
                "complete_candidates": [
                    {
                        "payload_id": 3,
                        "root_path": str(candidate_a),
                        "file_count": 1,
                        "total_bytes": 10,
                        "status": "complete",
                    },
                    {
                        "payload_id": 4,
                        "root_path": str(candidate_b),
                        "file_count": 1,
                        "total_bytes": 10,
                        "status": "complete",
                    },
                ],
            }
        )

        self.assertTrue(decision["broken_now"])
        self.assertEqual(decision["best_candidate_path"], "")
        self.assertEqual(decision["safe_to_mutate"], "no")
        self.assertEqual(decision["confidence"], "low")

    def test_rt_repair_assistant_outputs_only_strict_fields(self):
        conn = connect_db(self.db_path)
        payload_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="strict-complete",
                device_id=None,
                root_path=str(self.payload_root),
                file_count=2,
                total_bytes=2,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        upsert_torrent_instance(
            conn,
            TorrentInstance(
                torrent_hash="strict-hash",
                payload_id=payload_id,
                device_id=None,
                save_path="/downloads/complete/cross-seed",
                root_name=self.payload_root.name,
                category="",
                tags="",
                last_seen_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()
        conn.close()

        fake_rows = [
            RTTorrentInventoryRow(
                torrent_hash="strict-hash",
                root_name=self.payload_root.name,
                save_path="/downloads/complete/cross-seed",
                content_path="/downloads/complete/cross-seed/payload",
                expected_file_count=2,
                expected_total_bytes=2,
            )
        ]
        runner = CliRunner()
        with patch("hashall.cli.load_rt_inventory_rows", return_value=fake_rows):
            result = runner.invoke(
                cli,
                [
                    "rt",
                    "repair-assistant",
                    "--db",
                    str(self.db_path),
                    "--session-dir",
                    str(self.tmp_path),
                    "--hash",
                    "strict-hash",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        payload = cli_mod.json.loads(result.output)
        self.assertEqual(len(payload), 1)
        self.assertEqual(
            sorted(payload[0].keys()),
            sorted(
                [
                    "broken_now",
                    "current_client_path",
                    "best_candidate_path",
                    "confidence",
                    "why",
                    "safe_to_mutate",
                ]
            ),
        )

    def test_payload_sync_rt_reuses_complete_payload_from_expected_counts(self):
        conn = connect_db(self.db_path)
        matched_id = upsert_payload(
            conn,
            Payload(
                payload_id=None,
                payload_hash="matched-rt",
                device_id=None,
                root_path="/stash/media/torrents/seeding/cross-seed/DigitalCore (API)/12.Monkeys",
                file_count=2,
                total_bytes=1234,
                status="complete",
                last_built_at=time.time(),
            ),
            commit=False,
        )
        conn.commit()
        conn.close()

        runner = CliRunner()
        fake_rows = [
            RTTorrentInventoryRow(
                torrent_hash="rt-hash-1",
                root_name="12.Monkeys",
                save_path="/data/media/torrents/seeding/cross-seed/DigitalCore (API)/12.Monkeys",
                content_path="/data/media/torrents/seeding/cross-seed/DigitalCore (API)/12.Monkeys",
                expected_file_count=2,
                expected_total_bytes=1234,
            )
        ]
        empty_payload = Payload(
            payload_id=None,
            payload_hash=None,
            device_id=None,
            root_path="/data/media/torrents/seeding/cross-seed/DigitalCore (API)/12.Monkeys",
            file_count=0,
            total_bytes=0,
            status="incomplete",
            last_built_at=time.time(),
        )
        with patch("hashall.cli.load_rt_inventory_rows", return_value=fake_rows), patch(
            "hashall.payload.build_payload", return_value=empty_payload
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--source",
                    "rt",
                    "--rt-session-dir",
                    str(self.tmp_path),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Reused complete payload", result.output)
        conn = connect_db(self.db_path)
        row = conn.execute(
            "SELECT payload_id FROM torrent_instances WHERE torrent_hash = ?",
            ("rt-hash-1",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], matched_id)
        conn.close()

    def test_payload_sync_reports_post_upgrade_counts(self):
        runner = CliRunner()
        session_dir = self.tmp_path / "rt-session"
        session_dir.mkdir(parents=True, exist_ok=True)
        fake_rows = [
            RTTorrentInventoryRow(
                torrent_hash="upgraded-hash",
                root_name="Movie.mkv",
                save_path="/data/media/torrents/seeding/cross-seed/Aither (API)",
                content_path="/data/media/torrents/seeding/cross-seed/Aither (API)/Movie.mkv",
                expected_file_count=1,
                expected_total_bytes=42,
            )
        ]
        initial_payload = Payload(
            payload_id=None,
            payload_hash=None,
            device_id=46,
            root_path="/stash/media/torrents/seeding/cross-seed/Aither (API)/Movie.mkv",
            file_count=0,
            total_bytes=0,
            status="incomplete",
            last_built_at=None,
            fs_uuid="zfs-test",
        )
        upgraded_payload = replace(
            initial_payload,
            payload_hash="f" * 64,
            file_count=1,
            total_bytes=42,
            status="complete",
            last_built_at=time.time(),
        )

        with patch("hashall.cli.load_rt_inventory_rows", return_value=fake_rows), patch(
            "hashall.payload.build_payload", side_effect=[initial_payload, upgraded_payload]
        ), patch(
            "hashall.payload.summarize_missing_sha256_for_path",
            return_value={"files": 1, "bytes": 42},
        ), patch(
            "hashall.payload.upgrade_payload_missing_sha256",
            return_value=1,
        ), patch(
            "hashall.payload.count_missing_sha256_for_path",
            return_value=1,
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--source",
                    "rt",
                    "--rt-session-dir",
                    str(session_dir),
                    "--upgrade-missing",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("upgrade_summary queued=1 started=1 completed=1 failed=0", result.output)
        self.assertIn("complete payloads: 1", result.output)
        self.assertIn("incomplete payloads: 0", result.output)
        self.assertIn("missing in catalog: 0", result.output)

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

    def test_payload_sync_accepts_path_prefix_file(self):
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
        ]
        fake = _FakeQbit(torrents)
        prefix_file = self.tmp_path / "prefixes.txt"
        prefix_file.write_text(f"{self.tmp_path}\n", encoding="utf-8")

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
                    "--path-prefix-file",
                    str(prefix_file),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("processed: 1", result.output)
        self.assertIn("skipped (path-prefix): 0", result.output)

    def test_payload_sync_accepts_hash_progress_flag(self):
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
                    "--hash-progress",
                    "full",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("processed: 1", result.output)

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

    def test_payload_sync_supports_rt_source_from_session_dir(self):
        session_dir = self.tmp_path / "session"
        session_dir.mkdir()
        torrent_hash = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"
        (session_dir / f"{torrent_hash}.torrent.rtorrent").write_bytes(
            bencode_encode({b"directory": str(self.payload_root).encode("utf-8")})
        )
        (session_dir / f"{torrent_hash}.torrent").write_bytes(
            bencode_encode({b"info": {b"name": b"a.bin"}})
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "payload",
                "sync",
                "--db",
                str(self.db_path),
                "--source",
                "rt",
                "--rt-session-dir",
                str(session_dir),
                "--dry-run",
                "--path-prefix",
                str(self.tmp_path),
            ],
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Loaded 1 rTorrent session rows", result.output)
        self.assertIn("processed: 1", result.output)
        self.assertIn("complete payloads: 1", result.output)
        self.assertIn("root path source: rt_session_rows=1", result.output)

    def test_payload_sync_upgrade_uses_alias_aware_build_payload_for_rt_source(self):
        session_dir = self.tmp_path / "session"
        session_dir.mkdir()
        torrent_hash = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"
        root_alias = "/data/media/torrents/seeding/tv/example/example.mkv"

        (session_dir / f"{torrent_hash}.torrent.rtorrent").write_bytes(
            bencode_encode({b"directory": b"/data/media/torrents/seeding/tv/example"})
        )
        (session_dir / f"{torrent_hash}.torrent").write_bytes(
            bencode_encode({b"info": {b"name": b"example.mkv"}})
        )

        build_calls = []

        def fake_build_payload(conn, root_path, device_id=None, *, already_canonical=False):
            build_calls.append((root_path, device_id, already_canonical))
            status = "complete" if len(build_calls) > 1 else "incomplete"
            return Payload(
                payload_id=None,
                payload_hash="done-hash" if status == "complete" else None,
                device_id=device_id if device_id is not None else os.stat(self.payload_root).st_dev,
                root_path=root_path,
                file_count=1,
                total_bytes=1,
                status=status,
                last_built_at=None,
                fs_uuid=None,
            )

        runner = CliRunner()
        with (
            patch("hashall.payload.build_payload", side_effect=fake_build_payload),
            patch("hashall.payload.upsert_payload", return_value=1),
            patch("hashall.payload.upsert_torrent_instance"),
            patch("hashall.payload.summarize_missing_sha256_for_path", return_value={"files": 1, "bytes": 1}),
            patch("hashall.payload.upgrade_payload_missing_sha256", return_value=1),
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--source",
                    "rt",
                    "--rt-session-dir",
                    str(session_dir),
                    "--upgrade-missing",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertGreaterEqual(len(build_calls), 2)
        self.assertEqual(build_calls[0][0], root_alias)
        self.assertFalse(build_calls[0][2], result.output)
        self.assertFalse(build_calls[1][2], result.output)
        self.assertIn("✅ Upgrade complete: groups=1", result.output)

    def test_payload_sync_upgrade_skips_zero_file_roots_and_warns(self):
        session_dir = self.tmp_path / "session"
        session_dir.mkdir()
        torrent_hash = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"

        (session_dir / f"{torrent_hash}.torrent.rtorrent").write_bytes(
            bencode_encode({b"directory": b"/data/media/torrents/seeding/tv/example"})
        )
        (session_dir / f"{torrent_hash}.torrent").write_bytes(
            bencode_encode({b"info": {b"name": b"example.mkv"}})
        )

        def fake_build_payload(conn, root_path, device_id=None, *, already_canonical=False):
            return Payload(
                payload_id=None,
                payload_hash=None,
                device_id=device_id if device_id is not None else os.stat(self.payload_root).st_dev,
                root_path=root_path,
                file_count=0,
                total_bytes=0,
                status="incomplete",
                last_built_at=None,
                fs_uuid=None,
            )

        runner = CliRunner()
        with (
            patch("hashall.payload.build_payload", side_effect=fake_build_payload),
            patch("hashall.payload.upsert_payload", return_value=1),
            patch("hashall.payload.upsert_torrent_instance"),
            patch("hashall.payload.summarize_missing_sha256_for_path", return_value={"files": 0, "bytes": 0}),
            patch("hashall.payload.upgrade_payload_missing_sha256", side_effect=AssertionError("should not run")),
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--source",
                    "rt",
                    "--rt-session-dir",
                    str(session_dir),
                    "--upgrade-missing",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("zero-file roots skipped: 1", result.output)
        self.assertIn("upgrade stage completed with zero successful roots", result.output)

    def test_payload_sync_rejects_qb_filters_with_rt_source(self):
        session_dir = self.tmp_path / "session"
        session_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "payload",
                "sync",
                "--db",
                str(self.db_path),
                "--source",
                "rt",
                "--rt-session-dir",
                str(session_dir),
                "--category",
                "movies",
            ],
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--category/--tag are only supported with --source qb", result.output)

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

    def test_payload_sync_stages_orphan_prune_before_deleting(self):
        """Non-dry payload sync should mark orphan candidates before pruning them."""
        conn = connect_db(self.db_path)
        device_id = os.stat(self.payload_root).st_dev

        orphan_root = str(self.tmp_path / "stale" / "missing.mkv")
        keep_root = str(self.payload_root)

        cur = conn.cursor()
        orphan_id = cur.execute(
            """
            INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (None, device_id, orphan_root, 0, 0, "incomplete"),
        ).lastrowid
        keep_id = cur.execute(
            """
            INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("keep-hash", device_id, keep_root, 2, 2, "complete"),
        ).lastrowid
        cur.execute(
            """
            INSERT INTO torrent_instances (torrent_hash, payload_id, device_id, save_path, root_name, category, tags, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("keep-torrent", keep_id, device_id, str(self.tmp_path), self.payload_root.name, "", "", time.time()),
        )
        conn.commit()
        conn.close()

        fake = _FakeQbit([])
        runner = CliRunner()
        with patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--path-prefix",
                    str(self.tmp_path),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("orphan gc candidates: 1 (new=1, aged=0)", result.output)
        self.assertIn("orphan payloads pruned: 0", result.output)

        conn = connect_db(self.db_path)
        rows = conn.execute(
            "SELECT payload_id, root_path FROM payloads ORDER BY payload_id"
        ).fetchall()
        gc_rows = conn.execute("SELECT payload_id, seen_count FROM payload_orphan_gc").fetchall()
        conn.close()

        self.assertEqual(len(rows), 2)
        self.assertEqual(len(gc_rows), 1)
        self.assertEqual(int(gc_rows[0][0]), int(orphan_id))

        conn = connect_db(self.db_path)
        conn.execute(
            "UPDATE payload_orphan_gc SET first_seen_at = ?, seen_count = 1 WHERE payload_id = ?",
            (time.time() - (24 * 60 * 60 + 60), orphan_id),
        )
        conn.commit()
        conn.close()

        with patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--path-prefix",
                    str(self.tmp_path),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("orphan gc candidates: 1 (new=0, aged=1)", result.output)
        self.assertIn("orphan payloads pruned: 1", result.output)

        conn = connect_db(self.db_path)
        rows = conn.execute(
            "SELECT payload_id, root_path FROM payloads ORDER BY payload_id"
        ).fetchall()
        gc_rows = conn.execute("SELECT payload_id, seen_count FROM payload_orphan_gc").fetchall()
        conn.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], keep_id)
        self.assertEqual(rows[0][1], keep_root)
        self.assertEqual(gc_rows, [])

    def test_payload_sync_blocks_bulk_orphan_prune_spike(self):
        """Bulk prune should be blocked when candidate volume trips safety thresholds."""
        conn = connect_db(self.db_path)
        device_id = os.stat(self.payload_root).st_dev

        cur = conn.cursor()
        orphan_ids = []
        for idx in range(3):
            orphan_ids.append(
                cur.execute(
                    """
                    INSERT INTO payloads (payload_hash, device_id, root_path, file_count, total_bytes, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (None, device_id, str(self.tmp_path / "stale" / f"missing-{idx}.mkv"), 0, 0, "incomplete"),
                ).lastrowid
            )
        conn.commit()
        conn.close()

        fake = _FakeQbit([])
        runner = CliRunner()
        with patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--path-prefix",
                    str(self.tmp_path),
                ],
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("orphan payloads pruned: 0", result.output)

        conn = connect_db(self.db_path)
        conn.execute(
            "UPDATE payload_orphan_gc SET first_seen_at = ?, seen_count = 1",
            (time.time() - (24 * 60 * 60 + 60),),
        )
        conn.commit()
        conn.close()

        with (
            patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake),
            patch("hashall.payload.ORPHAN_GC_MAX_PRUNE_COUNT", 2),
            patch("hashall.payload.ORPHAN_GC_SPIKE_MIN_TOTAL", 1),
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--path-prefix",
                    str(self.tmp_path),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("orphan gc candidates: 3 (new=0, aged=3)", result.output)
        self.assertIn("orphan payloads pruned: 0", result.output)
        self.assertIn("orphan prune blocked", result.output)

        conn = connect_db(self.db_path)
        remaining = conn.execute("SELECT COUNT(*) FROM payloads").fetchone()[0]
        conn.close()

        self.assertEqual(remaining, 3)

    def test_payload_sync_upgrade_queues_unique_root_once(self):
        """When multiple torrents share one incomplete root, upgrade runs once for that root."""
        device_id = os.stat(self.payload_root).st_dev
        conn = connect_db(self.db_path)
        conn.execute(f"UPDATE files_{device_id} SET sha256 = NULL, sha1 = NULL")
        conn.commit()
        conn.close()

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
                save_path=str(self.tmp_path),
                content_path=str(self.payload_root),
                category="",
                tags="",
                state="",
                size=0,
                progress=1.0,
            ),
        ]
        fake = _FakeQbit(torrents)

        runner = CliRunner()
        with (
            patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake),
            patch("hashall.payload.upgrade_payload_missing_sha256", return_value=0) as mock_upgrade,
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--upgrade-missing",
                    "--path-prefix",
                    str(self.tmp_path),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_upgrade.call_count, 1)
        self.assertIn("upgrade stage: queued=1 started=1", result.output)

    def test_payload_sync_upgrade_resume_skips_completed_root_from_checkpoint(self):
        device_id = os.stat(self.payload_root).st_dev
        conn = connect_db(self.db_path)
        conn.execute(f"UPDATE files_{device_id} SET sha256 = 'ready', sha1 = 'ready'")
        conn.commit()
        conn.close()

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
        ]
        fake = _FakeQbit(torrents)
        scope = cli_mod._payload_sync_upgrade_scope(
            db_path=self.db_path,
            path_prefixes=[self.tmp_path],
            category="",
            tag="",
            limit=0,
            upgrade_order="small-first",
            upgrade_root_limit=0,
        )
        state_path = cli_mod._payload_sync_upgrade_state_path(scope)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            cli_mod.json.dumps(
                {
                    "completed_roots": {
                        cli_mod._payload_sync_upgrade_root_key(
                            {"device_id": device_id, "root_path": str(self.payload_root)}
                        ): {
                            "root_path": str(self.payload_root),
                            "device_id": device_id,
                            "completed_at": 123,
                            "payload_hash": "done-hash",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        conn = connect_db(self.db_path)
        payload_complete = build_payload(conn, str(self.payload_root), device_id=device_id, already_canonical=True)
        conn.close()
        payload_incomplete = replace(payload_complete, payload_hash=None, status="incomplete", last_built_at=None)

        runner = CliRunner()
        with (
            patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake),
            patch("hashall.payload.build_payload", return_value=payload_incomplete),
            patch("hashall.payload.upgrade_payload_missing_sha256") as mock_upgrade,
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--upgrade-missing",
                    "--path-prefix",
                    str(self.tmp_path),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_upgrade.call_count, 0)
        self.assertIn("resume checkpoint: skipped already-complete roots=1", result.output)
        self.assertFalse(state_path.exists())

    def test_payload_sync_upgrade_resume_does_not_skip_stale_checkpoint(self):
        device_id = os.stat(self.payload_root).st_dev
        conn = connect_db(self.db_path)
        conn.execute(f"UPDATE files_{device_id} SET sha256 = NULL, sha1 = NULL")
        conn.commit()
        conn.close()

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
        ]
        fake = _FakeQbit(torrents)
        scope = cli_mod._payload_sync_upgrade_scope(
            db_path=self.db_path,
            path_prefixes=[self.tmp_path],
            category="",
            tag="",
            limit=0,
            upgrade_order="small-first",
            upgrade_root_limit=0,
        )
        state_path = cli_mod._payload_sync_upgrade_state_path(scope)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            cli_mod.json.dumps(
                {
                    "completed_roots": {
                        cli_mod._payload_sync_upgrade_root_key(
                            {"device_id": device_id, "root_path": str(self.payload_root)}
                        ): {
                            "root_path": str(self.payload_root),
                            "device_id": device_id,
                            "completed_at": 123,
                            "payload_hash": "stale-hash",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        runner = CliRunner()
        with (
            patch("hashall.qbittorrent.get_qbittorrent_client", return_value=fake),
            patch("hashall.payload.upgrade_payload_missing_sha256", return_value=0) as mock_upgrade,
        ):
            result = runner.invoke(
                cli,
                [
                    "payload",
                    "sync",
                    "--db",
                    str(self.db_path),
                    "--upgrade-missing",
                    "--path-prefix",
                    str(self.tmp_path),
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_upgrade.call_count, 1)
        self.assertNotIn("resume checkpoint: skipped already-complete roots=1", result.output)


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
