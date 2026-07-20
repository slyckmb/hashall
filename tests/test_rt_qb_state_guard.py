import importlib.util
from argparse import Namespace
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "rt-qb-state-guard.py"


def load_script():
    spec = importlib.util.spec_from_file_location("rt_qb_state_guard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def args(**kwargs):
    base = {
        "allowed_rt_hash": [],
        "allowed_qb_hash": [],
        "max_checking": -1,
    }
    base.update(kwargs)
    return Namespace(**base)


def snapshot(qb_active=None, qb_stoppeddl=None, qb_checking=None, rt_non_ideal=None, rt_missing=None):
    return {
        "qb": {
            "active": qb_active or [],
            "stoppeddl": qb_stoppeddl or [],
            "checking": qb_checking or [],
        },
        "rt": {
            "non_ideal": rt_non_ideal or [],
            "missing_dirs": rt_missing or [],
        },
    }


def row(hash_, state="stalledUP"):
    return {"hash": hash_, "name": hash_, "state": state}


def test_compare_detects_new_qb_active():
    mod = load_script()
    base = snapshot()
    current = snapshot(qb_active=[row("a" * 40, "stalledUP")])

    report = mod.compare(base, current, args())

    assert report["status"] == "fail"
    assert report["issues"][0]["type"] == "new_qb_active"


def test_compare_allows_named_qb_hash():
    mod = load_script()
    h = "b" * 40
    base = snapshot()
    current = snapshot(qb_active=[row(h, "stalledUP")])

    report = mod.compare(base, current, args(allowed_qb_hash=[h]))

    assert report["status"] == "pass"


def test_compare_detects_new_rt_non_ideal():
    mod = load_script()
    h = "c" * 40
    base = snapshot()
    current = snapshot(rt_non_ideal=[row(h, "stoppedDL")])

    report = mod.compare(base, current, args())

    assert report["status"] == "fail"
    assert report["issues"][0]["type"] == "new_rt_non_ideal"


def test_compare_detects_new_rt_missing_dir():
    mod = load_script()
    h = "d" * 40
    base = snapshot()
    current = snapshot(rt_missing=[{**row(h, "stalledUP"), "session_directory": "/missing"}])

    report = mod.compare(base, current, args())

    assert report["status"] == "fail"
    assert report["issues"][0]["type"] == "new_rt_missing_dir"


def test_compare_detects_checking_limit():
    mod = load_script()
    base = snapshot()
    current = snapshot(qb_checking=[row("e" * 40, "checkingUP")])

    report = mod.compare(base, current, args(max_checking=0))

    assert report["status"] == "fail"
    assert report["issues"][0]["type"] == "qb_checking_above_limit"
