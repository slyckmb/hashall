#!/usr/bin/env python3
"""Apply verified qb-stoppeddl-drain matches into qBittorrent."""

from __future__ import annotations

import argparse
import json
import os
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
from rehome.seed_state import SEED_ROOT_STATE_PATH, validate_seed_root_state

SEMVER = "0.2.11"
SCRIPT_NAME = Path(__file__).name
DEFAULT_FASTRESUME_DIR = Path("/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup")
DEFAULT_QB_CONTAINER = "qbittorrent_vpn"
DEFAULT_ALLOWED_SAVE_ROOTS = "/pool/media,/pool/data"
DEFAULT_FORBID_SAVE_ROOTS = "/data/media,/stash/media"
DEFAULT_ROLLBACK_LEDGER_NAME = "apply-rollback-ledger.jsonl"
DEFAULT_GUARD_RECHECK_ALLOWLIST = Path("/tmp/qb-stoppeddl-bucket-live/guard-recheck-allowlist.json")
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


@dataclass(frozen=True)
class BuildPlanResult:
    rows: List[ApplyRow]
    root_policy_rejected: List[Dict[str, str]]


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


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, sort_keys=False) + "\n")


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


def _dedupe_paths(paths: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for value in paths:
        p = str(value or "").strip()
        if not p:
            continue
        if p != "/" and p.endswith("/"):
            p = p.rstrip("/")
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def load_seed_root_policy(path: Path) -> Dict[str, List[str]]:
    state = json.loads(path.read_text(encoding="utf-8"))
    validate_seed_root_state(state)
    candidate_roots: List[str] = []
    target = str((state.get("target") or {}).get("seeding_root") or "").strip()
    if target.startswith("/pool/"):
        candidate_roots.append(target)
    migration = state.get("migration") or {}
    for root in migration.get("source_roots") or []:
        root_s = str(root or "").strip()
        if root_s.startswith("/pool/"):
            candidate_roots.append(root_s)
    allowed = _dedupe_paths(candidate_roots)
    if not allowed:
        raise ValueError(f"seed-root-state {path} did not yield any pool-backed roots")
    return {"allowed_save_roots": allowed}


def is_under_root(path: str, root: str) -> bool:
    p = str(path or "").strip()
    r = str(root or "").strip()
    if not p or not r:
        return False
    if r == "/":
        return p.startswith("/")
    return p == r or p.startswith(r + "/")


def root_policy_check(path: str, allowed_roots: List[str], forbidden_roots: List[str]) -> Tuple[bool, str]:
    p = str(path or "").strip()
    if not p or not p.startswith("/"):
        return False, "path_not_absolute"
    for root in forbidden_roots:
        if is_under_root(p, root):
            return False, f"forbidden_root:{root}"
    if allowed_roots and not any(is_under_root(p, root) for root in allowed_roots):
        return False, "outside_allowed_roots"
    return True, "ok"


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
        out.append("/stash/media/downloads/torrents/seeding" + p[len("/data/media/torrents/seeding") :])
    if p == "/stash/media/downloads/torrents/seeding" or p.startswith("/stash/media/downloads/torrents/seeding/"):
        out.append("/data/media/torrents/seeding" + p[len("/stash/media/downloads/torrents/seeding") :])
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


def _first_existing_parent(path: str) -> Optional[Path]:
    p = Path(str(path or "").strip())
    if not str(p):
        return None
    try:
        if p.exists():
            return p
    except OSError:
        pass
    for cand in p.parents:
        # Falling all the way back to "/" hides missing mount roots and can
        # incorrectly mark unrelated filesystems as equivalent.
        if str(cand) == "/":
            break
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return None


def _device_id_for_path(path: str) -> Optional[int]:
    cand = _first_existing_parent(path)
    if cand is None:
        return None
    try:
        return int(os.stat(str(cand)).st_dev)
    except OSError:
        return None


def _storage_root_label(path: str) -> str:
    p = canonical_alias(path)
    if p.startswith("/pool/"):
        return "pool"
    if p.startswith("/data/"):
        return "data"
    if p.startswith("/stash/"):
        return "stash"
    return "other"


def same_filesystem_paths(source_path: str, target_path: str) -> Tuple[bool, str]:
    """
    Conservative filesystem gate:
      - Prefer direct st_dev equality when both sides can be stat'ed.
      - Fallback to top-level storage-root family equality.
    """
    source = str(source_path or "").strip()
    target = str(target_path or "").strip()
    if not source:
        return False, "missing_source_path"
    if not target:
        return False, "missing_target_path"
    src_dev = _device_id_for_path(source)
    dst_dev = _device_id_for_path(target)
    if src_dev is not None and dst_dev is not None:
        if src_dev == dst_dev:
            return True, "device_match"
        return False, f"device_mismatch:{src_dev}!={dst_dev}"
    src_root = _storage_root_label(source)
    dst_root = _storage_root_label(target)
    if src_root == dst_root:
        return True, f"storage_root_fallback:{src_root}"
    return False, f"storage_root_mismatch:{src_root}!={dst_root}"


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
    allowed_roots: List[str],
    forbidden_roots: List[str],
) -> BuildPlanResult:
    rows: List[ApplyRow] = []
    rejected: List[Dict[str, str]] = []
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
        # Safety gate: for single-file torrents, candidate basename must match
        # torrent name exactly. This blocks same-size false positives.
        expected_files = int(best.get("expected_files", 0) or 0)
        if expected_files == 1:
            torrent_name = Path(str(entry.get("name") or "")).name
            candidate_name = Path(raw_path).name
            if torrent_name and candidate_name and candidate_name != torrent_name:
                continue
        resolved = resolve_existing(raw_path)
        if not resolved:
            continue
        location, _ = decide_location(resolved, str(entry.get("name") or ""))
        ok_path, reason_path = root_policy_check(resolved, allowed_roots, forbidden_roots)
        ok_loc, reason_loc = root_policy_check(location, allowed_roots, forbidden_roots)
        if not ok_path or not ok_loc:
            rejected.append(
                {
                    "hash": h,
                    "name": str(entry.get("name") or ""),
                    "recommended_path": resolved,
                    "location": location,
                    "reason": reason_path if not ok_path else reason_loc,
                }
            )
            continue
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
    return BuildPlanResult(rows=rows, root_policy_rejected=rejected)


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


