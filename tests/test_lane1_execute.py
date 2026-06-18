"""Tests for lane1_execute.py — Lane 1 atomic rename + client repoint."""

from unittest.mock import patch, MagicMock, call

import pytest

from hashall.lane1_execute import (
    execute_lane1_group_atomic,
    _rt_fetch_health,
    _rt_health_check,
)


CANONICAL = "/pool/media/torrents/seeding/cross-seed/filelist"
SOURCE = "/pool/media/torrents/seeding/filelist"

# Healthy RT return values used by most tests
_HEALTHY_FIELDS = {"complete": 1, "hashing": 0, "down_rate": 0}
_HEALTH_OK = {
    "ok": True, "complete": 1, "down_rate": 0, "hashing": 0,
    "note": "RT seeding ok",
}


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


def _rt_mocks(canonical=CANONICAL):
    """Return standard RT patches for tests that don't focus on RT health logic."""
    return [
        patch("hashall.lane1_execute._rt_fetch_health", return_value=_HEALTHY_FIELDS),
        patch("hashall.lane1_execute._rt_health_check", return_value=_HEALTH_OK),
        patch("hashall.lane1_execute.rt_apply_directory_repoint"),
        patch("hashall.lane1_execute.rt_xmlrpc_call", return_value="<ok>"),
        patch("hashall.lane1_execute._xmlrpc_scalar_text", return_value=canonical),
    ]


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
        """Active qB download → raises error before rename."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="downloading")
        with patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("hashall.lane1_execute._rt_fetch_health", return_value=_HEALTHY_FIELDS):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)
        assert "active qB download" in str(result["errors"])
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

        patches = _rt_mocks()
        with patch("os.rename") as mock_rename, \
             patch("os.makedirs") as mock_mkdir, \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patches[0], patches[1], patches[2], patches[3], patches[4]:
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
             patch("hashall.lane1_execute._rt_fetch_health", return_value=_HEALTHY_FIELDS), \
             patch("hashall.lane1_execute._rt_health_check", return_value=_HEALTH_OK), \
             patch("hashall.lane1_execute.rt_apply_directory_repoint",
                   side_effect=[RuntimeError("RT failed"), None]), \
             patch("hashall.lane1_execute.rt_xmlrpc_call", return_value="<ok>"), \
             patch("hashall.lane1_execute._xmlrpc_scalar_text", return_value=CANONICAL):
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
        qb.get_torrent_info.return_value = FakeQBitTorrent(save_path=CANONICAL, state="pausedUP")
        qb.set_location.side_effect = [True, False]

        patches = _rt_mocks()
        with patch("os.rename"), \
             patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patches[0], patches[1], patches[2], patches[3], patches[4]:
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

        patches = _rt_mocks()
        with patch("os.rename"), \
             patch("os.makedirs"), \
             patch("os.path.isdir", side_effect=lambda p: "cross-seed" not in p), \
             patch("os.path.exists", side_effect=lambda p: "cross-seed" not in p), \
             patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        source_errors = [e for e in result.get("errors", []) if "source dir still exists" in e]
        assert len(source_errors) >= 1


class TestQBRepause:
    """Re-pause logic: re-pause qB after set_location when not in PAUSED_STATES."""

    def test_qb_already_paused_no_repause(self):
        """Already paused after set_location → pause_torrent NOT called."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.set_location.return_value = True
        qb.get_torrent_info.return_value = FakeQBitTorrent(save_path=CANONICAL, state="pausedUP")

        patches = _rt_mocks()
        with patch("os.rename"), patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("time.sleep"):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["items"][0]["qb"] == "ok"
        qb.pause_torrent.assert_not_called()
        notes = " ".join(result["items"][0].get("notes", []))
        assert "pausedUP" in notes

    def test_qb_repause_after_checking_up(self):
        """checkingUP → stalledUP → re-pause succeeds."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.set_location.return_value = True

        call_n = [0]
        def fake_info(h):
            call_n[0] += 1
            n = call_n[0]
            if n == 1:
                return FakeQBitTorrent(save_path="/pool/old", state="pausedUP")
            if n <= 5:
                return FakeQBitTorrent(save_path=CANONICAL, state="checkingUP")
            return FakeQBitTorrent(save_path=CANONICAL,
                                   state="stalledUP" if n == 6 else "pausedUP")
        qb.get_torrent_info.side_effect = fake_info

        patches = _rt_mocks()
        with patch("os.rename"), patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("time.sleep"):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["items"][0]["qb"] == "ok"
        qb.pause_torrent.assert_called_once()
        notes = " ".join(result["items"][0].get("notes", []))
        assert "pausedUP" in notes

    def test_qb_repause_times_out(self):
        """Re-pause called but state stays stalledUP → warn_not_paused."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.set_location.return_value = True

        call_n = [0]
        def fake_info(h):
            call_n[0] += 1
            n = call_n[0]
            if n == 1:
                return FakeQBitTorrent(save_path="/pool/old", state="pausedUP")
            return FakeQBitTorrent(save_path=CANONICAL, state="stalledUP")
        qb.get_torrent_info.side_effect = fake_info

        patches = _rt_mocks()
        with patch("os.rename"), patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patches[0], patches[1], patches[2], patches[3], patches[4], \
             patch("time.sleep"):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["items"][0]["qb"] == "warn_not_paused"
        qb.pause_torrent.assert_called_once()


