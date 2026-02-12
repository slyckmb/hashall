#!/usr/bin/env python3
"""Capture non-destructive orphan-audit + payload-auto dry-run snapshots."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
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
        print("❌ No roots provided")
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

    print(f"✅ Snapshot captured: {run_dir}")
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
