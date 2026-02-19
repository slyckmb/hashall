#!/usr/bin/env python3
"""Capture non-destructive orphan-audit + payload-auto dry-run snapshots."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _run(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _extract_json_line(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise ValueError("No JSON object found in command output")


def _extract_payload_auto_log_path(stdout: str) -> str | None:
    m = re.search(r"^\s*Log:\s*(.+)$", stdout, flags=re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _notification_subject(run_id: str, success: bool) -> str:
    status = "ok" if success else "failed"
    return f"[hashall] payload orphan snapshot {status} ({run_id})"


def _notification_body(
    *,
    run_id: str,
    captured_at: str,
    db_path: str,
    roots: list[str],
    run_dir: Path,
    orphan_json: dict | None,
    orphan_rc: int,
    payload_rc: int | None,
    review_hours: int,
    timer_unit: str,
) -> str:
    review_by = (datetime.now().astimezone() + timedelta(hours=review_hours)).strftime("%Y-%m-%dT%H:%M:%S%z")
    lines = [
        "hashall payload-orphan snapshot run summary.",
        "",
        f"run_id: {run_id}",
        f"captured_at: {captured_at}",
        f"db: {db_path}",
        f"roots: {', '.join(roots)}",
        f"snapshot_dir: {run_dir}",
        f"orphan_audit_rc: {orphan_rc}",
        f"payload_auto_dry_run_rc: {payload_rc if payload_rc is not None else 'skipped'}",
    ]

    if orphan_json:
        lines.extend(
            [
                "",
                "orphan_audit_summary:",
                f"- true_orphans={orphan_json.get('true_orphans')}",
                f"- alias_artifacts={orphan_json.get('alias_artifacts')}",
                f"- gc_tracked_true_orphans={orphan_json.get('gc_tracked_true_orphans')}",
                f"- gc_aged_true_orphans={orphan_json.get('gc_aged_true_orphans')}",
            ]
        )

    lines.extend(
        [
            "",
            f"review_by: {review_by} (within {review_hours}h)",
            "review_how:",
            f"- make payload-orphan-timer-status # includes {timer_unit}",
            f"- ls -1dt {run_dir.parent}/* | head -n 3",
            f"- cat {run_dir / 'summary.json'}",
            "",
            "disable_when:",
            "- disable if you intentionally pause orphan trend monitoring.",
            "- disable after replacing this timer with another approved monitor.",
            "disable_how:",
            "- make payload-orphan-timer-disable",
        ]
    )
    return "\n".join(lines) + "\n"


def _send_system_email(*, recipient: str, subject: str, body: str) -> tuple[bool, str]:
    if not recipient.strip():
        return False, "recipient is empty"

    sendmail = shutil.which("sendmail")
    if sendmail:
        message = f"To: {recipient}\nSubject: {subject}\n\n{body}"
        result = subprocess.run([sendmail, "-t"], input=message, text=True, capture_output=True)
        if result.returncode == 0:
            return True, f"sendmail:{sendmail}"
        err = (result.stderr or result.stdout or "").strip() or f"exit={result.returncode}"
        return False, f"sendmail failed: {err}"

    mail_bin = shutil.which("mail")
    if mail_bin:
        result = subprocess.run([mail_bin, "-s", subject, recipient], input=body, text=True, capture_output=True)
        if result.returncode == 0:
            return True, f"mail:{mail_bin}"
        err = (result.stderr or result.stdout or "").strip() or f"exit={result.returncode}"
        return False, f"mail failed: {err}"

    return False, "no system mailer found (sendmail/mail)"


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture orphan-audit + payload-auto dry-run snapshot")
    parser.add_argument("--db", default=str(Path.home() / ".hashall" / "catalog.db"))
    parser.add_argument("--roots", default="/pool/data,/stash/media,/data/media")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output-dir", default=str(Path.home() / ".logs" / "hashall" / "orphan-audit"))
    parser.add_argument("--skip-payload-auto", action="store_true", help="Skip payload-auto dry-run capture")
    args = parser.parse_args()

    roots = [r.strip() for r in args.roots.split(",") if r.strip()]
    if not roots:
        print("No roots provided")
        return 2

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}-{os.getpid()}"
    run_dir = Path(args.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    repo_src = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_src)

    orphan_cmd = [
        sys.executable,
        "-m",
        "hashall.cli",
        "payload",
        "orphan-audit",
        "--db",
        args.db,
        "--samples",
        str(args.samples),
        "--json",
    ]
    for root in roots:
        orphan_cmd.extend(["--path-prefix", root])

    orphan_result = _run(orphan_cmd, env=env)
    orphan_raw = (orphan_result.stdout or "") + (orphan_result.stderr or "")
    _write_text(run_dir / "orphan_audit_raw.txt", orphan_raw)

    orphan_json = None
    orphan_error = None
    if orphan_result.returncode == 0:
        try:
            orphan_json = _extract_json_line(orphan_result.stdout)
            _write_text(run_dir / "orphan_audit.json", json.dumps(orphan_json, indent=2, sort_keys=True) + "\n")
        except Exception as e:
            orphan_error = str(e)
    else:
        orphan_error = f"command failed rc={orphan_result.returncode}"

    payload_result = None
    payload_auto_log = None
    if not args.skip_payload_auto:
        payload_cmd = [
            sys.executable,
            str(Path(__file__).resolve().parents[0] / "payload_auto_workflow.py"),
            "--db",
            args.db,
            "--roots",
            ",".join(roots),
            "--dry-run",
        ]
        payload_result = _run(payload_cmd, env=env)
        payload_raw = (payload_result.stdout or "") + (payload_result.stderr or "")
        _write_text(run_dir / "payload_auto_dry_run.txt", payload_raw)
        payload_auto_log = _extract_payload_auto_log_path(payload_result.stdout or "")

    summary = {
        "run_id": run_id,
        "captured_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "db": args.db,
        "roots": roots,
        "orphan_audit": {
            "command": orphan_cmd,
            "rc": orphan_result.returncode,
            "error": orphan_error,
            "json": orphan_json,
            "raw_path": str(run_dir / "orphan_audit_raw.txt"),
        },
        "payload_auto_dry_run": {
            "enabled": not args.skip_payload_auto,
            "rc": None if payload_result is None else payload_result.returncode,
            "log_path": payload_auto_log,
            "raw_path": None if payload_result is None else str(run_dir / "payload_auto_dry_run.txt"),
        },
    }
    _write_text(run_dir / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")

    if _env_flag("PAYLOAD_ORPHAN_AUDIT_NOTIFY_EMAIL", default=False):
        recipient = os.environ.get("PAYLOAD_ORPHAN_AUDIT_NOTIFY_TO", "michael")
        timer_unit = os.environ.get("PAYLOAD_ORPHAN_AUDIT_TIMER_UNIT", "hashall-payload-orphan-snapshot.timer")
        try:
            review_hours = max(1, int(os.environ.get("PAYLOAD_ORPHAN_AUDIT_NOTIFY_REVIEW_HOURS", "24")))
        except ValueError:
            review_hours = 24

        success = orphan_result.returncode == 0 and (payload_result is None or payload_result.returncode == 0)
        subject = _notification_subject(run_id, success=success)
        body = _notification_body(
            run_id=run_id,
            captured_at=summary["captured_at"],
            db_path=args.db,
            roots=roots,
            run_dir=run_dir,
            orphan_json=orphan_json,
            orphan_rc=orphan_result.returncode,
            payload_rc=None if payload_result is None else payload_result.returncode,
            review_hours=review_hours,
            timer_unit=timer_unit,
        )
        email_ok, email_details = _send_system_email(recipient=recipient, subject=subject, body=body)
        if email_ok:
            print(f"Notification email sent to {recipient} ({email_details})")
        else:
            print(f"Notification email failed for {recipient}: {email_details}")

    print(f"Snapshot captured: {run_dir}")
    if orphan_json:
        print(
            "   orphan_audit: "
            f"true_orphans={orphan_json.get('true_orphans')} "
            f"alias_artifacts={orphan_json.get('alias_artifacts')} "
            f"gc_aged={orphan_json.get('gc_aged_true_orphans')}"
        )
    else:
        print(f"   orphan_audit: failed ({orphan_error})")

    if payload_result is not None:
        print(
            "   payload_auto_dry_run: "
            f"rc={payload_result.returncode} log={payload_auto_log or '-'}"
        )

    if orphan_result.returncode != 0:
        return orphan_result.returncode
    if payload_result is not None and payload_result.returncode != 0:
        return payload_result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