def detect_gradual_daemons() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return out
    if proc.returncode != 0:
        return out
    for raw in str(proc.stdout or "").splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid, args = parts[0].strip(), parts[1].strip()
        if "qbit-start-seeding-gradual.sh" not in args:
            continue
        if "--daemon" not in args:
            continue
        out.append(
            {
                "pid": pid,
                "args": args,
                "guard_only": "true" if "--guard-only" in args else "false",
            }
        )
    return out


def update_guard_recheck_allowlist(
    allowlist_path: Path,
    *,
    add_hash: str = "",
    remove_hash: str = "",
    ttl_seconds: int = 0,
) -> Tuple[bool, str, int]:
    try:
        now = int(time.time())
        state: Dict[str, int] = {}
        if allowlist_path.exists():
            try:
                obj = json.loads(allowlist_path.read_text(encoding="utf-8"))
            except Exception:
                obj = {}
            if isinstance(obj, dict):
                for k, v in obj.items():
                    h = str(k or "").strip().lower()
                    if len(h) != 40:
                        continue
                    try:
                        exp = int(v)
                    except Exception:
                        continue
                    if exp > now:
                        state[h] = exp
        added_expiry = 0
        add_h = str(add_hash or "").strip().lower()
        rem_h = str(remove_hash or "").strip().lower()
        if add_h:
            ttl = max(1, int(ttl_seconds))
            added_expiry = now + ttl
            state[add_h] = added_expiry
        if rem_h:
            state.pop(rem_h, None)
        state = {k: int(v) for k, v in state.items() if int(v) > now}
        allowlist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = allowlist_path.with_suffix(allowlist_path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(allowlist_path)
        if add_h:
            return True, "added", int(added_expiry)
        if rem_h:
            return True, "removed", 0
        return True, "ok", 0
    except Exception as e:
        return False, f"allowlist_update_error:{e}", 0


def wait_recheck_terminal(
    qb: Any,
    torrent_hash: str,
    poll_seconds: float,
    timeout_seconds: float,
    show_progress: bool,
    progress_interval: float,
    protect_download: bool,
    transient_miss_retries: int,
    item: Dict[str, Any],
    guard_daemon_active: bool = False,
) -> Tuple[str, str]:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    check_start = time.monotonic()
    max_idle = max(0.5, float(progress_interval))
    allowed_transient_misses = max(0, int(transient_miss_retries))
    transient_miss_count = 0
    last_emit_at = 0.0
    last_emit_state = ""
    last_emit_prog = -1.0
    seen_checking = False
    print(
        f"  watching poll={float(poll_seconds):.1f}s timeout={float(timeout_seconds):.1f}s",
        flush=True,
    )
    while time.monotonic() < deadline:
        info = qb.get_torrent_info(torrent_hash)
        if info is None:
            transient_miss_count += 1
            err = str(qb.last_error or "unknown")
            item["steps"].append(
                {
                    "step": "poll_missing",
                    "error": err,
                    "attempt": transient_miss_count,
                    "allowed": allowed_transient_misses,
                    "ts": ts_iso(),
                }
            )
            if transient_miss_count <= allowed_transient_misses:
                if show_progress:
                    print(
                        f"  poll missing transient attempt={transient_miss_count}/{allowed_transient_misses} "
                        f"error={err}",
                        flush=True,
                    )
                time.sleep(max(0.2, float(poll_seconds)))
                continue
            return "failed", f"postcheck_not_found_after_retries:{err}"
        transient_miss_count = 0
        state = str(info.state or "").lower()
        prog = float(info.progress or 0.0)
        item["steps"].append({"step": "poll", "state": state, "progress": prog, "ts": ts_iso()})
        if state in {"checkingdl", "checkingup", "checkingresumedata"}:
            seen_checking = True
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
        if guard_daemon_active and seen_checking and state == "stoppeddl" and prog < 1.0:
            item["steps"].append(
                {
                    "step": "guard_interference_suspected",
                    "state": state,
                    "progress": prog,
                    "ts": ts_iso(),
                }
            )
            return "failed", "interrupted_recheck:guard_daemon_active"
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
    p.add_argument(
        "--allowed-save-roots",
        default="",
        help=(
            "Comma-separated absolute save roots allowed for recommended paths/locations "
            "(default: seed-root-state pool roots, else built-in safe defaults)"
        ),
    )
    p.add_argument(
        "--seed-root-state",
        default=str(SEED_ROOT_STATE_PATH),
        help=(
            "Path to hashall seed-root-state.json used to derive safe save roots "
            "(default: ~/.hashall/seed-root-state.json)"
        ),
    )
    p.add_argument(
        "--no-seed-root-state",
        dest="use_seed_root_state",
        action="store_false",
        help="Do not derive default save-root policy from seed-root-state.json",
    )
    p.set_defaults(use_seed_root_state=True)
    p.add_argument(
        "--forbid-save-roots",
        default=DEFAULT_FORBID_SAVE_ROOTS,
        help=(
            "Comma-separated absolute save roots blocked for recommended paths/locations "
            f"(default: {DEFAULT_FORBID_SAVE_ROOTS})"
        ),
    )
    p.add_argument(
        "--fail-on-root-violations",
        dest="fail_on_root_violations",
        action="store_true",
        help="Abort apply when drain rows violate root policy (default: enabled)",
    )
    p.add_argument(
        "--no-fail-on-root-violations",
        dest="fail_on_root_violations",
        action="store_false",
        help="Do not abort apply when root-policy violations are present",
    )
    p.set_defaults(fail_on_root_violations=True)
    p.add_argument(
        "--enforce-same-filesystem",
        dest="enforce_same_filesystem",
        action="store_true",
        help="Block apply actions that cross filesystems/storage roots (default: enabled)",
    )
    p.add_argument(
        "--no-enforce-same-filesystem",
        dest="enforce_same_filesystem",
        action="store_false",
        help="Allow cross-filesystem apply actions (dangerous)",
    )
    p.set_defaults(enforce_same_filesystem=True)
    p.add_argument(
        "--ignore-hashes",
        default="",
        help="Optional hashes/prefixes to ignore (pipe/comma/space separated)",
    )
    p.add_argument(
        "--ignore-hashes-file",
        default="",
        help=(
            "Optional ignore hash file (one per line, # comments allowed). "
            "If omitted, <bucket>/download-whitelist-hashes.txt is used when present."
        ),
    )
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
        "--fail-if-guard-daemon",
        dest="fail_if_guard_daemon",
        action="store_true",
        help="Abort apply when qbit-start-seeding-gradual daemon is running (default: enabled)",
    )
    p.add_argument(
        "--allow-guard-daemon",
        dest="fail_if_guard_daemon",
        action="store_false",
        help="Allow apply while qbit-start-seeding-gradual daemon is active (not recommended)",
    )
    p.set_defaults(fail_if_guard_daemon=True)
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
        help="Do not wait for recheck; dispatch and continue (not recommended)",
    )
    p.set_defaults(wait_recheck=True)
    p.add_argument(
        "--guard-allowlist-file",
        default=str(DEFAULT_GUARD_RECHECK_ALLOWLIST),
        help=(
            "JSON TTL map used to exempt active repair rechecks from guard daemon stop logic "
            f"(default: {DEFAULT_GUARD_RECHECK_ALLOWLIST})"
        ),
    )
    p.add_argument(
        "--guard-allowlist-ttl",
        type=int,
        default=1800,
        help="Seconds to keep per-hash guard allowlist entries during recheck waits (default: 1800)",
    )
    p.add_argument(
        "--guard-allowlist",
        dest="guard_allowlist_enabled",
        action="store_true",
        help="Enable guard allowlist registration around recheck operations (default: enabled)",
    )
    p.add_argument(
        "--no-guard-allowlist",
        dest="guard_allowlist_enabled",
        action="store_false",
        help="Disable guard allowlist registration during apply",
    )
    p.set_defaults(guard_allowlist_enabled=True)
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
    p.add_argument(
        "--transient-miss-retries",
        type=int,
        default=6,
        help="Consecutive get_torrent_info misses tolerated during wait-recheck (default: 6)",
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
    p.add_argument(
        "--rollback-ledger",
        default="",
        help=(
            "Optional rollback ledger JSONL path "
            "(default: <bucket>/reports/" + DEFAULT_ROLLBACK_LEDGER_NAME + ")"
        ),
    )
    p.add_argument(
        "--rollback-ledger-enabled",
        dest="rollback_ledger_enabled",
        action="store_true",
        help="Write rollback ledger entries on apply mutations (default: enabled)",
    )
    p.add_argument(
        "--no-rollback-ledger",
        dest="rollback_ledger_enabled",
        action="store_false",
        help="Disable rollback ledger writes",
    )
    p.set_defaults(rollback_ledger_enabled=True)
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
    rollback_ledger_path = (
        Path(args.rollback_ledger).expanduser()
        if str(args.rollback_ledger or "").strip()
        else reports_dir / DEFAULT_ROLLBACK_LEDGER_NAME
    )
    rollback_ledger_enabled = bool(args.rollback_ledger_enabled)
    rollback_ledger_written = 0
    guard_allowlist_path = (
        Path(args.guard_allowlist_file).expanduser()
        if str(args.guard_allowlist_file or "").strip()
        else DEFAULT_GUARD_RECHECK_ALLOWLIST
    )
    guard_allowlist_ttl = max(0, int(args.guard_allowlist_ttl))
    guard_allowlist_enabled = bool(args.guard_allowlist_enabled) and guard_allowlist_ttl > 0

    def append_rollback_entry(entry: Dict[str, Any]) -> None:
        nonlocal rollback_ledger_written
        if not bool(args.apply):
            return
        if not rollback_ledger_enabled:
            return
        try:
            append_jsonl(rollback_ledger_path, entry)
            rollback_ledger_written += 1
        except Exception as e:
            print(f"WARN rollback_ledger_write_failed path={rollback_ledger_path} error={e}", flush=True)

    def guard_allowlist_add(torrent_hash: str, item: Dict[str, Any]) -> bool:
        if not bool(args.apply):
            return False
        if not guard_allowlist_enabled:
            return False
        ok, detail, expires = update_guard_recheck_allowlist(
            guard_allowlist_path,
            add_hash=torrent_hash,
            ttl_seconds=guard_allowlist_ttl,
        )
        item["steps"].append(
            {
                "step": "guard_allowlist_add",
                "ok": bool(ok),
                "path": str(guard_allowlist_path),
                "ttl_seconds": int(guard_allowlist_ttl),
                "expires_epoch": int(expires),
                "detail": detail,
            }
        )
        if not ok:
            print(
                f"WARN guard_allowlist_add_failed hash={torrent_hash[:12]} path={guard_allowlist_path} detail={detail}",
                flush=True,
            )
            return False
        return True

    def guard_allowlist_remove(torrent_hash: str, item: Dict[str, Any], reason: str) -> None:
        if not bool(args.apply):
            return
        if not guard_allowlist_enabled:
            return
        ok, detail, _ = update_guard_recheck_allowlist(
            guard_allowlist_path,
            remove_hash=torrent_hash,
        )
        item["steps"].append(
            {
                "step": "guard_allowlist_remove",
                "ok": bool(ok),
                "path": str(guard_allowlist_path),
                "reason": str(reason or ""),
                "detail": detail,
            }
        )
        if not ok:
            print(
                f"WARN guard_allowlist_remove_failed hash={torrent_hash[:12]} path={guard_allowlist_path} detail={detail}",
                flush=True,
            )

    try:
        drain_obj = json.loads(drain_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR drain_report_unreadable path={drain_path} error={e}")
        return 2

    allow_classes = parse_classes(args.allow_class)
    seed_root_policy: Dict[str, List[str]] = {}
    seed_root_state_path = Path(args.seed_root_state).expanduser()
    if bool(args.use_seed_root_state) and seed_root_state_path.exists():
        try:
            seed_root_policy = load_seed_root_policy(seed_root_state_path)
            print(
                "seed_root_policy "
                f"path={seed_root_state_path} "
                f"allowed_save_roots={','.join(seed_root_policy['allowed_save_roots'])}"
            )
        except Exception as exc:
            print(f"WARN seed_root_policy_unusable path={seed_root_state_path} detail={exc}")
    allowed_roots = parse_path_list(args.allowed_save_roots) or seed_root_policy.get(
        "allowed_save_roots", parse_path_list(DEFAULT_ALLOWED_SAVE_ROOTS)
    )
    forbidden_roots = parse_path_list(args.forbid_save_roots)
    allow_hashes = set(parse_hash_tokens(args.hashes) + read_hash_file(args.hashes_file))
    default_ignore_file = bucket_dir / "download-whitelist-hashes.txt"
    ignore_hashes = parse_hash_tokens(args.ignore_hashes)
    if str(args.ignore_hashes_file or "").strip():
        ignore_hashes.extend(read_hash_file(args.ignore_hashes_file))
    elif default_ignore_file.exists():
        ignore_hashes.extend(read_hash_file(str(default_ignore_file)))
    ignore_hashes = list(dict.fromkeys(ignore_hashes))
    ignore_set = set(ignore_hashes)
    plan_result = build_plan(
        drain_obj=drain_obj,
        allow_classes=allow_classes,
        allowed_hashes=allow_hashes,
        require_verified=bool(args.require_verified),
        min_ratio=float(args.min_ratio),
        allowed_roots=allowed_roots,
        forbidden_roots=forbidden_roots,
    )
    plan = list(plan_result.rows)
    root_policy_rejected = list(plan_result.root_policy_rejected)
    ignored_plan = 0
    if ignore_set:
        before_ignore = len(plan)
        plan = [row for row in plan if not hash_matches_filters(row.torrent_hash, ignore_set)]
        ignored_plan = max(0, before_ignore - len(plan))
    if args.limit > 0:
        plan = plan[: args.limit]

    print(
        f"plan report={drain_path} apply={bool(args.apply)} "
        f"selected={len(plan)} allow_class={','.join(sorted(allow_classes))} min_ratio={float(args.min_ratio):.4f} "
        f"ignored={ignored_plan} root_policy_rejected={len(root_policy_rejected)} "
        f"allowed_roots={','.join(allowed_roots) if allowed_roots else '<none>'} "
        f"forbidden_roots={','.join(forbidden_roots) if forbidden_roots else '<none>'}"
    , flush=True)
    print(f"filesystem_gate enforce_same_filesystem={bool(args.enforce_same_filesystem)}", flush=True)
    if root_policy_rejected:
        print("root_policy_rejections:", flush=True)
        for rec in root_policy_rejected[:20]:
            print(
                f"  hash={str(rec.get('hash') or '')[:12]} reason={rec.get('reason','unknown')} "
                f"location={rec.get('location','')}",
                flush=True,
            )
        if len(root_policy_rejected) > 20:
            print(f"  ... {len(root_policy_rejected) - 20} more", flush=True)
    if bool(args.apply) and bool(args.fail_on_root_violations) and root_policy_rejected:
        payload = {
            "tool": "qb-stoppeddl-apply",
            "script": SCRIPT_NAME,
            "semver": SEMVER,
            "generated_at": started,
            "drain_report": str(drain_path),
            "bucket_dir": str(bucket_dir),
            "ignored_hashes": ignore_hashes,
            "ignore_hashes_file": str(Path(args.ignore_hashes_file).expanduser()) if str(args.ignore_hashes_file or "").strip() else (str(default_ignore_file) if default_ignore_file.exists() else ""),
            "args": vars(args),
            "summary": {
                "mode": "root_policy_blocked",
                "planned": int(len(plan)),
                "applied": 0,
                "ok": 0,
                "failed": 0,
                "blocked": 0,
                "same_filesystem_blocked": 0,
                "recheck_dispatched": 0,
                "skipped_live_state": 0,
                "skipped_ignored": int(ignored_plan),
                "fr_needed": 0,
                "fr_patched": 0,
                "fr_patch_failed": 0,
                "root_policy_rejected": int(len(root_policy_rejected)),
                "rollback_ledger_written": int(rollback_ledger_written),
                "guard_daemon_detected": 0,
            },
            "root_policy": {
                "allowed_roots": allowed_roots,
                "forbidden_roots": forbidden_roots,
                "rejected": root_policy_rejected,
            },
            "rollback_ledger": {
                "enabled": bool(rollback_ledger_enabled),
                "path": str(rollback_ledger_path),
                "written": int(rollback_ledger_written),
            },
            "guard_daemon": {
                "detected": 0,
                "records": [],
            },
            "guard_allowlist": {
                "enabled": bool(guard_allowlist_enabled),
                "path": str(guard_allowlist_path),
                "ttl_seconds": int(guard_allowlist_ttl),
            },
            "entries": [],
        }
        report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print("ERROR root_policy_violations_detected; refusing to apply", flush=True)
        print(f"report_json={report_path}", flush=True)
        return 4

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

    selected_ops = str(args.ops_mode or "auto").strip().lower()
    if selected_ops == "auto":
        selected_ops = "fastresume_batch" if fr_needed > 0 else "api"
    elif selected_ops == "fastresume":
        selected_ops = "fastresume_batch"
    else:
        selected_ops = "api"
    selected_mode = f"{selected_ops}_{'wait' if bool(args.wait_recheck) else 'nowait'}"

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
        "same_filesystem_blocked": 0,
        "recheck_dispatched": 0,
        "skipped_live_state": 0,
        "skipped_ignored": int(ignored_plan),
        "fr_needed": fr_needed,
        "fr_patched": 0,
        "fr_patch_failed": 0,
        "root_policy_rejected": int(len(root_policy_rejected)),
        "rollback_ledger_written": 0,
        "guard_daemon_detected": 0,
    }
    guard_daemons: List[Dict[str, str]] = []

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
            "same_filesystem_blocked": 0,
            "recheck_dispatched": 0,
            "skipped_live_state": 0,
            "skipped_ignored": int(counts["skipped_ignored"]),
            "fr_needed": int(counts["fr_needed"]),
            "fr_patched": 0,
            "fr_patch_failed": 0,
            "root_policy_rejected": int(counts["root_policy_rejected"]),
            "rollback_ledger_written": int(counts["rollback_ledger_written"]),
            "guard_daemon_detected": int(counts["guard_daemon_detected"]),
        }
    else:
        guard_daemons = detect_gradual_daemons()
        counts["guard_daemon_detected"] = int(len(guard_daemons))
        guard_daemon_active = bool(guard_daemons)
        guard_preflight_blocked = bool(guard_daemon_active and args.fail_if_guard_daemon)
        if guard_daemon_active:
            print(
                f"guard_daemon detected count={len(guard_daemons)} fail_if_guard_daemon={bool(args.fail_if_guard_daemon)}",
                flush=True,
            )
            for rec in guard_daemons[:20]:
                print(
                    f"  guard pid={rec.get('pid','?')} guard_only={rec.get('guard_only','false')} args={rec.get('args','')}",
                    flush=True,
                )
            if len(guard_daemons) > 20:
                print(f"  ... {len(guard_daemons) - 20} more", flush=True)

        if guard_preflight_blocked:
            for item in out_rows:
                item["status"] = "blocked"
                item["detail"] = "guard_daemon_running"
                item["steps"].append(
                    {
                        "step": "preflight_guard_daemon",
                        "ok": False,
                        "detail": "guard_daemon_running",
                    }
                )
            counts["blocked"] = len(out_rows)
            counts["rollback_ledger_written"] = int(rollback_ledger_written)
            summary = {
                "mode": "guard_daemon_blocked",
                "planned": int(counts["planned"]),
                "applied": 0,
                "ok": 0,
                "failed": 0,
                "blocked": int(counts["blocked"]),
                "same_filesystem_blocked": int(counts["same_filesystem_blocked"]),
                "recheck_dispatched": 0,
                "skipped_live_state": 0,
                "skipped_ignored": int(counts["skipped_ignored"]),
                "fr_needed": int(counts["fr_needed"]),
                "fr_patched": 0,
                "fr_patch_failed": 0,
                "root_policy_rejected": int(counts["root_policy_rejected"]),
                "rollback_ledger_written": int(counts["rollback_ledger_written"]),
                "guard_daemon_detected": int(counts["guard_daemon_detected"]),
            }
        else:
            qb = get_qbittorrent_client()
            if not qb.test_connection() or not qb.login():
                print("ERROR qB connection/login failed", flush=True)
                return 2

            active_plan = list(plan)
            state_map: Dict[str, Any] = {}
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
            elif selected_ops == "fastresume_batch":
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
                        fr_save_path = str(item.get("fastresume_probe", {}).get("save_path") or "")
                        if bool(args.enforce_same_filesystem):
                            same_ok, same_reason = same_filesystem_paths(fr_save_path, row.location)
                            item["same_filesystem_gate"] = {
                                "enforced": True,
                                "source_path": fr_save_path,
                                "target_path": row.location,
                                "ok": bool(same_ok),
                                "reason": same_reason,
                            }
                            if not same_ok:
                                item["status"] = "blocked"
                                item["detail"] = f"same_filesystem_blocked:{same_reason}"
                                counts["blocked"] += 1
                                counts["same_filesystem_blocked"] += 1
                                print(f"  BLOCK same_filesystem {same_reason}", flush=True)
                                continue
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
                            append_rollback_entry(
                                {
                                    "ts": ts_iso(),
                                    "run_started_at": started,
                                    "tool": SCRIPT_NAME,
                                    "semver": SEMVER,
                                    "action": "fastresume_patch",
                                    "mode": selected_mode,
                                    "hash": row.torrent_hash,
                                    "name": row.name,
                                    "classification": row.classification,
                                    "source": row.source,
                                    "from_save_path": str(item.get("fastresume_probe", {}).get("save_path") or ""),
                                    "to_save_path": row.location,
                                    "drain_report": str(drain_path),
                                    "apply_report_json": str(report_path),
                                    "detail": str(patch_msg or ""),
                                }
                            )

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
                            allowlist_registered = guard_allowlist_add(row.torrent_hash, item)
                            ok_recheck = qb.recheck_torrent(row.torrent_hash)
                            item["steps"].append({"step": "recheck", "ok": bool(ok_recheck)})
                            if not ok_recheck:
                                if allowlist_registered:
                                    guard_allowlist_remove(row.torrent_hash, item, "recheck_failed")
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
                                transient_miss_retries=int(args.transient_miss_retries),
                                item=item,
                                guard_daemon_active=bool(guard_daemon_active),
                            )
                            if allowlist_registered:
                                guard_allowlist_remove(row.torrent_hash, item, "wait_recheck_terminal")
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
                    live = state_map.get(row.torrent_hash)
                    if live is None:
                        live = qb.get_torrent_info(row.torrent_hash)
                    current_save_path = str(getattr(live, "save_path", "") or "")
                    if bool(args.enforce_same_filesystem):
                        same_ok, same_reason = same_filesystem_paths(current_save_path, row.location)
                        item["same_filesystem_gate"] = {
                            "enforced": True,
                            "source_path": current_save_path,
                            "target_path": row.location,
                            "ok": bool(same_ok),
                            "reason": same_reason,
                        }
                        if not same_ok:
                            item["status"] = "blocked"
                            item["detail"] = f"same_filesystem_blocked:{same_reason}"
                            counts["blocked"] += 1
                            counts["same_filesystem_blocked"] += 1
                            print(f"  BLOCK same_filesystem {same_reason}", flush=True)
                            continue
                    if current_save_path and path_equivalent(current_save_path, row.location):
                        item["steps"].append(
                            {
                                "step": "setLocation",
                                "ok": True,
                                "location": row.location,
                                "from_save_path": current_save_path,
                                "skipped": True,
                                "reason": "already_aligned",
                            }
                        )
                        print("  setLocation skipped: already aligned", flush=True)
                    else:
                        ok_set = qb.set_location(row.torrent_hash, row.location)
                        item["steps"].append(
                            {
                                "step": "setLocation",
                                "ok": bool(ok_set),
                                "location": row.location,
                                "from_save_path": current_save_path,
                            }
                        )
                        if not ok_set:
                            item["status"] = "failed"
                            item["detail"] = f"setLocation_failed:{qb.last_error or 'unknown'}"
                            counts["failed"] += 1
                            print(f"  FAIL setLocation error={qb.last_error or 'unknown'}", flush=True)
                            continue
                        append_rollback_entry(
                            {
                                "ts": ts_iso(),
                                "run_started_at": started,
                                "tool": SCRIPT_NAME,
                                "semver": SEMVER,
                                "action": "set_location",
                                "mode": selected_mode,
                                "hash": row.torrent_hash,
                                "name": row.name,
                                "classification": row.classification,
                                "source": row.source,
                                "from_save_path": current_save_path,
                                "to_save_path": row.location,
                                "drain_report": str(drain_path),
                                "apply_report_json": str(report_path),
                            }
                        )
                    allowlist_registered = guard_allowlist_add(row.torrent_hash, item)
                    ok_recheck = qb.recheck_torrent(row.torrent_hash)
                    item["steps"].append({"step": "recheck", "ok": bool(ok_recheck)})
                    if not ok_recheck:
                        if allowlist_registered:
                            guard_allowlist_remove(row.torrent_hash, item, "recheck_failed")
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
                        transient_miss_retries=int(args.transient_miss_retries),
                        item=item,
                        guard_daemon_active=bool(guard_daemon_active),
                    )
                    if allowlist_registered:
                        guard_allowlist_remove(row.torrent_hash, item, "wait_recheck_terminal")
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

        if not guard_preflight_blocked:
            counts["rollback_ledger_written"] = int(rollback_ledger_written)
            summary = {
                "mode": selected_mode,
                "planned": int(counts["planned"]),
                "applied": int(counts["applied"]),
                "ok": int(counts["ok"]),
                "failed": int(counts["failed"]),
                "blocked": int(counts["blocked"]),
                "same_filesystem_blocked": int(counts["same_filesystem_blocked"]),
                "recheck_dispatched": int(counts["recheck_dispatched"]),
                "skipped_live_state": int(counts["skipped_live_state"]),
                "skipped_ignored": int(counts["skipped_ignored"]),
                "fr_needed": int(counts["fr_needed"]),
                "fr_patched": int(counts["fr_patched"]),
                "fr_patch_failed": int(counts["fr_patch_failed"]),
                "root_policy_rejected": int(counts["root_policy_rejected"]),
                "rollback_ledger_written": int(counts["rollback_ledger_written"]),
                "guard_daemon_detected": int(counts["guard_daemon_detected"]),
            }
    payload = {
        "tool": "qb-stoppeddl-apply",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "generated_at": started,
        "drain_report": str(drain_path),
        "bucket_dir": str(bucket_dir),
        "ignored_hashes": ignore_hashes,
        "ignore_hashes_file": str(Path(args.ignore_hashes_file).expanduser()) if str(args.ignore_hashes_file or "").strip() else (str(default_ignore_file) if default_ignore_file.exists() else ""),
        "args": vars(args),
        "summary": summary,
        "root_policy": {
            "allowed_roots": allowed_roots,
            "forbidden_roots": forbidden_roots,
            "rejected": root_policy_rejected,
        },
        "rollback_ledger": {
            "enabled": bool(rollback_ledger_enabled),
            "path": str(rollback_ledger_path),
            "written": int(rollback_ledger_written),
        },
        "guard_daemon": {
            "detected": int(len(guard_daemons)),
            "records": guard_daemons,
        },
        "guard_allowlist": {
            "enabled": bool(guard_allowlist_enabled),
            "path": str(guard_allowlist_path),
            "ttl_seconds": int(guard_allowlist_ttl),
        },
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
        "rollback_ledger": {
            "enabled": bool(rollback_ledger_enabled),
            "path": str(rollback_ledger_path),
            "written": int(rollback_ledger_written),
        },
        "guard_daemon": {
            "detected": int(len(guard_daemons)),
            "records": guard_daemons,
        },
        "guard_allowlist": {
            "enabled": bool(guard_allowlist_enabled),
            "path": str(guard_allowlist_path),
            "ttl_seconds": int(guard_allowlist_ttl),
        },
        "hashes_by_status": hashes_by_status,
    }
    completion_path.write_text(json.dumps(completion_payload, indent=2) + "\n", encoding="utf-8")

    print(
        f"summary mode={summary.get('mode','unknown')} planned={summary['planned']} applied={summary['applied']} "
        f"dispatched={summary.get('recheck_dispatched',0)} ok={summary['ok']} failed={summary['failed']} "
        f"skipped_live_state={summary.get('skipped_live_state',0)} "
        f"skipped_ignored={summary.get('skipped_ignored',0)} "
        f"blocked={summary['blocked']} fr_needed={summary.get('fr_needed',0)} "
        f"same_filesystem_blocked={summary.get('same_filesystem_blocked',0)} "
        f"fr_patched={summary.get('fr_patched',0)} fr_patch_failed={summary.get('fr_patch_failed',0)} "
        f"root_policy_rejected={summary.get('root_policy_rejected',0)} "
        f"rollback_ledger_written={summary.get('rollback_ledger_written',0)} "
        f"guard_daemon_detected={summary.get('guard_daemon_detected',0)}"
    , flush=True)
    print(f"report_json={report_path}", flush=True)
    print(f"completion_json={completion_path}", flush=True)
    if bool(args.apply) and rollback_ledger_enabled:
        print(f"rollback_ledger_jsonl={rollback_ledger_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
