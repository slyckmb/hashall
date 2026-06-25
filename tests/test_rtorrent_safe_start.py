"""Tests for rt_check_and_conditionally_start and related safe-start guards."""

from unittest.mock import patch, MagicMock, call

import pytest

from hashall.rtorrent import (
    rt_check_and_conditionally_start,
    rt_apply_directory_repoint,
    rt_recheck_torrent,
)


HASH = "a" * 40
RPC = "http://127.0.0.1:18000/"


def _scalar_text(value):
    """Return minimal XMLRPC-like string that _xmlrpc_scalar_text can parse."""
    if isinstance(value, int):
        return f"<value><i4>{value}</i4></value>"
    return f"<value><string>{value}</string></value>"


class TestCheckAndConditionallyStart:
    def test_complete(self):
        """d.complete==1 after hashing → d.start called, started=True."""
        call_log = []

        def fake_xmlrpc(method, *args, rpc_url=RPC, timeout=60):
            call_log.append((method, args))
            if method == "d.hashing":
                if len([c for c in call_log if c[0] == "d.hashing"]) == 1:
                    return _scalar_text(0)
                return _scalar_text(0)
            if method == "d.complete":
                return _scalar_text(1)
            return "<value><i4>0</i4></value>"

        with patch("hashall.rtorrent.rt_xmlrpc_call", side_effect=fake_xmlrpc) as mock_call:
            result = rt_check_and_conditionally_start(HASH, rpc_url=RPC, poll_secs=5.0)

        assert result["started"] is True
        assert result["complete"] == 1
        assert result["hashing"] == 0
        assert "started" in result["note"]
        d_start_calls = [c for c in call_log if c[0] == "d.start"]
        assert len(d_start_calls) == 1

    def test_incomplete(self):
        """d.complete==0 after hashing → d.start NOT called."""
        call_log = []

        def fake_xmlrpc(method, *args, rpc_url=RPC, timeout=60):
            call_log.append((method, args))
            if method == "d.hashing":
                return _scalar_text(0)
            if method == "d.complete":
                return _scalar_text(0)
            return "<value><i4>0</i4></value>"

        with patch("hashall.rtorrent.rt_xmlrpc_call", side_effect=fake_xmlrpc) as mock_call:
            result = rt_check_and_conditionally_start(HASH, rpc_url=RPC, poll_secs=5.0)

        assert result["started"] is False
        assert result["complete"] == 0
        d_start_calls = [c for c in call_log if c[0] == "d.start"]
        assert len(d_start_calls) == 0

    def test_timeout(self):
        """d.hashing never reaches 0 → timed out, started=False."""
        call_log = []

        def fake_xmlrpc(method, *args, rpc_url=RPC, timeout=60):
            call_log.append((method, args))
            if method == "d.hashing":
                return _scalar_text(1)
            return "<value><i4>1</i4></value>"

        with patch("hashall.rtorrent.rt_xmlrpc_call", side_effect=fake_xmlrpc), \
             patch("hashall.rtorrent.time.sleep"), \
             patch("hashall.rtorrent.time.monotonic", side_effect=[0, 0.5, 1.5, 3.0]):
            result = rt_check_and_conditionally_start(HASH, rpc_url=RPC, poll_secs=1.0)

        assert result["started"] is False
        assert result["complete"] == -1
        assert "timed out" in result["note"]


class TestApplyDirectoryRepoint:
    def test_check_before_start_false(self):
        """check_before_start=False: d.start in multicall (existing behaviour)."""
        multicall_calls = []

        def fake_multicall(calls, rpc_url=RPC, timeout=60):
            multicall_calls.extend(calls)
            return [c[0] for c in calls]

        with patch("hashall.rtorrent.rt_xmlrpc_multicall", side_effect=fake_multicall):
            result = rt_apply_directory_repoint(
                HASH, "/data/target", rpc_url=RPC, restart=True, check_before_start=False,
            )

        assert ("d.start", HASH) in multicall_calls
        assert "d.start" in result

    def test_check_before_start_true(self):
        """check_before_start=True: d.start NOT in multicall;
        rt_check_and_conditionally_start called instead."""
        multicall_calls = []

        def fake_multicall(calls, rpc_url=RPC, timeout=60):
            multicall_calls.extend(calls)
            return [c[0] for c in calls]

        with patch("hashall.rtorrent.rt_xmlrpc_multicall", side_effect=fake_multicall), \
             patch(
                 "hashall.rtorrent.rt_check_and_conditionally_start",
                 return_value={"started": True, "complete": 1, "hashing": 0, "note": "started"},
             ) as mock_safe:
            result = rt_apply_directory_repoint(
                HASH, "/data/target", rpc_url=RPC, restart=True, check_before_start=True,
            )

        assert ("d.start", HASH) not in multicall_calls
        mock_safe.assert_called_once_with(HASH, rpc_url=RPC)
        assert "check_and_start:started" in result
