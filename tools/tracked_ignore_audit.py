#!/usr/bin/env python3
"""Review and untrack files that are already tracked but now ignored.

The cleanup action is index-only: it runs ``git rm --cached`` so files remain on
disk and future status output follows the repo's ignore rules.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


@dataclass(frozen=True)
class Suspect:
    path: str
    category: str
    action: str
    reason: str


def run_git(repo_root: Path, args: Sequence[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
    )


def repo_root_from(path: Path) -> Path:
    result = run_git(path, ["rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip())


def tracked_ignored(repo_root: Path) -> List[str]:
    result = run_git(repo_root, ["ls-files", "-ci", "--exclude-standard"])
    return [line for line in result.stdout.splitlines() if line.strip()]


def classify(path: str, include_legacy_jobs: bool) -> Suspect:
    if path.startswith("briefs/"):
        return Suspect(
            path=path,
            category="chatrap-session-brief",
            action="clean",
            reason="session-scoped generated brief under ignored briefs/",
        )
    if path.startswith("docs/briefs/"):
        return Suspect(
            path=path,
            category="legacy-doc-brief",
            action="clean",
            reason="generated task brief under ignored docs/briefs/",
        )
    if path.startswith("jobs/"):
        return Suspect(
            path=path,
            category="legacy-job-artifact",
            action="clean" if include_legacy_jobs else "review",
            reason="ignored jobs/ artifact; opt in to cleanup with --include-legacy-jobs",
        )
    return Suspect(
        path=path,
        category="unknown",
        action="review",
        reason="ignored tracked file not covered by a cleanup rule",
    )


def batched(items: Sequence[str], size: int = 100) -> Iterable[Sequence[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def apply_cleanup(repo_root: Path, paths: Sequence[str]) -> None:
    for chunk in batched(paths):
        run_git(repo_root, ["rm", "--cached", "--", *chunk])


def print_table(suspects: Sequence[Suspect]) -> None:
    if not suspects:
        print("No tracked ignored files found.")
        return

    width = max(len(item.category) for item in suspects)
    print(f"{'ACTION':<7}  {'CATEGORY':<{width}}  PATH")
    print(f"{'-' * 7}  {'-' * width}  {'-' * 4}")
    for item in suspects:
        print(f"{item.action:<7}  {item.category:<{width}}  {item.path}")

    totals = {}
    for item in suspects:
        totals[item.action] = totals.get(item.action, 0) + 1
    summary = ", ".join(f"{key}={totals[key]}" for key in sorted(totals))
    print(f"\nsummary: total={len(suspects)}, {summary}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review tracked files that match .gitignore and optionally untrack safe generated artifacts.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="path inside the git repo to audit (default: current directory)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="run git rm --cached for files classified with action=clean",
    )
    parser.add_argument(
        "--include-legacy-jobs",
        action="store_true",
        help="also untrack ignored files under jobs/; default is review-only",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        repo_root = repo_root_from(Path(args.repo_root).resolve())
    except subprocess.CalledProcessError as exc:
        print(exc.stderr.strip() or "not inside a git repository", file=sys.stderr)
        return 2

    suspects = [classify(path, args.include_legacy_jobs) for path in tracked_ignored(repo_root)]
    clean_paths = [item.path for item in suspects if item.action == "clean"]

    if args.apply and clean_paths:
        apply_cleanup(repo_root, clean_paths)
        suspects = [classify(path, args.include_legacy_jobs) for path in tracked_ignored(repo_root)]

    if args.json:
        payload = {
            "repo_root": str(repo_root),
            "applied": bool(args.apply),
            "cleaned_count": len(clean_paths) if args.apply else 0,
            "suspects": [asdict(item) for item in suspects],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if args.apply:
            print(f"cleaned: {len(clean_paths)} tracked ignored file(s)")
        print_table(suspects)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
