from importlib.machinery import SourceFileLoader
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module(path: Path, name: str):
    return SourceFileLoader(name, str(path)).load_module()


def test_identical_twins_parser_exposes_verify_heartbeat() -> None:
    mod = _load_module(
        REPO_ROOT / "bin" / "qb-stoppeddl-find-identical-twins.py",
        "qb_stoppeddl_identical_twins_mod",
    )
    args = mod.build_parser().parse_args([])
    assert int(args.verify_heartbeat) == 30
