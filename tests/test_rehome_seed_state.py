from datetime import datetime, timezone
from pathlib import Path

from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.cli import cli
from rehome.seed_state import build_seed_root_state, publish_seed_root_state


def test_build_seed_root_state_surfaces_active_target_and_legacy_mirrors():
    cfg = {
        "active_root": "/stash/media",
        "default_dest_device": "pool-media",
        "default_dest_root": "/pool/media/torrents/seeding",
        "managed_roots": ["/pool/data:pool-data", "/mnt/hotspare6tb:spare"],
    }

    state = build_seed_root_state(
        cfg,
        now=datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc),
        previous_generation=7,
    )

    assert state["schema_version"] == 1
    assert state["generation"] == 8
    assert state["writer"] == "hashall"
    assert state["active"]["seeding_root"] == "/pool/media/torrents/seeding"
    assert state["target"]["seeding_root"] == "/pool/media/torrents/seeding"
    assert state["cross_seed"]["link_root"] == "/pool/media/torrents/seeding/cross-seed"
    assert state["migration"]["state"] == "in_progress"
    assert "/pool/data/media/torrents/seeding" in state["migration"]["source_roots"]
    assert "/pool/data/seeds" in state["mirror_roots"]
    assert "/data/media/torrents/seeding" in state["mirror_roots"]
    assert "/stash/media/torrents/seeding" in state["mirror_roots"]


def test_publish_seed_root_state_increments_generation(tmp_path: Path):
    path = tmp_path / "seed-root-state.json"
    cfg = {
        "active_root": "/stash/media",
        "default_dest_device": "pool-media",
        "default_dest_root": "/pool/media/torrents/seeding",
        "managed_roots": [],
    }

    _, first = publish_seed_root_state(path, cfg)
    _, second = publish_seed_root_state(path, cfg)

    assert first["generation"] == 1
    assert second["generation"] == 2
    assert path.exists()


def test_seed_root_state_cli_show_and_write(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "rehome.toml"
    config_path.write_text(
        "\n".join(
            [
                'active_device = "stash"',
                'active_root = "/stash/media"',
                'default_dest_device = "pool-media"',
                'default_dest_root = "/pool/media/torrents/seeding"',
                'managed_roots = ["/pool/data:pool-data"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "seed-root-state.json"

    monkeypatch.setattr("rehome.config.CONFIG_PATH", config_path)
    monkeypatch.setattr("rehome.seed_state.SEED_ROOT_STATE_PATH", output_path)

    runner = CliRunner()
    show_result = runner.invoke(cli, ["seed-root-state", "show", "--compact"])
    assert show_result.exit_code == 0
    assert '"writer": "hashall"' in show_result.output
    assert "/pool/media/torrents/seeding" in show_result.output

    write_result = runner.invoke(cli, ["seed-root-state", "show", "--write"])
    assert write_result.exit_code == 0
    assert "wrote seed-root-state" in write_result.output
    assert output_path.exists()
