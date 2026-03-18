import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "qb-libtorrent-verify.py"
SPEC = importlib.util.spec_from_file_location("qb_libtorrent_verify", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_update_stall_watch_flags_stalled_zero_progress() -> None:
    last_progress_at, last_done, last_wanted, stalled = MODULE.update_stall_watch(
        state_value=1,
        checking_files_value=1,
        done=0,
        wanted=100,
        now=10.0,
        last_progress_at=None,
        last_done=0,
        last_wanted=0,
        stalled_timeout_s=300.0,
    )

    assert stalled is False
    assert last_progress_at == 10.0
    assert last_done == 0
    assert last_wanted == 100

    _, _, _, stalled = MODULE.update_stall_watch(
        state_value=1,
        checking_files_value=1,
        done=0,
        wanted=100,
        now=311.0,
        last_progress_at=last_progress_at,
        last_done=last_done,
        last_wanted=last_wanted,
        stalled_timeout_s=300.0,
    )

    assert stalled is True


def test_update_stall_watch_resets_when_progress_moves() -> None:
    last_progress_at, last_done, last_wanted, stalled = MODULE.update_stall_watch(
        state_value=1,
        checking_files_value=1,
        done=0,
        wanted=100,
        now=10.0,
        last_progress_at=None,
        last_done=0,
        last_wanted=0,
        stalled_timeout_s=300.0,
    )

    assert stalled is False

    next_progress_at, next_done, next_wanted, stalled = MODULE.update_stall_watch(
        state_value=1,
        checking_files_value=1,
        done=50,
        wanted=100,
        now=200.0,
        last_progress_at=last_progress_at,
        last_done=last_done,
        last_wanted=last_wanted,
        stalled_timeout_s=300.0,
    )

    assert stalled is False
    assert next_progress_at == 200.0
    assert next_done == 50
    assert next_wanted == 100


def test_finalize_verify_result_promotes_instant_complete_exact_tree() -> None:
    quick = {"exact_tree": True}
    verify = {
        "verified": False,
        "verify_reason": "no_recheck_transition",
        "verify_state": "seeding",
        "verify_ratio": 1.0,
    }

    out = MODULE.finalize_verify_result(quick, verify)

    assert out["verified"] is True
    assert out["verify_reason"] == "instant_complete_without_checking_transition"


def test_finalize_verify_result_keeps_non_exact_tree_partial() -> None:
    quick = {"exact_tree": False}
    verify = {
        "verified": False,
        "verify_reason": "no_recheck_transition",
        "verify_state": "seeding",
        "verify_ratio": 1.0,
    }

    out = MODULE.finalize_verify_result(quick, verify)

    assert out["verified"] is False
    assert out["verify_reason"] == "no_recheck_transition"
