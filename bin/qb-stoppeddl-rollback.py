#!/usr/bin/env python3
"""Rollback qB save locations using qb-stoppeddl-apply rollback ledger JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import get_qbittorrent_client

SCRIPT_NAME = Path(__file__).name
SEMVER = "0.1.1"
DEFAULT_LEDGER = "/tmp/qb-stoppeddl-bucket-live/reports/apply-rollback-ledger.jsonl"


@dataclass(frozen=True)
class RollbackRow:
    hash: str
    name: str
    from_save_path: str
    to_save_path: str
    action: str
    source: str
    ts: str
    raw: Dict[str, Any]


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_hash_tokens(text: str) -> List[str]:
    raw = str(text or "")
    for ch in ("|", ",", "\n", "\t"):
        raw = raw.replace(ch, " ")
    out: List[str] = []
    seen: Set[str] = set()
    for tok in raw.split():
        h = str(tok or "").strip().lower()
        if not h or h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out


def hash_matches_filters(torrent_hash: str, filters: Set[str]) -> bool:
    h = str(torrent_hash or "").strip().lower()
    if not h:
        return False
    for f in filters:
        token = str(f or "").strip().lower()
        if not token:
            continue
        if h == token or h.startswith(token):
            return True
    return False


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


def canonical_alias(path: str) -> str:
    p = str(path or "").strip().rstrip("/")
    if not p:
        return ""
    if p == "/stash/media":
        return "/data/media"
    if p.startswith("/stash/media/"):
        return "/data/media/" + p[len("/stash/media/") :]
    if p == "/stash/media/downloads/torrents/seeding":
        return "/data/media/torrents/seeding"
    if p.startswith("/stash/media/downloads/torrents/seeding/"):
        return "/data/media/torrents/seeding/" + p[len("/stash/media/downloads/torrents/seeding/") :]
    return p


def path_equivalent(a: str, b: str) -> bool:
    return canonical_alias(str(a or "")) == canonical_alias(str(b or ""))


def parse_path_list(text: str) -> List[str]:
    raw = str(text or "")
    for ch in ("|", ",", "\n", "\t"):
        raw = raw.replace(ch, " ")
    out: List[str] = []
    seen: Set[str] = set()
    for tok in raw.split():
        p = str(tok or "").strip()
        if not p:
            continue
        if p != "/" and p.endswith("/"):
            p = p.rstrip("/")
        if not p.startswith("/"):
            continue
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def is_under_root(path: str, root: str) -> bool:
    p = str(path or "").strip()
    r = str(root or "").strip()
    if not p or not r:
        return False
    if r == "/":
        return p.startswith("/")
    return p == r or p.startswith(r + "/")


def root_policy_check(path: str, allowed_roots: List[str], forbidden_roots: List[str]) -> bool:
    p = str(path or "").strip()
    if not p or not p.startswith("/"):
        return False
    for root in forbidden_roots:
        if is_under_root(p, root):
            return False
    if allowed_roots and not any(is_under_root(p, root) for root in allowed_roots):
        return False
    return True


def load_ledger(path: Path) -> List[RollbackRow]:
    rows: List[RollbackRow] = []
    if not path.exists():
        return rows
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        h = str(obj.get("hash") or "").lower().strip()
        if len(h) < 8:
            continue
        from_save = str(obj.get("from_save_path") or "").strip()
        to_save = str(obj.get("to_save_path") or "").strip()
        if not from_save.startswith("/") or not to_save.startswith("/"):
            continue
        rows.append(
            RollbackRow(
                hash=h,
                name=str(obj.get("name") or ""),
                from_save_path=from_save,
                to_save_path=to_save,
                action=str(obj.get("action") or ""),
                source=str(obj.get("source") or ""),
                ts=str(obj.get("ts") or ""),
                raw=obj if isinstance(obj, dict) else {},
            )
        )
    return rows


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Rollback qB save locations from qb-stoppeddl-apply rollback ledger JSONL. "
            "Dry-run by default."
        )
    )
    p.add_argument("--ledger", default=DEFAULT_LEDGER, help=f"Rollback ledger JSONL path (default: {DEFAULT_LEDGER})")
    p.add_argument("--hashes", default="", help="Optional explicit hashes filter")
    p.add_argument("--hashes-file", default="", help="Optional hashes file filter")
    p.add_argument("--limit", type=int, default=0, help="Max hashes to process (0 = all)")
    p.add_argument(
        "--allow-target-roots",
        default="/pool/media,/pool/data,/data/media",
        help="Comma-separated allowed roots for rollback targets (from_save_path)",
    )
    p.add_argument(
        "--forbid-target-roots",
        default="",
        help="Comma-separated forbidden roots for rollback targets",
    )
    p.add_argument(
        "--require-current-match",
        dest="require_current_match",
        action="store_true",
        help="Require current qB save_path to match ledger to_save_path before rollback (default: enabled)",
    )
    p.add_argument(
        "--no-require-current-match",
        dest="require_current_match",
        action="store_false",
        help="Disable current save-path match guard",
    )
    p.set_defaults(require_current_match=True)
    p.add_argument(
        "--recheck",
        dest="recheck",
        action="store_true",
        help="Dispatch qB recheck after successful rollback setLocation (default: enabled)",
    )
    p.add_argument(
        "--no-recheck",
        dest="recheck",
        action="store_false",
        help="Do not dispatch recheck after rollback setLocation",
    )
    p.set_defaults(recheck=True)
    p.add_argument("--apply", action="store_true", help="Execute rollback changes (default: dry-run)")
    p.add_argument("--report-json", default="", help="Optional report JSON path")
    return p


def main() -> int:
    args = build_parser().parse_args()
    started = ts_iso()
    print(f"start ts={started} script={SCRIPT_NAME} semver={SEMVER}", flush=True)

    ledger_path = Path(args.ledger).expanduser()
    report_path = (
        Path(args.report_json).expanduser()
        if str(args.report_json or "").strip()
        else ledger_path.parent / f"rollback-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)

    rows = load_ledger(ledger_path)
    allow_hashes = set(parse_hash_tokens(args.hashes) + read_hash_file(args.hashes_file))
    allowed_roots = parse_path_list(args.allow_target_roots)
    forbidden_roots = parse_path_list(args.forbid_target_roots)

    latest_by_hash: Dict[str, RollbackRow] = {}
    for row in rows:
        latest_by_hash[row.hash] = row
    selected = list(latest_by_hash.values())
    selected.sort(key=lambda r: r.hash)
    if allow_hashes:
        selected = [r for r in selected if hash_matches_filters(r.hash, allow_hashes)]
    if args.limit > 0:
        selected = selected[: args.limit]

    print(
        f"plan ledger={ledger_path} apply={bool(args.apply)} selected={len(selected)} "
        f"require_current_match={bool(args.require_current_match)} recheck={bool(args.recheck)}",
        flush=True,
    )

    out_rows: List[Dict[str, Any]] = []
    summary = {
        "selected": int(len(selected)),
        "applied": 0,
        "ok": 0,
        "failed": 0,
        "skipped_current_mismatch": 0,
        "skipped_root_policy": 0,
        "skipped_missing_torrent": 0,
    }

    qb = None
    if args.apply:
        qb = get_qbittorrent_client()
        if not qb.test_connection() or not qb.login():
            print("ERROR qB connection/login failed", flush=True)
            return 2

    for idx, row in enumerate(selected, start=1):
        item: Dict[str, Any] = {
            "hash": row.hash,
            "name": row.name,
            "from_save_path": row.from_save_path,
            "to_save_path": row.to_save_path,
            "action": row.action,
            "source": row.source,
            "status": "planned",
            "detail": "dry_run",
        }
        print(
            f"[{idx}/{len(selected)}] hash={row.hash[:12]} from={row.from_save_path} to={row.to_save_path}",
            flush=True,
        )

        if not root_policy_check(row.from_save_path, allowed_roots, forbidden_roots):
            item["status"] = "skipped_root_policy"
            item["detail"] = "target_root_blocked"
            summary["skipped_root_policy"] += 1
            out_rows.append(item)
            print("  SKIP target_root_blocked", flush=True)
            continue

        if not args.apply:
            out_rows.append(item)
            continue

        summary["applied"] += 1
        info = qb.get_torrent_info(row.hash) if qb is not None else None
        if info is None:
            item["status"] = "skipped_missing_torrent"
            item["detail"] = "missing_torrent_info"
            summary["skipped_missing_torrent"] += 1
            out_rows.append(item)
            print("  SKIP missing_torrent_info", flush=True)
            continue

        current_save = str(getattr(info, "save_path", "") or "")
        item["current_save_path"] = current_save
        if bool(args.require_current_match) and not path_equivalent(current_save, row.to_save_path):
            item["status"] = "skipped_current_mismatch"
            item["detail"] = "current_save_path_mismatch"
            summary["skipped_current_mismatch"] += 1
            out_rows.append(item)
            print(
                f"  SKIP current_mismatch current={current_save} expected_to={row.to_save_path}",
                flush=True,
            )
            continue

        ok_set = qb.set_location(row.hash, row.from_save_path)
        item["steps"] = [{"step": "setLocation", "ok": bool(ok_set), "location": row.from_save_path}]
        if not ok_set:
            item["status"] = "failed"
            item["detail"] = f"setLocation_failed:{qb.last_error or 'unknown'}"
            summary["failed"] += 1
            out_rows.append(item)
            print(f"  FAIL setLocation error={qb.last_error or 'unknown'}", flush=True)
            continue

        if bool(args.recheck):
            ok_recheck = qb.recheck_torrent(row.hash)
            item["steps"].append({"step": "recheck", "ok": bool(ok_recheck)})
            if not ok_recheck:
                item["status"] = "failed"
                item["detail"] = f"recheck_failed:{qb.last_error or 'unknown'}"
                summary["failed"] += 1
                out_rows.append(item)
                print(f"  FAIL recheck error={qb.last_error or 'unknown'}", flush=True)
                continue

        item["status"] = "ok"
        item["detail"] = "rollback_dispatched"
        summary["ok"] += 1
        out_rows.append(item)
        print("  OK rollback_dispatched", flush=True)

    payload = {
        "tool": "qb-stoppeddl-rollback",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "generated_at": started,
        "ledger": str(ledger_path),
        "args": vars(args),
        "summary": summary,
        "entries": out_rows,
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(
        f"summary selected={summary['selected']} applied={summary['applied']} ok={summary['ok']} "
        f"failed={summary['failed']} skipped_current_mismatch={summary['skipped_current_mismatch']} "
        f"skipped_root_policy={summary['skipped_root_policy']} skipped_missing_torrent={summary['skipped_missing_torrent']}",
        flush=True,
    )
    print(f"report_json={report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
