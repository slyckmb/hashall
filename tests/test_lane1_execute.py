"""Tests for lane1_execute.py — Lane 1 atomic rename + client repoint."""

from unittest.mock import patch, MagicMock, call

import pytest

from hashall.lane1_execute import execute_lane1_group_atomic


CANONICAL = "/pool/media/torrents/seeding/cross-seed/filelist"
SOURCE = "/pool/media/torrents/seeding/filelist"


def _make_group_item(
    source_dir=SOURCE,
    canonical_path=CANONICAL,
    name="SomeRelease",
    tor_hash="a" * 40,
    safe=True,
):
    return {
        "hash": tor_hash,
        "name": name,
        "source_dir": source_dir,
        "canonical_path": canonical_path,
        "canonical_content_path": f"{canonical_path}/{name}",
        "target_dir": f"{canonical_path}/{name}",
        "safe": safe,
        "source_exists": True,
        "target_exists": False,
        "same_device": True,
    }


class FakeQBitTorrent:
    def __init__(self, save_path=CANONICAL, state="pausedUP"):
        self.save_path = save_path
        self.state = state


class TestExecuteLane1GroupAtomic:
    def test_dry_run_no_mutations(self):
        """Dry-run: no os.rename, RT, or qB calls."""
        items = [_make_group_item(tor_hash="a" * 40)]
        with patch("os.rename") as mock_rename, \
             patch("os.makedirs") as mock_mkdir, \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False):
            result = execute_lane1_group_atomic(items, dry_run=True)

        assert result["rename_done"] is False
        mock_rename.assert_not_called()
        mock_mkdir.assert_not_called()
        assert result["items"][0]["rt"] == "dry_run"
        assert result["items"][0]["qb"] == "dry_run"

    def test_precheck_source_missing(self):
        """Source dir missing → raises error before rename."""
        items = [_make_group_item()]
        with patch("os.path.isdir", return_value=False):
            result = execute_lane1_group_atomic(items, dry_run=False)
        assert "source dir missing" in str(result["errors"])
        assert result["rename_done"] is False

    def test_precheck_target_exists(self):
        """Target already exists → raises error before rename."""
        items = [_make_group_item()]
        with patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=True):
            result = execute_lane1_group_atomic(items, dry_run=False)
        assert "target already exists" in str(result["errors"])
        assert result["rename_done"] is False

    def test_precheck_active_download(self):
        """Active download → raises error before rename."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="downloading")
        with patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)
        assert "active download" in str(result["errors"])
        assert result["rename_done"] is False

    def test_happy_path(self):
        """Happy path: rename, RT repoint, qB set_location."""
        items = [
            _make_group_item(tor_hash="a" * 40, name="First"),
            _make_group_item(tor_hash="b" * 40, name="Second"),
        ]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")
        qb.set_location.return_value = True

        with patch("os.rename") as mock_rename, \
             patch("os.makedirs") as mock_mkdir, \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("hashall.lane1_execute.rt_apply_directory_repoint"), \
             patch("hashall.lane1_execute.rt_xmlrpc_call") as mock_rt, \
             patch("hashall.lane1_execute._xmlrpc_scalar_text") as mock_scalar:
            # _xmlrpc_scalar_text: first d.directory → CANONICAL, then d.state → "1", repeat
            mock_scalar.side_effect = [
                CANONICAL, "1",   # first item: directory, state
                CANONICAL, "1",   # second item: directory, state
            ]
            mock_rt.return_value = "<ok>"

            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["rename_done"] is True
        mock_rename.assert_called_once()
        mock_mkdir.assert_called_once()
        assert len(result["items"]) == 2
        assert result["items"][0]["rt"] == "ok"
        assert result["items"][0]["qb"] == "ok"
        assert result["items"][1]["rt"] == "ok"
        assert result["items"][1]["qb"] == "ok"

    def test_rt_failure_continues(self):
        """RT repoint fails: rename done, item logged, continue to next."""
        items = [
            _make_group_item(tor_hash="a" * 40, name="First"),
            _make_group_item(tor_hash="b" * 40, name="Second"),
        ]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")
        qb.set_location.return_value = True

        with patch("os.rename") as mock_rename, \
             patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("hashall.lane1_execute.rt_apply_directory_repoint",
                   side_effect=[RuntimeError("RT failed"), None]), \
             patch("hashall.lane1_execute.rt_xmlrpc_call") as mock_rt, \
             patch("hashall.lane1_execute._xmlrpc_scalar_text") as mock_scalar:
            mock_scalar.side_effect = [CANONICAL, "1"]
            mock_rt.return_value = "<ok>"

            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["rename_done"] is True
        mock_rename.assert_called_once()
        assert result["items"][0]["rt"] == "failed"
        assert result["items"][1]["rt"] == "ok"
        assert result["items"][0]["qb"] == "ok"
        assert result["items"][1]["qb"] == "ok"

    def test_qb_failure_continues(self):
        """qB set_location fails: rename done, item logged, continue."""
        items = [
            _make_group_item(tor_hash="a" * 40, name="First"),
            _make_group_item(tor_hash="b" * 40, name="Second"),
        ]
        qb = MagicMock()
        qb.get_torrent_info.side_effect = [
            FakeQBitTorrent(state="pausedUP"),        # pre-check for first
            FakeQBitTorrent(state="pausedUP"),        # pre-check for second
            FakeQBitTorrent(save_path="/pool/media/torrents/seeding/cross-seed/filelist", state="pausedUP"),  # poll for first
            FakeQBitTorrent(save_path="/pool/media/torrents/seeding/cross-seed/filelist", state="pausedUP"),  # poll for second
        ]
        qb.set_location.side_effect = [True, False]   # first ok, second fails

        with patch("os.rename"), \
             patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("hashall.lane1_execute.rt_apply_directory_repoint"), \
             patch("hashall.lane1_execute.rt_xmlrpc_call") as mock_rt, \
             patch("hashall.lane1_execute._xmlrpc_scalar_text") as mock_scalar:
            def fake_scalar(xml):
                return "/pool/media/torrents/seeding/cross-seed/filelist"
            mock_scalar.side_effect = fake_scalar
            mock_rt.return_value = "ok"

            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["rename_done"] is True
        assert result["items"][0]["qb"] == "ok"
        assert result["items"][1]["qb"] == "failed"
        assert result["items"][0]["rt"] == "ok"
        assert result["items"][1]["rt"] == "ok"

    def test_post_check_source_still_exists(self):
        """Source still exists after rename → logged as error."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")
        qb.set_location.return_value = True

        with patch("os.rename"), \
             patch("os.makedirs"), \
             patch("os.path.isdir", side_effect=lambda p: "cross-seed" not in p), \
             patch("os.path.exists", side_effect=lambda p: "cross-seed" not in p), \
             patch("hashall.lane1_execute.rt_apply_directory_repoint"), \
             patch("hashall.lane1_execute.rt_xmlrpc_call") as mock_rt, \
             patch("hashall.lane1_execute._xmlrpc_scalar_text") as mock_scalar:
            def fake_scalar(xml):
                return "/pool/media/torrents/seeding/cross-seed/filelist"
            mock_scalar.side_effect = fake_scalar
            mock_rt.return_value = "ok"

            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        # source still exists → logged in errors
        source_errors = [e for e in result.get("errors", []) if "source dir still exists" in e]
        assert len(source_errors) >= 1
