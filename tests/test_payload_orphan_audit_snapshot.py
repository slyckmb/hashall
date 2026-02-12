"""Tests for payload orphan audit snapshot helper script."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "payload_orphan_audit_snapshot.py"


spec = importlib.util.spec_from_file_location("payload_orphan_audit_snapshot", SCRIPT_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_extract_json_line_parses_last_json_object():
    stdout = "line1\n{\"true_orphans\": 1}\n"
    parsed = module._extract_json_line(stdout)
    assert parsed["true_orphans"] == 1


def test_extract_json_line_raises_without_json():
    with pytest.raises(ValueError):
        module._extract_json_line("no json here\n")


def test_extract_payload_auto_log_path():
    stdout = "Automated payload workflow\n  Log: /tmp/hashall/payload-auto/run.jsonl\n"
    assert module._extract_payload_auto_log_path(stdout) == "/tmp/hashall/payload-auto/run.jsonl"
