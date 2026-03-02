#!/usr/bin/env python3
"""Retag stoppedDL torrents using strict recoverable evidence from twin reports."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import get_qbittorrent_client

SEMVER = "0.1.0"
SCRIPT_NAME = Path(__file__).name


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emit_start_banner() -> str:
    now = ts_iso()
    print(f"start ts={now} script={SCRIPT_NAME} semver={SEMVER}")
    return now


def parse_states(text: str) -> Set[str]:
    out: Set[str] = set()
    for part in str(text or "").replace("|", ",").split(","):
        s = part.strip().lower()
        if s:
            out.add(s)
    return out


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


def choose_report_path(bucket_dir: Path, explicit: str) -> Path:
    if str(explicit or "").strip():
        p = Path(explicit).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"report not found: {p}")
        return p

    reports_dir = bucket_dir / "reports"
    candidates: List[Path] = []
    candidates.extend(sorted(reports_dir.glob("drain-identical-twins-*.json"), reverse=True))
    latest = reports_dir / "drain-latest.json"
    if latest.exists():
        candidates.append(latest)

    for path in candidates:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            summary = obj.get("summary") or {}
            if obj.get("progress_reason") == "final" and int(summary.get("processed", 0)) == int(summary.get("selected", 0)):
                return path
        except Exception:
            continue
    raise FileNotFoundError(f"no finalized twin/drain report found under {reports_dir}")


def is_strict_from_entry(entry: dict) -> Tuple[bool, str]:
    if bool(entry.get("strict_recoverable")):
        return True, str(entry.get("strict_recoverable_reason") or "strict_recoverable")

    cls = str(entry.get("classification") or "").lower()
    best = dict(entry.get("best_result") or {})
    ratio = float(best.get("verify_ratio", 0.0) or 0.0)
    if cls != "a":
        return False, "class_not_a"
    if not bool(best.get("verified", False)):
        return False, "not_verified"
    if not bool(best.get("exact_tree", False)):
        return False, "exact_tree_false"
    if ratio < 0.999999:
        return False, "ratio_below_1"
    if "candidate_signature_exact" in best and not bool(best.get("candidate_signature_exact")):
        return False, "candidate_signature_not_exact"
    return True, "strict_exact_twin"


def classify_group(entry: dict) -> Tuple[str, str]:
    strict, strict_reason = is_strict_from_entry(entry)
    if strict:
        return "recoverable", strict_reason
    cls = str(entry.get("classification") or "").lower()
    if cls in {"a", "b", "c"}:
        return "recoverable_weak", strict_reason
    return "not_recoverable", strict_reason


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Retag stoppedDL recoverability groups from twin report evidence.")
    p.add_argument("--bucket-dir", default="~/.cache/hashall/qb-stoppeddl-bucket")
    p.add_argument("--report-json", default="", help="Input report path (default: latest finalized twin/drain report).")
    p.add_argument("--states", default="stoppeddl", help="Only retag torrents currently in these states.")
    p.add_argument("--hashes", default="", help="Optional hash/prefix filter against report entries.")
    p.add_argument("--tag-recoverable", default="stoppeddl_recoverable")
    p.add_argument("--tag-not-recoverable", default="stoppeddl_not_recoverable")
    p.add_argument("--tag-weak", default="stoppeddl_recoverable_weak")
    p.add_argument(
        "--strict-hashes-out",
        default="",
        help="Output file with strict recoverable hashes (default: <bucket>/reports/stoppeddl-recoverable-strict-hashes.txt).",
    )
    p.add_argument(
        "--weak-hashes-out",
        default="",
        help="Output file with weak recoverable hashes (default: <bucket>/reports/stoppeddl-recoverable-weak-hashes.txt).",
    )
    p.add_argument(
        "--not-hashes-out",
        default="",
        help="Output file with not-recoverable hashes (default: <bucket>/reports/stoppeddl-not-recoverable-hashes.txt).",
    )
    p.add_argument("--apply", action="store_true", help="Apply qB tag mutations. Without this, dry-run only.")
    p.add_argument(
        "--report-out",
        default="",
        help="Output json summary path (default: <bucket>/reports/stoppeddl-retag-strict-<ts>.json).",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    started_at = emit_start_banner()

    bucket_dir = Path(args.bucket_dir).expanduser()
    reports_dir = bucket_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_in = choose_report_path(bucket_dir, args.report_json)
    report_obj = json.loads(report_in.read_text(encoding="utf-8"))
    entries = list(report_obj.get("entries") or [])
    hash_filters = set(parse_hash_tokens(args.hashes))

    strict_out = (
        Path(args.strict_hashes_out).expanduser()
        if str(args.strict_hashes_out or "").strip()
        else reports_dir / "stoppeddl-recoverable-strict-hashes.txt"
    )
    weak_out = (
        Path(args.weak_hashes_out).expanduser()
        if str(args.weak_hashes_out or "").strip()
        else reports_dir / "stoppeddl-recoverable-weak-hashes.txt"
    )
    not_out = (
        Path(args.not_hashes_out).expanduser()
        if str(args.not_hashes_out or "").strip()
        else reports_dir / "stoppeddl-not-recoverable-hashes.txt"
    )
    report_out = (
        Path(args.report_out).expanduser()
        if str(args.report_out or "").strip()
        else reports_dir / f"stoppeddl-retag-strict-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )

    tag_recoverable = str(args.tag_recoverable or "").strip()
    tag_not = str(args.tag_not_recoverable or "").strip()
    tag_weak = str(args.tag_weak or "").strip()
    mutable_tags = [t for t in [tag_recoverable, tag_not, tag_weak] if t]
    allow_states = parse_states(args.states)

    target_entries: List[dict] = []
    for e in entries:
        h = str(e.get("hash") or "").lower()
        if not h:
            continue
        if hash_filters and not any(h == f or h.startswith(f) for f in hash_filters):
            continue
        target_entries.append(e)

    hashes = sorted({str(e.get("hash") or "").lower() for e in target_entries if str(e.get("hash") or "").strip()})
    print(f"plan report={report_in} entries={len(target_entries)} hashes={len(hashes)} apply={bool(args.apply)}")

    qb = get_qbittorrent_client()
    if not qb.test_connection() or not qb.login():
        raise RuntimeError("qB connection/login failed")
    live_map = qb.get_torrents_by_hashes(hashes)

    strict_hashes: List[str] = []
    weak_hashes: List[str] = []
    not_hashes: List[str] = []
    skipped_missing = 0
    skipped_state = 0
    tag_failures = 0
    actions: List[dict] = []

    for e in target_entries:
        h = str(e.get("hash") or "").lower()
        row = live_map.get(h)
        if row is None:
            skipped_missing += 1
            actions.append({"hash": h, "status": "skip_missing_live"})
            continue
        state = str(row.state or "").lower()
        if allow_states and state not in allow_states:
            skipped_state += 1
            actions.append({"hash": h, "status": "skip_state", "state": state})
            continue

        group, reason = classify_group(e)
        desired_tags: List[str]
        if group == "recoverable":
            desired_tags = [tag_recoverable] if tag_recoverable else []
            strict_hashes.append(h)
        elif group == "recoverable_weak":
            desired_tags = [tag_weak] if tag_weak else []
            weak_hashes.append(h)
        else:
            desired_tags = [tag_not] if tag_not else []
            not_hashes.append(h)

        status = "planned"
        if bool(args.apply):
            ok_remove = qb.remove_tags(h, mutable_tags)
            ok_add = qb.add_tags(h, desired_tags) if desired_tags else True
            if not (ok_remove and ok_add):
                status = "tag_failed"
                tag_failures += 1
            else:
                status = "tagged"

        actions.append(
            {
                "hash": h,
                "name": str(row.name or ""),
                "state": state,
                "classification": str(e.get("classification") or "").lower(),
                "group": group,
                "reason": reason,
                "status": status,
                "desired_tags": desired_tags,
            }
        )
        print(
            f"hash={h[:12]} state={state} class={str(e.get('classification') or '').lower()} "
            f"group={group} status={status} reason={reason}"
        )

    strict_out.parent.mkdir(parents=True, exist_ok=True)
    weak_out.parent.mkdir(parents=True, exist_ok=True)
    not_out.parent.mkdir(parents=True, exist_ok=True)
    strict_out.write_text("\n".join(sorted(set(strict_hashes))) + ("\n" if strict_hashes else ""), encoding="utf-8")
    weak_out.write_text("\n".join(sorted(set(weak_hashes))) + ("\n" if weak_hashes else ""), encoding="utf-8")
    not_out.write_text("\n".join(sorted(set(not_hashes))) + ("\n" if not_hashes else ""), encoding="utf-8")

    out_obj = {
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "started_at": started_at,
        "finished_at": ts_iso(),
        "params": {
            "bucket_dir": str(bucket_dir),
            "report_json": str(report_in),
            "states": sorted(allow_states),
            "hash_filters": sorted(hash_filters),
            "apply": bool(args.apply),
            "tag_recoverable": tag_recoverable,
            "tag_not_recoverable": tag_not,
            "tag_weak": tag_weak,
        },
        "summary": {
            "selected_entries": len(target_entries),
            "strict_recoverable": len(sorted(set(strict_hashes))),
            "weak_recoverable": len(sorted(set(weak_hashes))),
            "not_recoverable": len(sorted(set(not_hashes))),
            "skipped_missing_live": int(skipped_missing),
            "skipped_state": int(skipped_state),
            "tag_failures": int(tag_failures),
        },
        "actions": actions,
        "strict_hashes_file": str(strict_out),
        "weak_hashes_file": str(weak_out),
        "not_hashes_file": str(not_out),
    }
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(out_obj, indent=2), encoding="utf-8")

    summary = out_obj["summary"]
    print(
        f"summary selected={summary['selected_entries']} strict={summary['strict_recoverable']} "
        f"weak={summary['weak_recoverable']} not={summary['not_recoverable']} "
        f"skipped_missing={summary['skipped_missing_live']} skipped_state={summary['skipped_state']} "
        f"tag_failures={summary['tag_failures']}"
    )
    print(f"strict_hashes_txt={strict_out}")
    print(f"weak_hashes_txt={weak_out}")
    print(f"not_hashes_txt={not_out}")
    print(f"report_json={report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
