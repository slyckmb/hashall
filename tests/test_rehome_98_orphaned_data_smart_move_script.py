import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "rehome-98_orphaned-data-smart-move.sh"


def _mk_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_phase_98_dryrun_does_not_move_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"

    _mk_file(src / "a" / "leaf1" / "f1.bin", 16)
    _mk_file(src / "b" / "leaf2" / "f2.bin", 32)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--source",
            str(src),
            "--dest",
            str(dst),
            "--dryrun",
            "--reserve-gib",
            "0",
            "--order",
            "small-first",
            "--output-prefix",
            "t98-dryrun",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "action=dryrun_move" in result.stdout
    assert (src / "a" / "leaf1" / "f1.bin").exists()
    assert (src / "b" / "leaf2" / "f2.bin").exists()
    assert not (dst / "a" / "leaf1" / "f1.bin").exists()


def test_phase_98_apply_moves_whole_leaf_folders(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"

    _mk_file(src / "show" / "s1" / "ep1.mkv", 20)
    _mk_file(src / "show" / "s1" / "ep2.mkv", 20)
    _mk_file(src / "movie" / "m1" / "file.mkv", 20)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--source",
            str(src),
            "--dest",
            str(dst),
            "--apply",
            "--reserve-gib",
            "0",
            "--order",
            "input",
            "--output-prefix",
            "t98-apply",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "action=move" in result.stdout
    assert (dst / "show" / "s1" / "ep1.mkv").exists()
    assert (dst / "show" / "s1" / "ep2.mkv").exists()
    assert (dst / "movie" / "m1" / "file.mkv").exists()
    assert not (src / "show" / "s1" / "ep1.mkv").exists()
    assert not (src / "movie" / "m1" / "file.mkv").exists()


def test_phase_98_space_guard_skips_when_budget_too_low(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"

    _mk_file(src / "big" / "leaf" / "blob.bin", 1024)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--source",
            str(src),
            "--dest",
            str(dst),
            "--dryrun",
            "--reserve-gib",
            "999999",
            "--output-prefix",
            "t98-space",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "action=skip_space" in result.stdout
