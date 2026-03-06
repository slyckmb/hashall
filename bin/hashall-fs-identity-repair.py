#!/usr/bin/env python3
"""Repair payload/torrent identity drift using fs_uuid-first inference."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.identity_repair import run_identity_repair, write_report

SEMVER = "0.1.1"
SCRIPT_NAME = Path(__file__).name
DEFAULT_DB = Path.home() / ".hashall" / "catalog.db"
DEFAULT_REPORT_DIR = Path.home() / ".logs" / "hashall" / "reports" / "identity-repair"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite catalog path")
    parser.add_argument("--apply", action="store_true", help="Apply updates (default is dry-run)")
    parser.add_argument(
        "--max-actions",
        type=int,
        default=0,
        help="Limit action count (0 means no limit)",
    )
    parser.add_argument(
        "--allow-bind-alias",
        dest="allow_bind_alias",
        action="store_true",
        default=True,
        help="Allow /data/media <-> /stash/media bind alias inference (default)",
    )
    parser.add_argument(
        "--no-allow-bind-alias",
        dest="allow_bind_alias",
        action="store_false",
        help="Disable bind alias inference",
    )
    parser.add_argument(
        "--report-json",
        default="",
        help="Explicit report output path. Defaults to timestamped report in report dir.",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
        help="Report directory when --report-json is omitted",
    )
    parser.add_argument("--json-output", action="store_true", help="Emit full JSON to stdout")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"error: db_not_found path={db_path}", file=sys.stderr)
        return 2

    now = _timestamp()
    print(
        f"start ts={now} script={SCRIPT_NAME} semver={SEMVER} "
        f"db={db_path} apply={str(bool(args.apply)).lower()}"
    )

    result = run_identity_repair(
        db_path,
        apply_mode=bool(args.apply),
        max_actions=max(0, int(args.max_actions or 0)),
        allow_bind_aliases=bool(args.allow_bind_alias),
    )

    report_path: Path
    if args.report_json:
        report_path = Path(args.report_json).expanduser()
    else:
        mode = "apply" if args.apply else "dryrun"
        report_path = Path(args.report_dir).expanduser() / f"identity-repair-{mode}-{now}.json"

    write_report(result, report_path)

    if args.json_output:
        print(result.to_json().rstrip())
    else:
        print(
            "summary "
            f"payload_candidates={result.payload_candidates} "
            f"torrent_candidates={result.torrent_candidates} "
            f"actions_planned={result.actions_planned} "
            f"actions_applied={result.actions_applied} "
            f"unresolved={result.unresolved_count}"
        )
        if result.reason_counts:
            print("reason_counts " + " ".join(f"{k}={v}" for k, v in result.reason_counts.items()))

    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
