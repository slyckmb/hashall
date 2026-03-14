#!/usr/bin/env python3
"""Verify a qBittorrent hash against live or overridden payload paths."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hashall.qbittorrent import QBittorrentClient, QBitTorrent  # noqa: E402


SCRIPT_VERSION = "0.1.1"
SCRIPT_NAME = Path(__file__).name
VERIFY_SCRIPT = REPO_ROOT / "bin" / "qb-libtorrent-verify.py"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Look up a qB torrent by hash, export its .torrent file, derive candidate "
            "payload paths, and run qb-libtorrent-verify against them."
        )
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SCRIPT_VERSION}",
    )
    p.add_argument("hash", help="Torrent infohash to verify")
    p.add_argument(
        "--path",
        action="append",
        dest="paths",
        default=[],
        help="Extra candidate payload path to verify (repeatable)",
    )
    p.add_argument(
        "--path-map",
        action="append",
        dest="path_maps",
        default=[],
        help="Translate qB-derived paths from FROM=TO prefixes before verify (repeatable)",
    )
    p.add_argument(
        "--no-qb-paths",
        action="store_true",
        help="Do not include qB-derived candidate paths automatically",
    )
    p.add_argument(
        "--content-path-only",
        action="store_true",
        help="Only use qB content_path as the automatic candidate",
    )
    p.add_argument(
        "--save-path-only",
        action="store_true",
        help="Only use qB save_path and root-derived candidates automatically",
    )
    p.add_argument(
        "--base-url",
        default="http://localhost:9003",
        help="qB Web API base URL (default: http://localhost:9003)",
    )
    p.add_argument("--username", default="admin", help="qB username")
    p.add_argument("--password", default="adminpass", help="qB password")
    p.add_argument(
        "--torrent-out",
        default="",
        help="Optional path to keep the exported .torrent file",
    )
    p.add_argument(
        "--json-out",
        default="",
        help="Optional wrapper JSON report path",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="Max seconds per candidate verify (default: 1800)",
    )
    p.add_argument(
        "--poll",
        type=float,
        default=1.0,
        help="Status poll interval seconds (default: 1)",
    )
    p.add_argument(
        "--stalled-timeout",
        type=float,
        default=300.0,
        help="Abort if checking_files makes no progress for this many seconds (default: 300, 0 disables)",
    )
    p.add_argument(
        "--quick-only",
        action="store_true",
        help="Only do the quick tree compare (no piece hash verify)",
    )
    p.add_argument(
        "--show-progress",
        action="store_true",
        help="Pass through periodic verifier progress lines",
    )
    p.add_argument(
        "--compare-all",
        action="store_true",
        help="Return success only if every candidate verifies; default is any verified candidate",
    )
    return p


def ts_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def dedupe_keep_order(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        key = str(Path(value))
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def parse_path_maps(values: Sequence[str]) -> List[tuple[str, str]]:
    out: List[tuple[str, str]] = []
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"invalid_path_map={text!r}")
        src, dst = text.split("=", 1)
        src = src.strip()
        dst = dst.strip()
        if not src or not dst:
            raise ValueError(f"invalid_path_map={text!r}")
        out.append((src.rstrip("/"), dst.rstrip("/")))
    return out


def apply_path_maps(path: str, path_maps: Sequence[tuple[str, str]]) -> str:
    current = str(path or "")
    for src, dst in path_maps:
        if current == src or current.startswith(src + "/"):
            suffix = current[len(src):]
            return dst + suffix
    return current


def collect_candidate_paths(
    qb: QBittorrentClient,
    torrent: QBitTorrent,
    *,
    include_qb_paths: bool,
    content_path_only: bool,
    save_path_only: bool,
    extra_paths: Sequence[str],
    path_maps: Sequence[tuple[str, str]],
) -> List[str]:
    candidates: List[str] = []
    if include_qb_paths:
        root_path = qb.get_torrent_root_path(torrent)
        multi_file_root = ""
        if torrent.save_path and torrent.name:
            multi_file_root = str(Path(torrent.save_path) / torrent.name)
        if torrent.content_path and not save_path_only:
            candidates.append(apply_path_maps(str(Path(torrent.content_path)), path_maps))
        if torrent.save_path and not content_path_only:
            candidates.append(apply_path_maps(str(Path(torrent.save_path)), path_maps))
            if multi_file_root:
                candidates.append(apply_path_maps(multi_file_root, path_maps))
        if root_path and not content_path_only:
            candidates.append(apply_path_maps(str(Path(root_path)), path_maps))
    candidates.extend(str(Path(apply_path_maps(str(Path(p).expanduser()), path_maps))) for p in extra_paths)
    return dedupe_keep_order(candidates)


def export_torrent_file(
    qb: QBittorrentClient,
    torrent_hash: str,
    requested_out: str,
) -> tuple[Path, bool]:
    if requested_out:
        out_path = Path(requested_out).expanduser().resolve()
        blob = qb.export_torrent_file(torrent_hash, out_path=out_path)
        if not blob or not out_path.exists():
            raise RuntimeError(f"failed_to_export_torrent hash={torrent_hash}")
        return out_path, False

    tmpdir = Path(tempfile.mkdtemp(prefix="qb-verify-hash-"))
    out_path = tmpdir / f"{torrent_hash}.torrent"
    blob = qb.export_torrent_file(torrent_hash, out_path=out_path)
    if not blob or not out_path.exists():
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"failed_to_export_torrent hash={torrent_hash}")
    return out_path, True


def run_verifier(
    verifier_script: Path,
    torrent_file: Path,
    candidate_paths: Sequence[str],
    args: argparse.Namespace,
    verifier_json: Path,
) -> int:
    cmd = [
        sys.executable,
        str(verifier_script),
        "--torrent",
        str(torrent_file),
        "--json-out",
        str(verifier_json),
        "--timeout",
        str(float(args.timeout)),
        "--poll",
        str(float(args.poll)),
        "--stalled-timeout",
        str(float(args.stalled_timeout)),
    ]
    if args.quick_only:
        cmd.append("--quick-only")
    if args.show_progress:
        cmd.append("--show-progress")
    for candidate in candidate_paths:
        cmd.extend(["--path", str(candidate)])
    proc = subprocess.run(cmd, check=False)
    return int(proc.returncode)


def build_report(
    torrent_hash: str,
    torrent: QBitTorrent,
    candidate_paths: Sequence[str],
    verifier_report: dict,
    *,
    torrent_file: Path,
) -> dict:
    summary = verifier_report.get("summary", {}) if isinstance(verifier_report, dict) else {}
    torrent_payload = asdict(torrent) if is_dataclass(torrent) else dict(vars(torrent))
    return {
        "tool": "qb-verify-hash",
        "version": SCRIPT_VERSION,
        "hash": torrent_hash,
        "torrent": torrent_payload,
        "candidate_paths": list(candidate_paths),
        "torrent_file": str(torrent_file),
        "summary": {
            "candidate_count": len(candidate_paths),
            "best_classification": str(summary.get("best_classification") or ""),
            "best_path": str(summary.get("best_path") or ""),
            "verified_candidates": int(summary.get("verified") or 0),
            "partial_candidates": int(summary.get("partial") or 0),
        },
        "verifier_report": verifier_report,
    }


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def print_summary(report: dict) -> None:
    summary = report.get("summary", {})
    torrent = report.get("torrent", {})
    print(
        f"hash={report.get('hash')} name={torrent.get('name','')} "
        f"state={torrent.get('state','')} progress={float(torrent.get('progress', 0.0)):.4f}"
    )
    print(
        f"candidates={int(summary.get('candidate_count', 0))} "
        f"verified={int(summary.get('verified_candidates', 0))} "
        f"partial={int(summary.get('partial_candidates', 0))} "
        f"best_classification={summary.get('best_classification','')} "
        f"best_path={summary.get('best_path','')}"
    )


def determine_exit_code(verifier_rc: int, report: dict, *, compare_all: bool) -> int:
    if verifier_rc != 0 and not compare_all:
        return verifier_rc
    results = report.get("verifier_report", {}).get("results", [])
    if not compare_all:
        return 0 if int(report.get("summary", {}).get("verified_candidates", 0)) > 0 else max(verifier_rc, 1)
    if not results:
        return max(verifier_rc, 1)
    return 0 if all(bool(item.get("verified")) for item in results) else 1


def main() -> int:
    args = build_parser().parse_args()
    print(f"script={SCRIPT_NAME} version={SCRIPT_VERSION} ts={ts_now()}")
    torrent_hash = str(args.hash or "").strip().lower()
    if not torrent_hash:
        print("error=empty_hash", file=sys.stderr)
        return 2
    if args.content_path_only and args.save_path_only:
        print("error=content_path_only_conflicts_with_save_path_only", file=sys.stderr)
        return 2
    try:
        path_maps = parse_path_maps(args.path_maps)
    except ValueError as exc:
        print(f"error={exc}", file=sys.stderr)
        return 2

    qb = QBittorrentClient(
        base_url=str(args.base_url),
        username=str(args.username),
        password=str(args.password),
    )
    torrent = qb.get_torrent_info(torrent_hash)
    if torrent is None:
        print(f"error=torrent_not_found hash={torrent_hash}", file=sys.stderr)
        return 2

    candidate_paths = collect_candidate_paths(
        qb,
        torrent,
        include_qb_paths=not bool(args.no_qb_paths),
        content_path_only=bool(args.content_path_only),
        save_path_only=bool(args.save_path_only),
        extra_paths=args.paths,
        path_maps=path_maps,
    )
    if not candidate_paths:
        print(f"error=no_candidate_paths hash={torrent_hash}", file=sys.stderr)
        return 2

    torrent_file, remove_parent = export_torrent_file(qb, torrent_hash, str(args.torrent_out or ""))
    verifier_tmpdir = Path(tempfile.mkdtemp(prefix="qb-verify-hash-report-"))
    verifier_json = verifier_tmpdir / f"{torrent_hash}.json"
    try:
        verifier_rc = run_verifier(VERIFY_SCRIPT, torrent_file, candidate_paths, args, verifier_json)
        if not verifier_json.exists():
            print(f"error=missing_verifier_report path={verifier_json}", file=sys.stderr)
            return max(verifier_rc, 1)
        verifier_report = load_json(verifier_json)
        report = build_report(
            torrent_hash,
            torrent,
            candidate_paths,
            verifier_report,
            torrent_file=torrent_file,
        )
        print_summary(report)
        if args.json_out:
            out_path = Path(args.json_out).expanduser()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"report_json={out_path}")
        return determine_exit_code(verifier_rc, report, compare_all=bool(args.compare_all))
    finally:
        shutil.rmtree(verifier_tmpdir, ignore_errors=True)
        if remove_parent:
            shutil.rmtree(torrent_file.parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
