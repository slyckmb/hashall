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


def test_env_flag_handles_common_truthy_values(monkeypatch):
    monkeypatch.setenv("PAYLOAD_ORPHAN_AUDIT_NOTIFY_EMAIL", "yes")
    assert module._env_flag("PAYLOAD_ORPHAN_AUDIT_NOTIFY_EMAIL") is True


def test_notification_body_includes_review_and_disable_guidance(tmp_path):
    body = module._notification_body(
        run_id="run123",
        captured_at="2026-02-12T11:00:00-0500",
        db_path="/home/michael/.hashall/catalog.db",
        roots=["/pool/data", "/stash/media", "/data/media"],
        run_dir=tmp_path / "run123",
        orphan_json={
            "true_orphans": 10,
            "alias_artifacts": 2,
            "gc_tracked_true_orphans": 4,
            "gc_aged_true_orphans": 1,
        },
        orphan_rc=0,
        payload_rc=0,
        review_hours=24,
        timer_unit="hashall-payload-orphan-snapshot.timer",
    )

    assert "review_by:" in body
    assert "make payload-orphan-timer-status" in body
    assert "make payload-orphan-timer-disable" in body
    assert "true_orphans=10" in body


def test_send_system_email_reports_missing_mailer(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)

    ok, details = module._send_system_email(
        recipient="michael",
        subject="test",
        body="body",
    )
    assert ok is False
    assert "no system mailer" in details
