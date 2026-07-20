import importlib.util
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pause_mirror_seeders.py"
SPEC = importlib.util.spec_from_file_location("pause_mirror_seeders", SCRIPT)
pause_mirror_seeders = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pause_mirror_seeders)


def test_paused_up_is_acceptable_for_mirror_items() -> None:
    assert not pause_mirror_seeders.is_non_acceptable_state(
        "pausedUP",
        pause_mirror_seeders.ALL_NON_ACCEPTABLE | {"pausedUP"},
    )


def test_stalled_up_is_non_acceptable_for_mirror_items() -> None:
    assert pause_mirror_seeders.is_non_acceptable_state(
        "stalledUP",
        pause_mirror_seeders.ALL_NON_ACCEPTABLE,
    )


def test_live_state_reads_post_pause_state() -> None:
    class FakeQbit:
        def get_torrent_info(self, torrent_hash):
            assert torrent_hash == "f4a6a876"
            return SimpleNamespace(state="stoppedUP")

    assert pause_mirror_seeders.live_state(FakeQbit(), "f4a6a876") == "stoppedUP"

