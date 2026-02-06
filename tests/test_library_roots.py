from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rehome.library_roots import (
    parse_cross_seed_data_dirs,
    parse_tracker_registry_save_paths,
)


def test_parse_cross_seed_data_dirs(tmp_path: Path) -> None:
    config_path = tmp_path / "config.js"
    config_path.write_text(
        """
module.exports = {
  dataDirs: [
    "/data/one",
    // "/data/skip",
    "/data/two", // trailing comment
    "/data/three",
  ],
};
""".lstrip()
    )

    roots = parse_cross_seed_data_dirs(config_path)
    assert roots == ["/data/one", "/data/two", "/data/three"]


def test_parse_tracker_registry_save_paths(tmp_path: Path) -> None:
    registry_path = tmp_path / "tracker-registry.yml"
    registry_path.write_text(
        """
version: 1
trackers:
  alpha:
    qbittorrent:
      category: alpha
      save_path: /data/alpha
  beta:
    qbittorrent:
      save_path: "/data/beta"
  gamma:
    cross_seed:
      enabled: true
""".lstrip()
    )

    roots = parse_tracker_registry_save_paths(registry_path)
    assert roots == ["/data/alpha", "/data/beta"]
