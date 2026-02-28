#!/usr/bin/env python3
"""Apply verified qb-stoppeddl-drain matches into qBittorrent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import get_qbittorrent_client

SEMVER = "0.2.3"
SCRIPT_NAME = Path(__file__).name
DEFAULT_FASTRESUME_DIR = Path("/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup")
DEFAULT_QB_CONTAINER = "qbittorrent_vpn"
SAFE_STATES = {"stalledup", "uploading", "stoppedup", "queuedup", "forcedup", "checkingup"}
DANGEROUS_DOWNLOAD_STATES = {
    "downloading",
    "forceddl",
    "metadl",
    "stalleddl",
    "queueddl",
}
DEFAULT_LIVE_ALLOW_STATES = {"stoppeddl", "missingfiles", "pauseddl", "error"}


@dataclass(frozen=True)
class ApplyRow:
    torrent_hash: str
    name: str
    classification: str
    source: str
    recommended_path: str
    location: str
    verified: bool
    ratio: float


class Bencode:
    def __init__(self, blob: bytes):
        self.blob = blob
        self.i = 0

    def parse(self) -> Any:
        c = self.blob[self.i : self.i + 1]
        if c == b"i":
            self.i += 1
            j = self.blob.index(b"e", self.i)
            n = int(self.blob[self.i : j])
            self.i = j + 1
            return n
        if c == b"l":
            self.i += 1
            out: List[Any] = []
            while self.blob[self.i : self.i + 1] != b"e":
                out.append(self.parse())
            self.i += 1
            return out
        if c == b"d":
            self.i += 1
            out: Dict[bytes, Any] = {}
            while self.blob[self.i : self.i + 1] != b"e":
                k = self.parse()
                v = self.parse()
                out[k] = v
            self.i += 1
            return out
        j = self.blob.index(b":", self.i)
        n = int(self.blob[self.i : j])
        self.i = j + 1
        s = self.blob[self.i : self.i + n]
        self.i += n
        return s


def bencode(value: Any) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, str):
        b = value.encode("utf-8")
        return str(len(b)).encode("ascii") + b":" + b
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items: List[bytes] = []
        for k in sorted(
            value.keys(), key=lambda x: x if isinstance(x, bytes) else str(x).encode("utf-8")
        ):
            kb = k if isinstance(k, bytes) else str(k).encode("utf-8")
            items.append(bencode(kb))
            items.append(bencode(value[k]))
        return b"d" + b"".join(items) + b"e"
    raise TypeError(f"Unsupported type for bencode: {type(value)!r}")


def as_text(v: Any) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "ignore")
    return str(v)


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fmt_hms(seconds: float) -> str:
    total = max(0, int(seconds))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def emit_start() -> str:
    now = ts_iso()
    print(f"start ts={now} script={SCRIPT_NAME} semver={SEMVER}", flush=True)
    return now


def parse_hash_tokens(text: str) -> List[str]:
    if not text:
        return []
    for ch in ("|", ",", "\n", "\t"):
        text = text.replace(ch, " ")
    out: List[str] = []
    seen = set()
    for tok in text.split():
        h = tok.strip().lower()
        if not h or h in seen:
            continue
        seen.add(h)
        out.append(h)
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


def parse_classes(text: str) -> Set[str]:
    out = set()
    for part in str(text or "").replace("|", ",").split(","):
        c = part.strip().lower()
        if c:
            out.add(c)
    return out


def parse_states(text: str) -> Set[str]:
    out = set()
    for part in str(text or "").replace("|", ",").split(","):
        state = part.strip().lower()
        if state:
            out.add(state)
    return out


def canonical_alias(path: str) -> str:
    p = str(path or "").strip().rstrip("/")
    if not p:
        return ""
    if p == "/stash/media":
        return "/data/media"
    if p.startswith("/stash/media/"):
        return "/data/media/" + p[len("/stash/media/") :]
    if p == "/pool/data/seeds":
        return "/data/media/torrents/seeding"
    if p.startswith("/pool/data/seeds/"):
        return "/data/media/torrents/seeding/" + p[len("/pool/data/seeds/") :]
    if p == "/pool/data/cross-seed-link":
        return "/data/media/torrents/seeding/cross-seed-link"
    if p.startswith("/pool/data/cross-seed-link/"):
        return "/data/media/torrents/seeding/cross-seed-link/" + p[len("/pool/data/cross-seed-link/") :]
    if p == "/stash/media/downloads/torrents/seeding":
        return "/data/media/torrents/seeding"
    if p.startswith("/stash/media/downloads/torrents/seeding/"):
        return "/data/media/torrents/seeding/" + p[len("/stash/media/downloads/torrents/seeding/") :]
    return p


def alias_variants(path: str) -> List[str]:
    p = str(path or "").strip().rstrip("/")
    if not p:
        return []
    out = [p, canonical_alias(p)]
    if p == "/data/media" or p.startswith("/data/media/"):
        out.append("/stash/media" + p[len("/data/media") :])
    if p == "/stash/media" or p.startswith("/stash/media/"):
        out.append("/data/media" + p[len("/stash/media") :])
    if p == "/data/media/torrents/seeding" or p.startswith("/data/media/torrents/seeding/"):
        out.append("/pool/data/seeds" + p[len("/data/media/torrents/seeding") :])
        out.append("/stash/media/downloads/torrents/seeding" + p[len("/data/media/torrents/seeding") :])
    if p == "/pool/data/seeds" or p.startswith("/pool/data/seeds/"):
        out.append("/data/media/torrents/seeding" + p[len("/pool/data/seeds") :])
    if p == "/data/media/torrents/seeding/cross-seed-link" or p.startswith("/data/media/torrents/seeding/cross-seed-link/"):
        out.append("/pool/data/cross-seed-link" + p[len("/data/media/torrents/seeding/cross-seed-link") :])
    if p == "/pool/data/cross-seed-link" or p.startswith("/pool/data/cross-seed-link/"):
        out.append("/data/media/torrents/seeding/cross-seed-link" + p[len("/pool/data/cross-seed-link") :])
    seen = set()
    dedup = []
    for cand in out:
        c = cand.rstrip("/")
        if c and c not in seen:
            seen.add(c)
            dedup.append(c)
    return dedup


def resolve_existing(path: str) -> Optional[str]:
    for cand in alias_variants(path):
        if Path(cand).exists():
            return cand
    return None


def is_download_state(state: str) -> bool:
    s = str(state or "").lower()
    if not s:
        return False
    if s in SAFE_STATES:
        return False
    if s in {"stoppeddl", "pauseddl", "missingfiles", "error", "checkingdl", "checkingresumedata", "moving", "allocating"}:
        return False
    if s in DANGEROUS_DOWNLOAD_STATES:
        return True
    if s.endswith("up"):
        return False
    if "downloading" in s:
        return True
    if s.startswith("queued") and "dl" in s:
        return True
    return False


def find_latest_drain_report(bucket_dir: Path) -> Optional[Path]:
    reports_dir = bucket_dir / "reports"
    if not reports_dir.exists():
        return None
    reports = sorted(reports_dir.glob("drain-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def decide_location(recommended_path: str, name: str) -> tuple[str, str]:
    p = Path(recommended_path)
    if p.is_file():
        return str(p.parent), "recommended_is_file"
    if p.name == str(name or ""):
        return str(p.parent), "recommended_matches_name"
    return str(p), "recommended_is_dir"


def build_plan(
    drain_obj: dict,
    allow_classes: Set[str],
    allowed_hashes: Set[str],
    require_verified: bool,
    min_ratio: float,
) -> List[ApplyRow]:
    rows: List[ApplyRow] = []
    for entry in drain_obj.get("entries", []):
        h = str(entry.get("hash") or "").lower().strip()
        if not h:
            continue
        if allowed_hashes and h not in allowed_hashes:
            continue
        cls = str(entry.get("classification") or "").lower()
        if allow_classes and cls not in allow_classes:
            continue
        best = entry.get("best_result") if isinstance(entry.get("best_result"), dict) else {}
        verified = bool(best.get("verified"))
        ratio = float(best.get("verify_ratio", 0.0) or 0.0)
        if require_verified and not verified:
            continue
        if ratio < float(min_ratio):
            continue
        raw_path = str(entry.get("recommended_path") or best.get("path") or "").strip()
        if not raw_path:
            continue
        resolved = resolve_existing(raw_path)
        if not resolved:
            continue
        location, _ = decide_location(resolved, str(entry.get("name") or ""))
        rows.append(
            ApplyRow(
                torrent_hash=h,
                name=str(entry.get("name") or ""),
                classification=cls,
                source=str(entry.get("recommended_source") or "unknown"),
                recommended_path=resolved,
                location=location,
                verified=verified,
                ratio=ratio,
            )
        )
    return rows


def path_equivalent(a: str, b: str) -> bool:
    return canonical_alias(str(a or "")) == canonical_alias(str(b or ""))


def probe_fastresume(path: Path, target_location: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "exists": path.exists(),
        "parse_ok": False,
        "needs_patch": False,
        "reason": "missing",
        "save_path": "",
        "qbt_save_path": "",
        "qbt_download_path": "",
    }
    if not path.exists():
        return out
    try:
        raw = path.read_bytes()
        doc = Bencode(raw).parse()
        if not isinstance(doc, dict):
            out["reason"] = "invalid_fastresume_dict"
            return out
        save_path = as_text(doc.get(b"save_path", b"")).strip()
        qbt_save_path = as_text(doc.get(b"qBt-savePath", b"")).strip()
        qbt_download_path = as_text(doc.get(b"qBt-downloadPath", b"")).strip()
        needs_patch = False
        if not path_equivalent(save_path, target_location):
            needs_patch = True
        if not path_equivalent(qbt_save_path, target_location):
            needs_patch = True
        if qbt_download_path:
            needs_patch = True
        out.update(
            {
                "parse_ok": True,
                "needs_patch": bool(needs_patch),
                "reason": "needs_patch" if needs_patch else "already_aligned",
                "save_path": save_path,
                "qbt_save_path": qbt_save_path,
                "qbt_download_path": qbt_download_path,
            }
        )
        return out
    except Exception as e:
        out["reason"] = f"parse_error:{e}"
        return out


def patch_fastresume(path: Path, target_location: str, backup_suffix: str, apply_mode: bool) -> Tuple[bool, str, bool]:
    if not path.exists():
        return False, "missing_fastresume", False
    try:
        raw = path.read_bytes()
        doc = Bencode(raw).parse()
        if not isinstance(doc, dict):
            return False, "invalid_fastresume_dict", False
        changed = False
        target_b = str(target_location).rstrip("/").encode("utf-8")
        if doc.get(b"save_path") != target_b:
            doc[b"save_path"] = target_b
            changed = True
        if doc.get(b"qBt-savePath") != target_b:
            doc[b"qBt-savePath"] = target_b
            changed = True
        if doc.get(b"qBt-downloadPath", b"") != b"":
            doc[b"qBt-downloadPath"] = b""
            changed = True
        if not changed:
            return True, "no_change", False
        if apply_mode:
            backup = path.with_name(path.name + backup_suffix)
            if not backup.exists():
                backup.write_bytes(raw)
            path.write_bytes(bencode(doc))
        return True, "patched" if apply_mode else "would_patch", True
    except Exception as e:
        return False, f"patch_error:{e}", False


def docker_ctl(action: str, container: str) -> Tuple[bool, str]:
    if action not in {"start", "stop"}:
        return False, f"invalid_action:{action}"
    try:
        proc = subprocess.run(
            ["docker", action, container],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return True, (proc.stdout or "").strip() or "ok"
        msg = ((proc.stderr or "") + " " + (proc.stdout or "")).strip()
        return False, msg or f"docker_{action}_failed"
    except Exception as e:
        return False, str(e)


def wait_qb_online(qb: Any, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(5.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        if qb.test_connection() and qb.login():
            return True
        time.sleep(2.0)
    return False


def wait_recheck_terminal(
    qb: Any,
    torrent_hash: str,
    poll_seconds: float,
    timeout_seconds: float,
    show_progress: bool,
    progress_interval: float,
    protect_download: bool,
    item: Dict[str, Any],
) -> Tuple[str, str]:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    check_start = time.monotonic()
    max_idle = max(0.5, float(progress_interval))
    last_emit_at = 0.0
    last_emit_state = ""
    last_emit_prog = -1.0
    print(
        f"  watching poll={float(poll_seconds):.1f}s timeout={float(timeout_seconds):.1f}s",
        flush=True,
    )
    while time.monotonic() < deadline:
        info = qb.get_torrent_info(torrent_hash)
        if info is None:
            return "failed", f"postcheck_not_found:{qb.last_error or 'unknown'}"
        state = str(info.state or "").lower()
        prog = float(info.progress or 0.0)
        item["steps"].append({"step": "poll", "state": state, "progress": prog, "ts": ts_iso()})
        if show_progress:
            now = time.monotonic()
            elapsed = now - check_start
            left = max(0.0, deadline - now)
            emit = False
            if state != last_emit_state:
                emit = True
            if abs(prog - last_emit_prog) >= 0.001:
                emit = True
            if (now - last_emit_at) >= max_idle:
                emit = True
            if emit:
                print(
                    f"  poll state={state or 'unknown'} progress={prog:.6f} "
                    f"elapsed={fmt_hms(elapsed)} left={fmt_hms(left)}",
                    flush=True,
                )
                last_emit_at = now
                last_emit_state = state
                last_emit_prog = prog
        if protect_download and is_download_state(state):
            qb.pause_torrent(torrent_hash)
            return "blocked", f"entered_download_state:{state}"
        if prog >= 1.0 and state in SAFE_STATES:
            return "ok", f"seed_ready:{state}"
        time.sleep(max(0.2, float(poll_seconds)))
    return "failed", "postcheck_timeout"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Apply verified qb-stoppeddl-drain recommendations. "
            "Default auto mode: if any hash needs fastresume edits, patch whole batch offline with one qB restart; "
            "otherwise run API setLocation+recheck without waiting."
        )
    )
    p.add_argument(
        "--bucket-dir",
        default="/tmp/qb-stoppeddl-bucket-live",
        help="Bucket directory used by qb-stoppeddl tools (default: /tmp/qb-stoppeddl-bucket-live)",
    )
    p.add_argument(
        "--drain-report",
        default="",
        help="Drain report JSON path (default: latest drain-*.json in <bucket>/reports)",
    )
    p.add_argument(
        "--allow-class",
        default="a,b,c",
        help="Allowed drain classes to apply (default: a,b,c)",
    )
    p.add_argument("--hashes", default="", help="Optional explicit hashes filter")
    p.add_argument("--hashes-file", default="", help="Optional hash file filter")
    p.add_argument("--limit", type=int, default=0, help="Max rows to process (0 = all)")
    p.add_argument(
        "--require-verified",
        dest="require_verified",
        action="store_true",
        help="Only apply rows where best_result.verified=true (default: enabled)",
    )
    p.add_argument(
        "--no-require-verified",
        dest="require_verified",
        action="store_false",
        help="Allow unverified rows (not recommended)",
    )
    p.set_defaults(require_verified=True)
    p.add_argument("--min-ratio", type=float, default=1.0, help="Minimum verify ratio to apply (default: 1.0)")
    p.add_argument("--poll", type=float, default=5.0, help="qB poll interval seconds (default: 5)")
    p.add_argument("--timeout", type=float, default=1800.0, help="Per-hash poll timeout seconds (default: 1800)")
    p.add_argument(
        "--ops-mode",
        choices=("auto", "fastresume", "api"),
        default="auto",
        help="Operation mode (default: auto)",
    )
    p.add_argument(
        "--require-live-state",
        dest="require_live_state",
        action="store_true",
        help="Require hash to be in currently actionable live qB states before apply (default: enabled)",
    )
    p.add_argument(
        "--no-require-live-state",
        dest="require_live_state",
        action="store_false",
        help="Disable live-state gate (not recommended; allows stale report applies)",
    )
    p.set_defaults(require_live_state=True)
    p.add_argument(
        "--live-allow-states",
        default="stoppedDL,missingFiles,pausedDL,error",
        help="Comma-separated live qB states allowed for apply when live-state gate is enabled",
    )
    p.add_argument(
        "--fastresume-dir",
        default=str(DEFAULT_FASTRESUME_DIR),
        help=f"Directory containing <hash>.fastresume files (default: {DEFAULT_FASTRESUME_DIR})",
    )
    p.add_argument(
        "--qb-container",
        default=DEFAULT_QB_CONTAINER,
        help=f"Docker container name for qB restart in fastresume mode (default: {DEFAULT_QB_CONTAINER})",
    )
    p.add_argument(
        "--restart-timeout",
        type=float,
        default=180.0,
        help="Seconds to wait for qB API after restart (default: 180)",
    )
    p.add_argument(
        "--wait-recheck",
        dest="wait_recheck",
        action="store_true",
        help="Wait for each recheck to reach a terminal seed-ready/blocked/timeout state",
    )
    p.add_argument(
        "--no-wait-recheck",
        dest="wait_recheck",
        action="store_false",
        help="Do not wait for recheck; dispatch and continue (default)",
    )
    p.set_defaults(wait_recheck=False)
    p.add_argument(
        "--show-poll-progress",
        dest="show_poll_progress",
        action="store_true",
        help="Emit poll-state heartbeat lines during post-check wait (default: enabled)",
    )
    p.add_argument(
        "--no-show-poll-progress",
        dest="show_poll_progress",
        action="store_false",
        help="Disable poll-state heartbeat lines",
    )
    p.add_argument(
        "--progress-interval",
        type=float,
        default=10.0,
        help="Max seconds between poll heartbeat lines when state/progress is unchanged (default: 10)",
    )
    p.set_defaults(show_poll_progress=True)
    p.add_argument(
        "--protect-download",
        dest="protect_download",
        action="store_true",
        help="Pause hash if it enters download-like states during post-check (default: enabled)",
    )
    p.add_argument(
        "--no-protect-download",
        dest="protect_download",
        action="store_false",
        help="Disable download-state protection",
    )
    p.set_defaults(protect_download=True)
    p.add_argument("--apply", action="store_true", help="Execute qB actions (default: dry-run)")
    p.add_argument(
        "--report-json",
        default="",
        help="Optional apply report path (default: <bucket>/reports/apply-<ts>.json)",
    )
    p.add_argument(
        "--completion-file",
        default="",
        help=(
            "Optional completion marker JSON path "
            "(default: <bucket>/reports/apply-last-completion.json)"
        ),
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    started = emit_start()
    bucket_dir = Path(args.bucket_dir).expanduser()
    reports_dir = bucket_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    drain_path = Path(args.drain_report).expanduser() if args.drain_report else find_latest_drain_report(bucket_dir)
    if not drain_path or not drain_path.exists():
        print(f"ERROR drain_report_not_found bucket={bucket_dir}")
        return 2

    report_path = (
        Path(args.report_json).expanduser()
        if str(args.report_json or "").strip()
        else reports_dir / f"apply-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    completion_path = (
        Path(args.completion_file).expanduser()
        if str(args.completion_file or "").strip()
        else reports_dir / "apply-last-completion.json"
    )
    completion_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        drain_obj = json.loads(drain_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR drain_report_unreadable path={drain_path} error={e}")
        return 2

    allow_classes = parse_classes(args.allow_class)
    allow_hashes = set(parse_hash_tokens(args.hashes) + read_hash_file(args.hashes_file))
    plan = build_plan(
        drain_obj=drain_obj,
        allow_classes=allow_classes,
        allowed_hashes=allow_hashes,
        require_verified=bool(args.require_verified),
        min_ratio=float(args.min_ratio),
    )
    if args.limit > 0:
        plan = plan[: args.limit]

    print(
        f"plan report={drain_path} apply={bool(args.apply)} "
        f"selected={len(plan)} allow_class={','.join(sorted(allow_classes))} min_ratio={float(args.min_ratio):.4f}"
    , flush=True)

    fr_dir = Path(args.fastresume_dir).expanduser()
    fr_probe_by_hash: Dict[str, Dict[str, Any]] = {}
    fr_needed = 0
    fr_probe_errors = 0
    for row in plan:
        probe = probe_fastresume(fr_dir / f"{row.torrent_hash}.fastresume", row.location)
        fr_probe_by_hash[row.torrent_hash] = probe
        if bool(probe.get("needs_patch")):
            fr_needed += 1
        if not bool(probe.get("parse_ok")):
            fr_probe_errors += 1

    selected_mode = str(args.ops_mode or "auto").strip().lower()
    if selected_mode == "auto":
        selected_mode = "fastresume_batch" if fr_needed > 0 else "api_nowait"
    elif selected_mode == "fastresume":
        selected_mode = "fastresume_batch"
    else:
        selected_mode = "api_nowait"

    print(
        f"mode selected={selected_mode} fr_needed={fr_needed}/{len(plan)} fr_probe_errors={fr_probe_errors}",
        flush=True,
    )

    out_rows: List[dict] = []
    item_by_hash: Dict[str, Dict[str, Any]] = {}
    for row in plan:
        probe = fr_probe_by_hash.get(row.torrent_hash, {})
        item = {
            "hash": row.torrent_hash,
            "name": row.name,
            "classification": row.classification,
            "source": row.source,
            "recommended_path": row.recommended_path,
            "location": row.location,
            "verified": row.verified,
            "ratio": row.ratio,
            "fastresume_probe": probe,
            "status": "planned",
            "detail": "pending",
            "steps": [],
        }
        out_rows.append(item)
        item_by_hash[row.torrent_hash] = item

    counts = {
        "planned": len(plan),
        "applied": 0,
        "ok": 0,
        "failed": 0,
        "blocked": 0,
        "recheck_dispatched": 0,
        "skipped_live_state": 0,
        "fr_needed": fr_needed,
        "fr_patched": 0,
        "fr_patch_failed": 0,
    }

    if not args.apply:
        for item in out_rows:
            item["status"] = "planned"
            item["detail"] = f"dry_run:{selected_mode}"
        summary = {
            "mode": selected_mode,
            "planned": int(counts["planned"]),
            "applied": 0,
            "ok": 0,
            "failed": 0,
            "blocked": 0,
            "recheck_dispatched": 0,
            "skipped_live_state": 0,
            "fr_needed": int(counts["fr_needed"]),
            "fr_patched": 0,
            "fr_patch_failed": 0,
        }
    else:
        qb = get_qbittorrent_client()
        if not qb.test_connection() or not qb.login():
            print("ERROR qB connection/login failed", flush=True)
            return 2

        active_plan = list(plan)
        if bool(args.require_live_state) and active_plan:
            allowed_live_states = parse_states(args.live_allow_states)
            if not allowed_live_states:
                allowed_live_states = set(DEFAULT_LIVE_ALLOW_STATES)
            print(
                f"live_gate enabled allow_states={','.join(sorted(allowed_live_states))}",
                flush=True,
            )
            state_map = qb.get_torrents_by_hashes([row.torrent_hash for row in active_plan])
            next_plan: List[ApplyRow] = []
            for row in active_plan:
                item = item_by_hash[row.torrent_hash]
                live = state_map.get(row.torrent_hash)
                live_state = str(live.state or "").lower() if live is not None else "missing"
                live_progress = float(live.progress or 0.0) if live is not None else None
                live_amount_left = int(live.amount_left or 0) if live is not None else None
                item["live_state_gate"] = {
                    "allowed_states": sorted(allowed_live_states),
                    "live_state": live_state,
                    "live_progress": live_progress,
                    "live_amount_left": live_amount_left,
                }
                if live_state not in allowed_live_states:
                    item["status"] = "skipped_live_state"
                    item["detail"] = f"live_state_not_allowed:{live_state}"
                    counts["skipped_live_state"] += 1
                    print(
                        f"  SKIP live_state hash={row.torrent_hash[:12]} state={live_state} "
                        f"progress={live_progress if live_progress is not None else 'na'} "
                        f"amount_left={live_amount_left if live_amount_left is not None else 'na'}",
                        flush=True,
                    )
                    continue
                next_plan.append(row)
            active_plan = next_plan
            print(
                f"live_gate kept={len(active_plan)} skipped={counts['skipped_live_state']}",
                flush=True,
            )

        if not active_plan:
            print("no active hashes remain after live-state gate; nothing to apply", flush=True)
        elif selected_mode == "fastresume_batch":
            if not fr_dir.exists():
                print(f"ERROR fastresume_dir_not_found path={fr_dir}", flush=True)
                return 2
            backup_suffix = ".bak-qb-stoppeddl-apply-" + datetime.now().strftime("%Y%m%d-%H%M%S")
            print(
                f"fastresume_batch begin container={args.qb_container} dir={fr_dir} rows={len(active_plan)}",
                flush=True,
            )
            ok_stop, stop_msg = docker_ctl("stop", str(args.qb_container))
            print(
                f"qB stop status={'ok' if ok_stop else 'fail'} detail={stop_msg or 'none'}",
                flush=True,
            )
            if not ok_stop:
                for row in active_plan:
                    item = item_by_hash[row.torrent_hash]
                    item["status"] = "failed"
                    item["detail"] = f"docker_stop_failed:{stop_msg or 'unknown'}"
                counts["failed"] = len(active_plan)
            else:
                for idx, row in enumerate(active_plan, start=1):
                    item = item_by_hash[row.torrent_hash]
                    counts["applied"] += 1
                    print(
                        f"[{idx}/{len(active_plan)}] hash={row.torrent_hash[:12]} class={row.classification} ratio={row.ratio:.6f} source={row.source}",
                        flush=True,
                    )
                    print(f"  path={row.recommended_path}", flush=True)
                    print(f"  location={row.location}", flush=True)
                    fr_path = fr_dir / f"{row.torrent_hash}.fastresume"
                    ok_patch, patch_msg, changed = patch_fastresume(
                        fr_path, row.location, backup_suffix, apply_mode=True
                    )
                    item["steps"].append(
                        {
                            "step": "fastresume_patch",
                            "ok": bool(ok_patch),
                            "changed": bool(changed),
                            "path": str(fr_path),
                            "detail": patch_msg,
                        }
                    )
                    if not ok_patch:
                        item["status"] = "failed"
                        item["detail"] = patch_msg
                        counts["failed"] += 1
                        counts["fr_patch_failed"] += 1
                        print(f"  FAIL fastresume {patch_msg}", flush=True)
                        continue
                    if changed:
                        counts["fr_patched"] += 1

                ok_start, start_msg = docker_ctl("start", str(args.qb_container))
                print(
                    f"qB start status={'ok' if ok_start else 'fail'} detail={start_msg or 'none'}",
                    flush=True,
                )
                if not ok_start:
                    for row in active_plan:
                        item = item_by_hash[row.torrent_hash]
                        if item["status"] == "failed":
                            continue
                        item["status"] = "failed"
                        item["detail"] = f"docker_start_failed:{start_msg or 'unknown'}"
                        counts["failed"] += 1
                elif not wait_qb_online(qb, float(args.restart_timeout)):
                    for row in active_plan:
                        item = item_by_hash[row.torrent_hash]
                        if item["status"] == "failed":
                            continue
                        item["status"] = "failed"
                        item["detail"] = "qb_online_timeout_after_restart"
                        counts["failed"] += 1
                    print("ERROR qB API did not return after restart timeout", flush=True)
                else:
                    for row in active_plan:
                        item = item_by_hash[row.torrent_hash]
                        if item["status"] == "failed":
                            continue
                        ok_recheck = qb.recheck_torrent(row.torrent_hash)
                        item["steps"].append({"step": "recheck", "ok": bool(ok_recheck)})
                        if not ok_recheck:
                            item["status"] = "failed"
                            item["detail"] = f"recheck_failed:{qb.last_error or 'unknown'}"
                            counts["failed"] += 1
                            print(f"  FAIL recheck error={qb.last_error or 'unknown'}", flush=True)
                            continue
                        counts["recheck_dispatched"] += 1
                        if not bool(args.wait_recheck):
                            item["status"] = "queued"
                            item["detail"] = "recheck_dispatched:fastresume_batch"
                            print("  OK recheck_dispatched (no-wait)", flush=True)
                            continue
                        status, detail = wait_recheck_terminal(
                            qb=qb,
                            torrent_hash=row.torrent_hash,
                            poll_seconds=float(args.poll),
                            timeout_seconds=float(args.timeout),
                            show_progress=bool(args.show_poll_progress),
                            progress_interval=float(args.progress_interval),
                            protect_download=bool(args.protect_download),
                            item=item,
                        )
                        item["status"] = status
                        item["detail"] = detail
                        if status == "ok":
                            counts["ok"] += 1
                            print(f"  OK {detail}", flush=True)
                        elif status == "blocked":
                            counts["blocked"] += 1
                            print(f"  BLOCK {detail}", flush=True)
                        else:
                            counts["failed"] += 1
                            print(f"  FAIL {detail}", flush=True)
        else:
            for idx, row in enumerate(active_plan, start=1):
                item = item_by_hash[row.torrent_hash]
                counts["applied"] += 1
                print(
                    f"[{idx}/{len(active_plan)}] hash={row.torrent_hash[:12]} class={row.classification} ratio={row.ratio:.6f} source={row.source}",
                    flush=True,
                )
                print(f"  path={row.recommended_path}", flush=True)
                print(f"  location={row.location}", flush=True)
                ok_set = qb.set_location(row.torrent_hash, row.location)
                item["steps"].append({"step": "setLocation", "ok": bool(ok_set), "location": row.location})
                if not ok_set:
                    item["status"] = "failed"
                    item["detail"] = f"setLocation_failed:{qb.last_error or 'unknown'}"
                    counts["failed"] += 1
                    print(f"  FAIL setLocation error={qb.last_error or 'unknown'}", flush=True)
                    continue
                ok_recheck = qb.recheck_torrent(row.torrent_hash)
                item["steps"].append({"step": "recheck", "ok": bool(ok_recheck)})
                if not ok_recheck:
                    item["status"] = "failed"
                    item["detail"] = f"recheck_failed:{qb.last_error or 'unknown'}"
                    counts["failed"] += 1
                    print(f"  FAIL recheck error={qb.last_error or 'unknown'}", flush=True)
                    continue
                counts["recheck_dispatched"] += 1
                if not bool(args.wait_recheck):
                    item["status"] = "queued"
                    item["detail"] = "recheck_dispatched:api_nowait"
                    print("  OK recheck_dispatched (no-wait)", flush=True)
                    continue
                status, detail = wait_recheck_terminal(
                    qb=qb,
                    torrent_hash=row.torrent_hash,
                    poll_seconds=float(args.poll),
                    timeout_seconds=float(args.timeout),
                    show_progress=bool(args.show_poll_progress),
                    progress_interval=float(args.progress_interval),
                    protect_download=bool(args.protect_download),
                    item=item,
                )
                item["status"] = status
                item["detail"] = detail
                if status == "ok":
                    counts["ok"] += 1
                    print(f"  OK {detail}", flush=True)
                elif status == "blocked":
                    counts["blocked"] += 1
                    print(f"  BLOCK {detail}", flush=True)
                else:
                    counts["failed"] += 1
                    print(f"  FAIL {detail}", flush=True)

        summary = {
            "mode": selected_mode,
            "planned": int(counts["planned"]),
            "applied": int(counts["applied"]),
            "ok": int(counts["ok"]),
            "failed": int(counts["failed"]),
            "blocked": int(counts["blocked"]),
            "recheck_dispatched": int(counts["recheck_dispatched"]),
            "skipped_live_state": int(counts["skipped_live_state"]),
            "fr_needed": int(counts["fr_needed"]),
            "fr_patched": int(counts["fr_patched"]),
            "fr_patch_failed": int(counts["fr_patch_failed"]),
        }
    payload = {
        "tool": "qb-stoppeddl-apply",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "generated_at": started,
        "drain_report": str(drain_path),
        "bucket_dir": str(bucket_dir),
        "args": vars(args),
        "summary": summary,
        "entries": out_rows,
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    hashes_by_status: Dict[str, List[str]] = {}
    for item in out_rows:
        status = str(item.get("status") or "unknown")
        hashes_by_status.setdefault(status, []).append(str(item.get("hash") or ""))
    for status in list(hashes_by_status.keys()):
        hashes_by_status[status] = sorted(h for h in hashes_by_status[status] if h)

    completion_payload = {
        "tool": "qb-stoppeddl-apply-completion",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "completed_at": ts_iso(),
        "apply_report_json": str(report_path),
        "drain_report_json": str(drain_path),
        "bucket_dir": str(bucket_dir),
        "mode": str(summary.get("mode") or ""),
        "summary": summary,
        "hashes_by_status": hashes_by_status,
    }
    completion_path.write_text(json.dumps(completion_payload, indent=2) + "\n", encoding="utf-8")

    print(
        f"summary mode={summary.get('mode','unknown')} planned={summary['planned']} applied={summary['applied']} "
        f"dispatched={summary.get('recheck_dispatched',0)} ok={summary['ok']} failed={summary['failed']} "
        f"skipped_live_state={summary.get('skipped_live_state',0)} "
        f"blocked={summary['blocked']} fr_needed={summary.get('fr_needed',0)} "
        f"fr_patched={summary.get('fr_patched',0)} fr_patch_failed={summary.get('fr_patch_failed',0)}"
    , flush=True)
    print(f"report_json={report_path}", flush=True)
    print(f"completion_json={completion_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
