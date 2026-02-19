"""Tests for normalize-plan CLI helpers."""

from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.cli import _build_payload_sync_command


def test_build_payload_sync_command_minimal():
    cmd = _build_payload_sync_command(
        catalog=Path("/tmp/catalog.db"),
        pool_seeding_root="/pool/data/seeds",
    )
    assert cmd[:6] == [sys.executable, "-m", "hashall.cli", "payload", "sync", "--db"]
    assert "--path-prefix" in cmd
    assert "/pool/data/seeds" in cmd
    assert "--category" not in cmd
    assert "--tag" not in cmd
    assert "--limit" not in cmd


def test_build_payload_sync_command_with_filters():
    cmd = _build_payload_sync_command(
        catalog=Path("/tmp/catalog.db"),
        pool_seeding_root="/pool/data/seeds",
        category="cross-seed",
        tag="Aither",
        limit=25,
    )
    assert "--category" in cmd
    assert "cross-seed" in cmd
    assert "--tag" in cmd
    assert "Aither" in cmd
    assert "--limit" in cmd
    assert "25" in cmd