class TestRTDownloadMonitor:
    """RT download-state guard: pre-flight + post-repoint health checks."""

    def test_rt_precheck_blocks_downloading_before_rename(self):
        """Pre-flight: RT has down_rate>0 → group blocked before rename."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")

        downloading_fields = {"complete": 0, "hashing": 0, "down_rate": 2048}

        with patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("os.rename") as mock_rename, \
             patch("hashall.lane1_execute._rt_fetch_health",
                   return_value=downloading_fields):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["rename_done"] is False
        mock_rename.assert_not_called()
        assert any("RT downloading pre-rename" in e for e in result["errors"])

    def test_rt_precheck_blocks_incomplete_before_rename(self):
        """Pre-flight: RT has complete=0 (even with down_rate=0) → group blocked."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")

        incomplete_fields = {"complete": 0, "hashing": 0, "down_rate": 0}

        with patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("os.rename") as mock_rename, \
             patch("hashall.lane1_execute._rt_fetch_health",
                   return_value=incomplete_fields):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["rename_done"] is False
        mock_rename.assert_not_called()
        assert any("RT downloading pre-rename" in e for e in result["errors"])

    def test_rt_precheck_skips_on_rpc_error(self):
        """Pre-flight: _rt_fetch_health returns {} (RPC error) → do not block."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")
        qb.set_location.return_value = True

        with patch("os.rename"), \
             patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("hashall.lane1_execute._rt_fetch_health", return_value={}), \
             patch("hashall.lane1_execute._rt_health_check", return_value=_HEALTH_OK), \
             patch("hashall.lane1_execute.rt_apply_directory_repoint"), \
             patch("hashall.lane1_execute.rt_xmlrpc_call", return_value="<ok>"), \
             patch("hashall.lane1_execute._xmlrpc_scalar_text", return_value=CANONICAL):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["rename_done"] is True

    def test_rt_health_check_ok_sets_rt_ok(self):
        """Post-repoint: RT health ok → rt='ok'."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")
        qb.set_location.return_value = True

        patches = _rt_mocks()
        with patch("os.rename"), \
             patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["items"][0]["rt"] == "ok"
        notes = " ".join(result["items"][0]["notes"])
        assert "complete=1" in notes

    def test_rt_health_check_downloading_sets_warn(self):
        """Post-repoint: RT health not ok (down_rate>0) → rt='warn_downloading', qB still repointed."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")
        qb.set_location.return_value = True

        bad_health = {
            "ok": False, "complete": 0, "down_rate": 1024, "hashing": 0,
            "note": "RT incomplete after hashing: complete=0",
        }

        with patch("os.rename"), \
             patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("hashall.lane1_execute._rt_fetch_health", return_value=_HEALTHY_FIELDS), \
             patch("hashall.lane1_execute._rt_health_check", return_value=bad_health), \
             patch("hashall.lane1_execute.rt_apply_directory_repoint"), \
             patch("hashall.lane1_execute.rt_xmlrpc_call", return_value="<ok>"), \
             patch("hashall.lane1_execute._xmlrpc_scalar_text", return_value=CANONICAL):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        # RT flagged, but qB still repointed (path correction required regardless)
        assert result["items"][0]["rt"] == "warn_downloading"
        assert result["items"][0]["qb"] == "ok"
        # Group-level error propagated
        assert any("RT downloading post-repoint" in e for e in result["errors"])
        # Note includes the health message
        notes = " ".join(result["items"][0]["notes"])
        assert "RT incomplete" in notes

    def test_rt_health_check_timeout_sets_warn(self):
        """Post-repoint: RT stays hashing (timeout) → rt='warn_downloading'."""
        items = [_make_group_item(tor_hash="a" * 40)]
        qb = MagicMock()
        qb.get_torrent_info.return_value = FakeQBitTorrent(state="pausedUP")
        qb.set_location.return_value = True

        timeout_health = {
            "ok": False, "complete": 1, "down_rate": 0, "hashing": 1,
            "note": "RT still hashing after 15s poll",
        }

        with patch("os.rename"), \
             patch("os.makedirs"), \
             patch("os.path.isdir", return_value=True), \
             patch("os.path.exists", return_value=False), \
             patch("hashall.lane1_execute._rt_fetch_health", return_value=_HEALTHY_FIELDS), \
             patch("hashall.lane1_execute._rt_health_check", return_value=timeout_health), \
             patch("hashall.lane1_execute.rt_apply_directory_repoint"), \
             patch("hashall.lane1_execute.rt_xmlrpc_call", return_value="<ok>"), \
             patch("hashall.lane1_execute._xmlrpc_scalar_text", return_value=CANONICAL):
            result = execute_lane1_group_atomic(items, dry_run=False, qb_client=qb)

        assert result["items"][0]["rt"] == "warn_downloading"
        assert any("RT downloading post-repoint" in e for e in result["errors"])
        notes = " ".join(result["items"][0]["notes"])
        assert "still hashing" in notes


class TestRTFetchHealth:
    """Unit tests for _rt_fetch_health."""

    def test_returns_fields(self):
        """Normal: returns parsed integer fields."""
        call_n = [0]
        def fake_call(method, h, rpc_url=""):
            return f"<{method}>"
        def fake_scalar(xml):
            # complete → "1", hashing → "0", down_rate → "0"
            return {"<d.complete>": "1", "<d.hashing>": "0", "<d.down.rate>": "0"}[xml]

        with patch("hashall.lane1_execute.rt_xmlrpc_call", side_effect=fake_call), \
             patch("hashall.lane1_execute._xmlrpc_scalar_text", side_effect=fake_scalar):
            result = _rt_fetch_health("abc123", "http://localhost/RPC2")

        assert result == {"complete": 1, "hashing": 0, "down_rate": 0}

    def test_rpc_error_returns_empty(self):
        """RPC exception → returns empty dict (do not propagate)."""
        with patch("hashall.lane1_execute.rt_xmlrpc_call", side_effect=RuntimeError("conn refused")):
            result = _rt_fetch_health("abc123", "http://localhost/RPC2")
        assert result == {}


class TestRTHealthCheck:
    """Unit tests for _rt_health_check."""

    def test_seeding_immediately(self):
        """First poll: hashing=0, complete=1, down_rate=0 → ok=True."""
        with patch("hashall.lane1_execute._rt_fetch_health",
                   return_value={"complete": 1, "hashing": 0, "down_rate": 0}), \
             patch("time.sleep"):
            result = _rt_health_check("abc", "http://rt/RPC2", poll_secs=5.0)

        assert result["ok"] is True
        assert result["note"] == "RT seeding ok"

    def test_polls_until_hashing_clears(self):
        """hashing=1 on first poll, 0 on second → 2 polls, ok=True."""
        fields_seq = [
            {"complete": 1, "hashing": 1, "down_rate": 0},
            {"complete": 1, "hashing": 0, "down_rate": 0},
        ]
        call_n = [0]
        def fake_fetch(h, url):
            v = fields_seq[min(call_n[0], len(fields_seq) - 1)]
            call_n[0] += 1
            return v

        with patch("hashall.lane1_execute._rt_fetch_health", side_effect=fake_fetch), \
             patch("time.sleep"):
            result = _rt_health_check("abc", "http://rt/RPC2", poll_secs=5.0)

        assert result["ok"] is True
        assert call_n[0] == 2

    def test_timeout_stays_hashing(self):
        """All polls return hashing=1 → ok=False, 'still hashing' note."""
        with patch("hashall.lane1_execute._rt_fetch_health",
                   return_value={"complete": 1, "hashing": 1, "down_rate": 0}), \
             patch("time.sleep"):
            result = _rt_health_check("abc", "http://rt/RPC2", poll_secs=1.0)

        assert result["ok"] is False
        assert "still hashing" in result["note"]

    def test_downloading_after_hashing_clears(self):
        """Hashing clears but complete=0 → ok=False."""
        with patch("hashall.lane1_execute._rt_fetch_health",
                   return_value={"complete": 0, "hashing": 0, "down_rate": 512}), \
             patch("time.sleep"):
            result = _rt_health_check("abc", "http://rt/RPC2", poll_secs=1.0)

        assert result["ok"] is False
        assert "incomplete" in result["note"] or "down_rate" in result["note"]

    def test_rpc_error_returns_not_ok(self):
        """_rt_fetch_health returns {} (RPC error) → ok=False."""
        with patch("hashall.lane1_execute._rt_fetch_health", return_value={}), \
             patch("time.sleep"):
            result = _rt_health_check("abc", "http://rt/RPC2", poll_secs=1.0)

        assert result["ok"] is False
        assert "RPC error" in result["note"]
