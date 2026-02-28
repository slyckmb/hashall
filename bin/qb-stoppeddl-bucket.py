#!/usr/bin/env python3
"""Maintain a local working bucket of qB stoppedDL torrents and .torrent files."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import QBitTorrent, get_qbittorrent_client

SEMVER = "0.1.2"
SCRIPT_NAME = Path(__file__).name


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emit_start_banner() -> str:
    now = ts_iso()
    print(f"start ts={now} script={SCRIPT_NAME} semver={SEMVER}")
    return now


def parse_hash_tokens(text: str) -> List[str]:
    if not text:
        return []
    for ch in ("|", ",", "\n", "\t"):
        text = text.replace(ch, " ")
    out: List[str] = []
    seen: Set[str] = set()
    for tok in text.split():
        h = tok.strip().lower()
        if not h or h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out


def parse_states(text: str) -> Set[str]:
    out = set()
    for part in str(text or "").replace("|", ",").split(","):
        s = part.strip()
        if s:
            out.add(s.lower())
    return out


def read_hash_file(path: str) -> List[str]:
    if not path:
        return []
    p = Path(path).expanduser()
    if not p.exists():
        return []
    return parse_hash_tokens(
        " ".join(
            line
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    )


def load_existing_entries(index_path: Path) -> Dict[str, dict]:
    if not index_path.exists():
        return {}
    try:
        obj = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: Dict[str, dict] = {}
    for entry in obj.get("entries", []):
        h = str(entry.get("hash", "")).lower().strip()
        if h:
            out[h] = entry
    return out


@dataclass(frozen=True)
class SyncResult:
    exported: int
    export_failed: int
    existing: int
    skipped_export: int
    missing_in_qb: int
    pruned: int


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sync a local stoppedDL bucket and export .torrent files from qB."
    )
    p.add_argument(
        "--bucket-dir",
        default="~/.cache/hashall/qb-stoppeddl-bucket",
        help="Bucket root directory (default: ~/.cache/hashall/qb-stoppeddl-bucket)",
    )
    p.add_argument(
        "--states",
        default="stoppedDL",
        help="Comma-separated qB states to include when --hashes is not set (default: stoppedDL)",
    )
    p.add_argument(
        "--hashes",
        default="",
        help="Optional explicit hashes (pipe/comma/space separated)",
    )
    p.add_argument(
        "--hashes-file",
        default="",
        help="Optional file containing hashes (one per line, # comments allowed)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max torrents to include this run (0 = no limit)",
    )
    p.add_argument(
        "--refresh-torrents",
        action="store_true",
        help="Re-export .torrent files even if already present",
    )
    p.add_argument(
        "--no-export-torrents",
        dest="export_torrents",
        action="store_false",
        help="Do not export .torrent files (metadata sync only)",
    )
    p.set_defaults(export_torrents=True)
    p.add_argument(
        "--prune-absent",
        action="store_true",
        help="Remove entries that are no longer in the selected live set",
    )
    p.add_argument(
        "--report-json",
        default="",
        help="Optional report path (default: <bucket>/reports/sync-<ts>.json)",
    )
    return p


def fetch_torrents(explicit_hashes: List[str], states: Set[str]) -> tuple[List[QBitTorrent], int]:
    qb = get_qbittorrent_client()
    if not qb.test_connection() or not qb.login():
        raise RuntimeError("qB connection/login failed")

    missing_in_qb = 0
    rows: List[QBitTorrent]
    if explicit_hashes:
        by_hash = qb.get_torrents_by_hashes(explicit_hashes)
        rows = []
        for h in explicit_hashes:
            row = by_hash.get(h)
            if row is None:
                missing_in_qb += 1
                continue
            rows.append(row)
    else:
        all_rows = qb.get_torrents()
        rows = [r for r in all_rows if str(r.state or "").lower() in states]
    return rows, missing_in_qb


def main() -> int:
    args = build_parser().parse_args()
    now = emit_start_banner()
    bucket_dir = Path(args.bucket_dir).expanduser()
    torrents_dir = bucket_dir / "torrents"
    reports_dir = bucket_dir / "reports"
    index_path = bucket_dir / "index.json"
    hashes_path = bucket_dir / "active-hashes.txt"

    bucket_dir.mkdir(parents=True, exist_ok=True)
    torrents_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    report_path = (
        Path(args.report_json).expanduser()
        if str(args.report_json or "").strip()
        else reports_dir / f"sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    explicit_hashes = parse_hash_tokens(args.hashes)
    explicit_hashes.extend(read_hash_file(args.hashes_file))
    # Keep order, dedupe.
    explicit_hashes = list(dict.fromkeys(explicit_hashes))
    states = parse_states(args.states)
    if not explicit_hashes and not states:
        print("ERROR no states or hashes selected")
        return 2

    rows, missing_in_qb = fetch_torrents(explicit_hashes, states)
    rows.sort(key=lambda r: (str(r.name or "").lower(), str(r.hash or "").lower()))
    if args.limit > 0:
        rows = rows[: args.limit]

    existing = load_existing_entries(index_path)
    out_entries: List[dict] = []
    active_hashes: Set[str] = set()
    counts = {
        "exported": 0,
        "export_failed": 0,
        "existing": 0,
        "skipped_export": 0,
    }

    qb = get_qbittorrent_client()
    if not qb.test_connection() or not qb.login():
        print("ERROR qB connection/login failed during export stage")
        return 2

    for t in rows:
        h = str(t.hash or "").lower().strip()
        if not h:
            continue
        active_hashes.add(h)
        prior = existing.get(h, {})
        torrent_file = torrents_dir / f"{h}.torrent"
        export_status = "skipped"
        if args.export_torrents:
            if args.refresh_torrents or not torrent_file.exists():
                blob = qb.export_torrent_file(h, out_path=torrent_file)
                if blob is None:
                    export_status = "export_failed"
                    counts["export_failed"] += 1
                else:
                    export_status = "exported"
                    counts["exported"] += 1
            else:
                export_status = "existing"
                counts["existing"] += 1
        else:
            export_status = "skipped_export"
            counts["skipped_export"] += 1

        out_entries.append(
            {
                "hash": h,
                "name": str(t.name or ""),
                "state": str(t.state or ""),
                "progress": float(t.progress or 0.0),
                "size": int(t.size or 0),
                "save_path": str(t.save_path or ""),
                "content_path": str(t.content_path or ""),
                "first_seen": str(prior.get("first_seen") or now),
                "last_seen": now,
                "torrent_file": str(torrent_file),
                "torrent_file_exists": bool(torrent_file.exists()),
                "torrent_file_size": int(torrent_file.stat().st_size) if torrent_file.exists() else 0,
                "export_status": export_status,
                "stale": False,
            }
        )

    pruned = 0
    if args.prune_absent:
        pruned = sum(1 for h in existing.keys() if h not in active_hashes)
    else:
        for h, entry in existing.items():
            if h in active_hashes:
                continue
            stale = dict(entry)
            stale["stale"] = True
            stale["last_seen"] = now
            out_entries.append(stale)

    out_entries.sort(key=lambda e: (0 if not e.get("stale") else 1, str(e.get("name", "")).lower(), str(e.get("hash", ""))))
    hashes_path.write_text(
        "".join(f"{h}\n" for h in sorted(active_hashes)),
        encoding="utf-8",
    )

    index_payload = {
        "tool": "qb-stoppeddl-bucket",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "command": "sync",
        "generated_at": now,
        "bucket_dir": str(bucket_dir),
        "states": sorted(states),
        "explicit_hashes": explicit_hashes,
        "active_count": len(active_hashes),
        "total_entries": len(out_entries),
        "entries": out_entries,
    }
    index_path.write_text(json.dumps(index_payload, indent=2) + "\n", encoding="utf-8")

    result = SyncResult(
        exported=int(counts["exported"]),
        export_failed=int(counts["export_failed"]),
        existing=int(counts["existing"]),
        skipped_export=int(counts["skipped_export"]),
        missing_in_qb=int(missing_in_qb),
        pruned=int(pruned),
    )
    report_payload = {
        "tool": "qb-stoppeddl-bucket",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "command": "sync",
        "generated_at": now,
        "bucket_dir": str(bucket_dir),
        "index_json": str(index_path),
        "active_hashes_txt": str(hashes_path),
        "summary": {
            "active_count": len(active_hashes),
            "total_entries": len(out_entries),
            "exported": result.exported,
            "existing": result.existing,
            "export_failed": result.export_failed,
            "skipped_export": result.skipped_export,
            "missing_in_qb": result.missing_in_qb,
            "pruned": result.pruned,
        },
    }
    report_path.write_text(json.dumps(report_payload, indent=2) + "\n", encoding="utf-8")

    print(
        "summary "
        f"active={len(active_hashes)} total_entries={len(out_entries)} "
        f"exported={result.exported} existing={result.existing} "
        f"export_failed={result.export_failed} skipped_export={result.skipped_export} "
        f"missing_in_qb={result.missing_in_qb} pruned={result.pruned}"
    )
    print(f"index_json={index_path}")
    print(f"hashes_txt={hashes_path}")
    print(f"report_json={report_path}")
    return 0 if result.export_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
