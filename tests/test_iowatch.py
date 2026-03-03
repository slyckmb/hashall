import importlib.util
import io
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch


def _load_iowatch_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "bin" / "tools" / "iowatch"
    loader = SourceFileLoader("iowatch_module", str(script_path))
    spec = importlib.util.spec_from_loader("iowatch_module", loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_get_process_io_ignores_disappearing_proc_entries():
    mod = _load_iowatch_module()
    fake_pid_dir = Path("/proc/1594880")

    with patch.object(mod.Path, "glob", return_value=[fake_pid_dir]):
        with patch("builtins.open", side_effect=ProcessLookupError("gone")):
            assert mod.get_process_io() == {}


def test_get_process_io_parses_read_write_bytes():
    mod = _load_iowatch_module()
    fake_pid_dir = Path("/proc/4242")

    def _fake_open(path, mode="r", *args, **kwargs):
        if str(path).endswith("/io"):
            return io.StringIO("read_bytes: 123\nwrite_bytes: 456\n")
        raise FileNotFoundError(path)

    with patch.object(mod.Path, "glob", return_value=[fake_pid_dir]):
        with patch("builtins.open", side_effect=_fake_open):
            assert mod.get_process_io() == {"4242": {"read": 123, "write": 456}}
