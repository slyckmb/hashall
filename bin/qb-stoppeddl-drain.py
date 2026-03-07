#!/usr/bin/env python3
"""Analyze and classify stoppedDL bucket items using offline libtorrent verification."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import QBittorrentClient, QBitTorrent, get_qbittorrent_client
from rehome.seed_state import SEED_ROOT_STATE_PATH, validate_seed_root_state

SEMVER = "0.1.24"
SCRIPT_NAME = Path(__file__).name
DEFAULT_ALLOWED_SAVE_ROOTS = "/pool/media,/pool/data"
DEFAULT_FORBID_SAVE_ROOTS = "/data/media,/stash/media"
DEFAULT_ALLOWED_DONOR_ROOTS = "/pool/media,/pool/data,/data/media"
DEFAULT_FORBID_DONOR_ROOTS = "/stash/media"


TRUSTED_STATES = {"stalledup", "uploading", "stoppedup", "queuedup", "checkingup", "forcedup", "pausedup"}
LIVE_CHECKING_STATES = {"checkingdl", "checkingup", "checkingresumedata"}
LIVE_SEED_READY_STATES = {"stalledup", "uploading", "stoppedup", "queuedup", "forcedup", "pausedup"}

# Common scene/release noise terms that inflate weak name matches.
SCENE_NOISE_TOKENS = {
    "web",
    "webrip",
    "webdl",
    "bluray",
    "bdrip",
    "remux",
    "x264",
    "x265",
    "h264",
    "h265",
    "hevc",
    "avc",
    "hd",
    "uhd",
    "sd",
    "dts",
    "truehd",
    "atmos",
    "aac",
    "ac3",
    "dd",
    "ddp",
    "ma",
    "hdr",
    "hybrid",
    "proper",
    "repack",
    "internal",
    "limited",
    "extended",
    "unrated",
    "complete",
    "season",
    "multi",
    "subs",
    "sub",
    "dual",
    "audio",
    "amzn",
    "nf",
    "hmax",
    "dsnp",
    "hulu",
    "atvp",
    "appletv",
    "framestor",
    "epsilon",
    "privatehd",
    "flux",
    "ntb",
}


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


def _dedupe_paths(paths: Iterable[str]) -> List[str]:
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
    return {
        "allowed_save_roots": allowed,
        "allowed_donor_roots": list(allowed),
    }


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


def storage_root_label(path: str) -> str:
    p = canonical_alias(path)
    if p.startswith("/pool/"):
        return "pool"
    if p.startswith("/data/"):
        return "data"
    if p.startswith("/stash/"):
        return "stash"
    return "other"


def donor_affinity_score(path: str, target_save_path: str) -> float:
    p = canonical_alias(path)
    t = canonical_alias(target_save_path)
    if not p or not t:
        return 0.0
    score = 0.0
    p_root = storage_root_label(p)
    t_root = storage_root_label(t)
    if p_root == t_root:
        score += 25.0
    if t.startswith("/pool/") and p.startswith("/pool/"):
        score += 10.0
    if t.startswith("/data/") and p.startswith("/data/"):
        score += 10.0
    p_parts = [x for x in p.strip("/").split("/") if x]
    t_parts = [x for x in t.strip("/").split("/") if x]
    common_parts = 0
    for a, b in zip(p_parts, t_parts):
        if a != b:
            break
        common_parts += 1
    score += float(min(common_parts, 8))
    return score


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
    lines = [
        line
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return parse_hash_tokens(" ".join(lines))


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


def compact_path(path: str, max_len: int = 84) -> str:
    raw = str(path or "")
    if len(raw) <= max_len:
        return raw
    keep = max(16, max_len - 3)
    return "..." + raw[-keep:]


def normalize_name(text: str) -> str:
    base = str(text or "").strip().lower()
    if not base:
        return ""
    # Keep alnum only; collapse separators so near-equivalent names compare well.
    cleaned = re.sub(r"[^a-z0-9]+", " ", base)
    return " ".join(cleaned.split())


def is_meaningful_token(tok: str) -> bool:
    t = str(tok or "").strip().lower()
    if len(t) < 2:
        return False
    if t in SCENE_NOISE_TOKENS:
        return False
    if re.fullmatch(r"\d{3,4}p", t):
        return False
    if re.fullmatch(r"[xh]\d{3,4}", t):
        return False
    if re.fullmatch(r"\d+", t):
        # Keep years, drop other raw numeric tokens.
        try:
            n = int(t)
            return 1900 <= n <= 2099
        except Exception:
            return False
    if t.startswith(("dts", "ddp", "dd", "aac", "ac3", "truehd", "atmos", "h264", "h265", "x264", "x265")):
        return False
    return True


def tokenize_name(text: str) -> Tuple[str, ...]:
    norm = normalize_name(text)
    if not norm:
        return ()
    return tuple(tok for tok in norm.split(" ") if is_meaningful_token(tok))


@dataclass(frozen=True)
class GlobalDbPath:
    path: str
    source: str
    owner_hash: str
    basename: str
    basename_norm: str
    tokens: Tuple[str, ...]


@dataclass(frozen=True)
class GlobalDbIndex:
    all_paths: Tuple[GlobalDbPath, ...]
    by_basename: Dict[str, Tuple[GlobalDbPath, ...]]
    by_norm: Dict[str, Tuple[GlobalDbPath, ...]]
    by_token: Dict[str, Tuple[GlobalDbPath, ...]]


def load_global_db_index(conn: sqlite3.Connection) -> GlobalDbIndex:
    rows = conn.execute(
        """
        SELECT lower(coalesce(ti.torrent_hash, '')) AS torrent_hash,
               ti.save_path AS ti_save_path,
               ti.root_name AS ti_root_name,
               p.root_path AS payload_root_path
          FROM torrent_instances ti
          LEFT JOIN payloads p ON p.payload_id = ti.payload_id
         WHERE (p.root_path IS NOT NULL AND p.root_path != '')
            OR (
                ti.save_path IS NOT NULL AND ti.save_path != ''
                AND ti.root_name IS NOT NULL AND ti.root_name != ''
            )
        """
    ).fetchall()

    # Prefer payload-root sourced paths over save+root derived paths for the same canonical path.
    best_by_path: Dict[str, Tuple[int, GlobalDbPath]] = {}

    def maybe_add(path: str, source: str, owner_hash: str) -> None:
        resolved = resolve_existing_path(path)
        if not resolved:
            return
        canonical = canonical_alias(resolved)
        if not canonical:
            return
        base = Path(canonical).name.strip()
        if not base:
            return
        rec = GlobalDbPath(
            path=canonical,
            source=source,
            owner_hash=str(owner_hash or "").lower(),
            basename=base,
            basename_norm=normalize_name(base),
            tokens=tokenize_name(base),
        )
        priority = 2 if source == "db_global_payload_root" else 1
        prior = best_by_path.get(canonical)
        if prior is None or priority > prior[0]:
            best_by_path[canonical] = (priority, rec)

    for row in rows:
        owner_hash = str(row["torrent_hash"] or "").lower()
        payload_root = str(row["payload_root_path"] or "").strip()
        ti_save = str(row["ti_save_path"] or "").strip()
        ti_root = str(row["ti_root_name"] or "").strip()
        if payload_root:
            maybe_add(payload_root, "db_global_payload_root", owner_hash)
        if ti_save and ti_root:
            maybe_add(str(Path(ti_save) / ti_root), "db_global_save_root", owner_hash)

    all_paths = [item[1] for item in best_by_path.values()]
    by_basename: Dict[str, List[GlobalDbPath]] = defaultdict(list)
    by_norm: Dict[str, List[GlobalDbPath]] = defaultdict(list)
    by_token: Dict[str, List[GlobalDbPath]] = defaultdict(list)
    for rec in all_paths:
        by_basename[rec.basename.lower()].append(rec)
        if rec.basename_norm:
            by_norm[rec.basename_norm].append(rec)
        for tok in rec.tokens:
            by_token[tok].append(rec)

    return GlobalDbIndex(
        all_paths=tuple(all_paths),
        by_basename={k: tuple(v) for k, v in by_basename.items()},
        by_norm={k: tuple(v) for k, v in by_norm.items()},
        by_token={k: tuple(v) for k, v in by_token.items()},
    )


def add_global_db_candidates(
    cands: Dict[str, Candidate],
    index: GlobalDbIndex,
    torrent_hash: str,
    torrent_name: str,
    max_add: int,
) -> int:
    if not torrent_name:
        return 0

    target_hash = str(torrent_hash or "").lower()
    target_basename = Path(str(torrent_name)).name
    target_lower = target_basename.lower()
    target_norm = normalize_name(target_basename)
    target_tokens = tuple(tokenize_name(target_basename))
    target_token_set = set(target_tokens)
    anchor_token = target_tokens[0] if target_tokens else ""
    if not target_lower and not target_norm:
        return 0

    limit = int(max_add)
    unlimited = limit <= 0
    added = 0
    seen_paths: Set[str] = set()

    def add_ranked(rec: GlobalDbPath, score: float, note: str) -> bool:
        nonlocal added
        if not unlimited and added >= limit:
            return False
        if rec.owner_hash and rec.owner_hash == target_hash:
            return True
        key = canonical_alias(rec.path)
        if not key or key in seen_paths:
            return True
        add_candidate(cands, rec.path, rec.source, score, note)
        seen_paths.add(key)
        added += 1
        return unlimited or added < limit

    # Exact basename match.
    for rec in index.by_basename.get(target_lower, ()):
        if not add_ranked(rec, 72.0, "global db exact basename"):
            return added

    # Normalized basename match.
    if target_norm:
        for rec in index.by_norm.get(target_norm, ()):
            if not add_ranked(rec, 68.0, "global db normalized basename"):
                return added

    # Token-overlap fallback.
    if target_token_set:
        overlap: Dict[str, Tuple[int, float, GlobalDbPath]] = {}
        for tok in target_token_set:
            for rec in index.by_token.get(tok, ()):
                if rec.owner_hash and rec.owner_hash == target_hash:
                    continue
                key = canonical_alias(rec.path)
                if not key or key in seen_paths:
                    continue
                rec_tokens = set(rec.tokens)
                if not rec_tokens:
                    continue
                overlap_count = len(target_token_set & rec_tokens)
                if overlap_count <= 0:
                    continue
                coverage = float(overlap_count) / float(max(1, len(target_token_set)))
                # Reject weak global fallbacks that only match generic fragments.
                if overlap_count < 2 and coverage < 0.75:
                    continue
                has_anchor = bool(anchor_token and anchor_token in rec_tokens)
                if not has_anchor and overlap_count < 3:
                    continue
                prev = overlap.get(key)
                if prev is None or overlap_count > prev[0] or (
                    overlap_count == prev[0] and coverage > prev[1]
                ):
                    overlap[key] = (overlap_count, coverage, rec)
        ranked = sorted(overlap.values(), key=lambda item: (item[0], item[1]), reverse=True)
        for count, coverage, rec in ranked:
            base_score = 38.0 + min(24.0, float(count * 5)) + min(8.0, coverage * 8.0)
            if not add_ranked(
                rec,
                base_score,
                f"global db token overlap={count} coverage={coverage:.2f}",
            ):
                return added

    return added


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
    dedup: List[str] = []
    seen = set()
    for cand in out:
        c = cand.rstrip("/")
        if c and c not in seen:
            seen.add(c)
            dedup.append(c)
    return dedup


def resolve_existing_path(path: str) -> Optional[str]:
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


def load_bucket_entries(index_path: Path) -> Dict[str, dict]:
    if not index_path.exists():
        return {}
    obj = json.loads(index_path.read_text(encoding="utf-8"))
    out: Dict[str, dict] = {}
    for entry in obj.get("entries", []):
        h = str(entry.get("hash", "")).lower().strip()
        if h:
            out[h] = dict(entry)
    return out


def load_bad_cache(path: Path) -> Dict[str, Dict[str, dict]]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = obj.get("entries", {})
    if not isinstance(entries, dict):
        return {}
    out: Dict[str, Dict[str, dict]] = {}
    for raw_hash, by_path in entries.items():
        h = str(raw_hash or "").strip().lower()
        if not h or not isinstance(by_path, dict):
            continue
        norm: Dict[str, dict] = {}
        for raw_path, meta in by_path.items():
            p = canonical_alias(str(raw_path or ""))
            if not p:
                continue
            if isinstance(meta, dict):
                norm[p] = dict(meta)
        if norm:
            out[h] = norm
    return out


def write_bad_cache(path: Path, cache: Dict[str, Dict[str, dict]]) -> None:
    payload = {
        "tool": "qb-stoppeddl-drain",
        "generated_at": ts_iso(),
        "entries": {
            h: {p: cache[h][p] for p in sorted(cache[h].keys())}
            for h in sorted(cache.keys())
            if cache[h]
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_tested_cache(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = obj.get("entries", {})
    if not isinstance(entries, dict):
        return {}
    out: Dict[str, dict] = {}
    for raw_hash, meta in entries.items():
        h = str(raw_hash or "").strip().lower()
        if not h or not isinstance(meta, dict):
            continue
        paths_obj = meta.get("paths", {})
        paths_norm: Dict[str, dict] = {}
        if isinstance(paths_obj, dict):
            for raw_path, pmeta in paths_obj.items():
                p = canonical_alias(str(raw_path or ""))
                if not p or not isinstance(pmeta, dict):
                    continue
                paths_norm[p] = dict(pmeta)
        out[h] = {
            "solved_a": bool(meta.get("solved_a", False)),
            "solved_a_trusted": bool(meta.get("solved_a_trusted", False)),
            "solved_a_path": str(meta.get("solved_a_path") or ""),
            "solved_a_seen": str(meta.get("solved_a_seen") or ""),
            "paths": paths_norm,
        }
    return out


def write_tested_cache(path: Path, cache: Dict[str, dict]) -> None:
    payload = {
        "tool": "qb-stoppeddl-drain",
        "generated_at": ts_iso(),
        "entries": {
            h: {
                "solved_a": bool(cache[h].get("solved_a", False)),
                "solved_a_trusted": bool(cache[h].get("solved_a_trusted", False)),
                "solved_a_path": str(cache[h].get("solved_a_path") or ""),
                "solved_a_seen": str(cache[h].get("solved_a_seen") or ""),
                "paths": {
                    p: cache[h]["paths"][p]
                    for p in sorted(cache[h].get("paths", {}).keys())
                },
            }
            for h in sorted(cache.keys())
            if isinstance(cache[h], dict)
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@dataclass
class Candidate:
    path: str
    source: str
    score: float
    note: str


def add_candidate(cands: Dict[str, Candidate], path: str, source: str, score: float, note: str) -> None:
    p = str(path or "").strip()
    if not p:
        return
    resolved = resolve_existing_path(p) or p
    key = canonical_alias(resolved)
    if not key:
        return
    prev = cands.get(key)
    if prev is None or score > prev.score:
        cands[key] = Candidate(path=resolved, source=source, score=float(score), note=note)


def source_preference_rank(source: str) -> int:
    s = str(source or "").lower()
    if s.startswith("qb_same_name_exact:"):
        return 7
    if s.startswith("qb_same_name_size:"):
        return 6
    if s.startswith("qb_same_name_nearsize:"):
        return 5
    if s.startswith("db_self_") or s.startswith("db_payload_self_"):
        return 4
    if s.startswith("db_payload_sibling_"):
        return 3
    if s.startswith("bucket_"):
        return 2
    if s.startswith("db_global_"):
        return 1
    return 0


def fetch_qb_rows() -> Tuple[QBittorrentClient, Dict[str, QBitTorrent], Dict[Tuple[str, int], List[QBitTorrent]]]:
    qb = get_qbittorrent_client()
    if not qb.test_connection() or not qb.login():
        raise RuntimeError("qB connection/login failed")
    rows = qb.get_torrents()
    by_hash = {str(r.hash or "").lower(): r for r in rows if str(r.hash or "").strip()}
    by_name_size: Dict[Tuple[str, int], List[QBitTorrent]] = defaultdict(list)
    for r in rows:
        by_name_size[(str(r.name or ""), int(r.size or 0))].append(r)
    return qb, by_hash, by_name_size


def db_row_for_hash(conn: sqlite3.Connection, torrent_hash: str) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT lower(ti.torrent_hash) AS torrent_hash,
               ti.save_path AS ti_save_path,
               ti.root_name AS ti_root_name,
               ti.payload_id AS payload_id,
               p.payload_hash AS payload_hash,
               p.root_path AS payload_root_path,
               p.status AS payload_status
          FROM torrent_instances ti
          LEFT JOIN payloads p ON p.payload_id = ti.payload_id
         WHERE lower(ti.torrent_hash) = ?
         LIMIT 1
        """,
        (str(torrent_hash or "").lower(),),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def db_siblings_for_payload_hash(conn: sqlite3.Connection, payload_hash: str) -> List[dict]:
    rows = conn.execute(
        """
        SELECT lower(ti.torrent_hash) AS torrent_hash,
               ti.save_path AS ti_save_path,
               ti.root_name AS ti_root_name,
               p.root_path AS payload_root_path,
               p.status AS payload_status
          FROM payloads p
          LEFT JOIN torrent_instances ti ON ti.payload_id = p.payload_id
         WHERE p.payload_hash = ?
         LIMIT 500
        """,
        (str(payload_hash or ""),),
    ).fetchall()
    return [dict(r) for r in rows]


def classify_letter(best: dict, source: str) -> str:
    cls = str(best.get("classification", "") or "")
    if cls == "exact_tree":
        if source.startswith("db_self"):
            return "a"
        return "b"
    if cls == "close_match":
        return "c"
    if cls == "partial_match":
        return "d"
    return "e"


def live_seed_ready(row: QBitTorrent) -> bool:
    state = str(row.state or "").lower()
    if state not in LIVE_SEED_READY_STATES:
        return False
    progress = float(row.progress or 0.0)
    amount_left = int(row.amount_left or 0)
    return progress >= 0.9999 or amount_left <= 0


def live_skip_reason(row: Optional[QBitTorrent]) -> str:
    if row is None:
        return ""
    state = str(row.state or "").lower()
    if state in LIVE_CHECKING_STATES:
        return f"checking:{state}"
    if live_seed_ready(row):
        return f"seed_ready:{state}"
    return ""


def run_quick_probe(
    verifier_python: Path,
    verifier_script: Path,
    torrent_file: Path,
    reports_dir: Path,
    torrent_hash: str,
    paths: List[str],
) -> Tuple[Dict[str, dict], str]:
    if not paths:
        return {}, ""
    quick_json = reports_dir / f"quick-{torrent_hash}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    cmd = [
        str(verifier_python),
        str(verifier_script),
        "--torrent",
        str(torrent_file),
        "--quick-only",
        "--quiet-summary",
        "--json-out",
        str(quick_json),
    ]
    for p in paths:
        cmd.extend(["--path", p])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode not in (0, 1) or not quick_json.exists():
        return {}, str(quick_json)
    try:
        obj = json.loads(quick_json.read_text(encoding="utf-8"))
    except Exception:
        return {}, str(quick_json)
    out: Dict[str, dict] = {}
    for row in obj.get("results", []):
        key = canonical_alias(str(row.get("path") or ""))
        if not key:
            continue
        out[key] = {
            "quick_ratio": float(row.get("quick_ratio", 0.0) or 0.0),
            "size_overlap_ratio": float(row.get("size_overlap_ratio", 0.0) or 0.0),
            "exact_tree": bool(row.get("exact_tree")),
            "expected_files": int(row.get("expected_files", 0) or 0),
            "actual_files": int(row.get("actual_files", 0) or 0),
        }
    return out, str(quick_json)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Drain stoppedDL bucket by offline candidate verification and classification."
    )
    p.add_argument(
        "--bucket-dir",
        default="~/.cache/hashall/qb-stoppeddl-bucket",
        help="Bucket directory created by qb-stoppeddl-bucket.py",
    )
    p.add_argument(
        "--db",
        default=str(Path.home() / ".hashall" / "catalog.db"),
        help="hashall catalog DB path",
    )
    p.add_argument("--hashes", default="", help="Optional explicit hashes")
    p.add_argument("--hashes-file", default="", help="Optional hash file")
    p.add_argument(
        "--allowed-save-roots",
        default="",
        help=(
            "Comma-separated absolute candidate roots allowed in drain selection "
            "(default: seed-root-state pool roots, else built-in safe defaults)"
        ),
    )
    p.add_argument(
        "--forbid-save-roots",
        default=DEFAULT_FORBID_SAVE_ROOTS,
        help=(
            "Comma-separated absolute candidate roots blocked in drain selection "
            f"(default: {DEFAULT_FORBID_SAVE_ROOTS})"
        ),
    )
    p.add_argument(
        "--allowed-donor-roots",
        default="",
        help=(
            "Comma-separated absolute candidate roots allowed as donor verification sources "
            "(default: seed-root-state pool roots, else built-in safe defaults)"
        ),
    )
    p.add_argument(
        "--seed-root-state",
        default=str(SEED_ROOT_STATE_PATH),
        help=(
            "Path to hashall seed-root-state.json used to derive safe pool roots "
            "(default: ~/.hashall/seed-root-state.json)"
        ),
    )
    p.add_argument(
        "--no-seed-root-state",
        dest="use_seed_root_state",
        action="store_false",
        help="Do not derive default root policy from seed-root-state.json",
    )
    p.set_defaults(use_seed_root_state=True)
    p.add_argument(
        "--forbid-donor-roots",
        default=DEFAULT_FORBID_DONOR_ROOTS,
        help=(
            "Comma-separated absolute candidate roots blocked as donor verification sources "
            f"(default: {DEFAULT_FORBID_DONOR_ROOTS})"
        ),
    )
    p.add_argument(
        "--same-filesystem-only",
        dest="same_filesystem_only",
        action="store_true",
        help=(
            "Require donor candidates to match the target torrent filesystem "
            "(default: enabled)"
        ),
    )
    p.add_argument(
        "--no-same-filesystem-only",
        dest="same_filesystem_only",
        action="store_false",
        help="Allow donor candidates from other filesystems",
    )
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
    p.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Max hashes to process this run (default: 1)",
    )
    p.add_argument(
        "--max-candidates",
        type=int,
        default=0,
        help="Max candidate paths to verify per hash (0 = all, default: 0)",
    )
    p.add_argument(
        "--stop-on-a",
        dest="stop_on_a",
        action="store_true",
        help="Stop verifying further candidates for a hash once class A is found (default: enabled)",
    )
    p.add_argument(
        "--no-stop-on-a",
        dest="stop_on_a",
        action="store_false",
        help="Continue verifying all selected candidates even after class A",
    )
    p.add_argument(
        "--verify-timeout",
        type=float,
        default=900.0,
        help="Per-candidate verify timeout seconds (default: 900)",
    )
    p.add_argument(
        "--verify-poll",
        type=float,
        default=1.0,
        help="Verify poll interval seconds (default: 1)",
    )
    p.add_argument(
        "--verify-python",
        default="/usr/bin/python3",
        help="Python executable for verifier script (default: /usr/bin/python3)",
    )
    p.add_argument(
        "--verifier-script",
        default=str(REPO_ROOT / "bin" / "qb-libtorrent-verify.py"),
        help="Verifier script path",
    )
    p.add_argument(
        "--show-verify-progress",
        action="store_true",
        help="Pass --show-progress to verifier",
    )
    p.add_argument(
        "--extra-root",
        action="append",
        default=[],
        help="Extra root path to test for each hash (repeatable)",
    )
    p.add_argument(
        "--scan-db-global",
        dest="scan_db_global",
        action="store_true",
        help="Include global hashall DB roots from all scanned filesystems (default: enabled)",
    )
    p.add_argument(
        "--no-scan-db-global",
        dest="scan_db_global",
        action="store_false",
        help="Disable global hashall DB root candidate scan",
    )
    p.add_argument(
        "--scan-db-global-max",
        type=int,
        default=0,
        help="Max global DB candidates to add per hash (0 = all, default: 0)",
    )
    p.add_argument(
        "--report-json",
        default="",
        help="Optional report path (default: <bucket>/reports/drain-<ts>.json)",
    )
    p.add_argument(
        "--stop-file",
        default="",
        help=(
            "Optional stop-file path. If this file exists, drain exits early and "
            "terminates any in-flight verifier subprocess."
        ),
    )
    p.add_argument(
        "--no-update-latest",
        dest="update_latest",
        action="store_false",
        help="Do not update <bucket>/reports/drain-latest.json (useful for one-off audits)",
    )
    p.set_defaults(update_latest=True)
    p.add_argument(
        "--bad-cache-json",
        default="",
        help="Path to persistent bad-candidate cache JSON (default: <bucket>/bad-candidates.json)",
    )
    p.add_argument(
        "--bad-penalty",
        type=float,
        default=15.0,
        help="Score penalty per prior failure for the same hash/path (default: 15)",
    )
    p.add_argument(
        "--bad-threshold",
        type=int,
        default=2,
        help="Failure count threshold used with --skip-known-bad (default: 2)",
    )
    p.add_argument(
        "--skip-known-bad",
        action="store_true",
        help="Skip candidates whose cached failure count >= --bad-threshold",
    )
    p.add_argument(
        "--tested-cache-json",
        default="",
        help="Path to persistent tested-candidate cache JSON (default: <bucket>/tested-candidates.json)",
    )
    p.add_argument(
        "--skip-tested-candidates",
        dest="skip_tested_candidates",
        action="store_true",
        help="Skip candidate paths already tested for the same hash (default: enabled)",
    )
    p.add_argument(
        "--no-skip-tested-candidates",
        dest="skip_tested_candidates",
        action="store_false",
        help="Allow retesting previously tested candidate paths",
    )
    p.add_argument(
        "--skip-hash-if-a",
        dest="skip_hash_if_a",
        action="store_true",
        help="Skip entire hash if prior run already found class A (default: enabled)",
    )
    p.add_argument(
        "--no-skip-hash-if-a",
        dest="skip_hash_if_a",
        action="store_false",
        help="Do not skip hashes previously solved as class A",
    )
    p.add_argument(
        "--skip-live-active",
        dest="skip_live_active",
        action="store_true",
        help="Skip hash when live qB state is checking* or already seed-ready (default: enabled)",
    )
    p.add_argument(
        "--no-skip-live-active",
        dest="skip_live_active",
        action="store_false",
        help="Do not skip hash based on live qB state",
    )
    p.set_defaults(scan_db_global=True)
    p.set_defaults(skip_tested_candidates=True)
    p.set_defaults(skip_hash_if_a=True)
    p.set_defaults(skip_live_active=True)
    p.set_defaults(stop_on_a=True)
    p.set_defaults(same_filesystem_only=True)
    return p


def main() -> int:
    args = build_parser().parse_args()
    run_started_at = emit_start_banner()
    bucket_dir = Path(args.bucket_dir).expanduser()
    index_path = bucket_dir / "index.json"
    reports_dir = bucket_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = (
        Path(args.report_json).expanduser()
        if str(args.report_json or "").strip()
        else reports_dir / f"drain-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    latest_report_path = reports_dir / "drain-latest.json"
    bad_cache_path = (
        Path(args.bad_cache_json).expanduser()
        if str(args.bad_cache_json or "").strip()
        else bucket_dir / "bad-candidates.json"
    )
    tested_cache_path = (
        Path(args.tested_cache_json).expanduser()
        if str(args.tested_cache_json or "").strip()
        else bucket_dir / "tested-candidates.json"
    )
    stop_file_path = (
        Path(args.stop_file).expanduser()
        if str(args.stop_file or "").strip()
        else None
    )
    bad_cache = load_bad_cache(bad_cache_path)
    tested_cache = load_tested_cache(tested_cache_path)
    bad_cache_updates = 0
    bad_candidates_skipped = 0
    tested_cache_updates = 0
    tested_candidates_skipped = 0
    solved_hashes_skipped = 0
    live_state_skipped = 0
    quick_prefilter_skipped = 0
    ignored_hashes_skipped = 0
    untrusted_verified_retests = 0
    tested_cache_fallback_retests = 0
    root_policy_candidates_skipped = 0
    root_policy_hashes_blocked = 0
    filesystem_candidates_skipped = 0
    filesystem_hashes_blocked = 0

    if not index_path.exists():
        print(f"ERROR bucket_index_missing path={index_path}")
        print("hint: run bin/qb-stoppeddl-bucket.py first")
        return 2
    try:
        entries_by_hash = load_bucket_entries(index_path)
    except Exception as exc:
        print(f"ERROR bucket_index_invalid path={index_path} err={exc}")
        print("hint: run bin/qb-stoppeddl-bucket.py first")
        return 2

    selected_hashes = parse_hash_tokens(args.hashes)
    selected_hashes.extend(read_hash_file(args.hashes_file))
    selected_hashes = list(dict.fromkeys(selected_hashes))
    seed_root_policy: Dict[str, List[str]] = {}
    seed_root_state_path = Path(args.seed_root_state).expanduser()
    if bool(args.use_seed_root_state) and seed_root_state_path.exists():
        try:
            seed_root_policy = load_seed_root_policy(seed_root_state_path)
            print(
                "seed_root_policy "
                f"path={seed_root_state_path} "
                f"allowed_save_roots={','.join(seed_root_policy['allowed_save_roots'])} "
                f"allowed_donor_roots={','.join(seed_root_policy['allowed_donor_roots'])}"
            )
        except Exception as exc:
            print(f"WARN seed_root_policy_unusable path={seed_root_state_path} detail={exc}")
    allowed_roots = parse_path_list(args.allowed_save_roots) or seed_root_policy.get(
        "allowed_save_roots", parse_path_list(DEFAULT_ALLOWED_SAVE_ROOTS)
    )
    forbidden_roots = parse_path_list(args.forbid_save_roots)
    allowed_donor_roots = parse_path_list(args.allowed_donor_roots) or seed_root_policy.get(
        "allowed_donor_roots", parse_path_list(DEFAULT_ALLOWED_DONOR_ROOTS)
    )
    forbidden_donor_roots = parse_path_list(args.forbid_donor_roots)
    default_ignore_file = bucket_dir / "download-whitelist-hashes.txt"
    ignore_hashes = parse_hash_tokens(args.ignore_hashes)
    if str(args.ignore_hashes_file or "").strip():
        ignore_hashes.extend(read_hash_file(args.ignore_hashes_file))
    elif default_ignore_file.exists():
        ignore_hashes.extend(read_hash_file(str(default_ignore_file)))
    ignore_hashes = list(dict.fromkeys(ignore_hashes))
    ignore_set = set(ignore_hashes)
    if not selected_hashes:
        selected_hashes = [
            h
            for h, e in sorted(entries_by_hash.items(), key=lambda kv: (str(kv[1].get("first_seen", "")), str(kv[0])))
            if str(e.get("state", "")).lower() == "stoppeddl"
        ]
    if ignore_set:
        before_ignore = len(selected_hashes)
        selected_hashes = [h for h in selected_hashes if not hash_matches_filters(h, ignore_set)]
        ignored_hashes_skipped = max(0, before_ignore - len(selected_hashes))
    if args.limit > 0:
        selected_hashes = selected_hashes[: args.limit]

    print(
        "root_policy "
        f"allowed_roots={','.join(allowed_roots) if allowed_roots else '<none>'} "
        f"forbidden_roots={','.join(forbidden_roots) if forbidden_roots else '<none>'}"
    )
    print(
        "donor_policy "
        f"allowed_roots={','.join(allowed_donor_roots) if allowed_donor_roots else '<none>'} "
        f"forbidden_roots={','.join(forbidden_donor_roots) if forbidden_donor_roots else '<none>'}"
    )
    print(f"filesystem_policy same_filesystem_only={bool(args.same_filesystem_only)}")

    if not selected_hashes:
        print("summary selected=0 reason=no_hashes")
        return 0

    qb_client, by_hash_qb, by_name_size_qb = fetch_qb_rows()
    conn = sqlite3.connect(str(Path(args.db).expanduser()))
    conn.row_factory = sqlite3.Row
    global_db_index: Optional[GlobalDbIndex] = None
    if args.scan_db_global:
        global_db_index = load_global_db_index(conn)
        print(
            f"global_db_scan enabled paths={len(global_db_index.all_paths)} "
            f"exact_keys={len(global_db_index.by_basename)} norm_keys={len(global_db_index.by_norm)}"
        )

    verifier_script = Path(args.verifier_script).expanduser()
    verifier_python = Path(args.verify_python).expanduser()
    if not verifier_script.exists():
        print(f"ERROR verifier_not_found path={verifier_script}")
        return 2
    if not verifier_python.exists():
        print(f"ERROR verify_python_not_found path={verifier_python}")
        return 2

    out_entries: List[dict] = []
    class_counts = Counter()

    def write_progress_report(reason: str) -> dict:
        summary = {
            "selected": len(selected_hashes),
            "processed": len(out_entries),
            "remaining": max(0, len(selected_hashes) - len(out_entries)),
            "a": int(class_counts["a"]),
            "b": int(class_counts["b"]),
            "c": int(class_counts["c"]),
            "d": int(class_counts["d"]),
            "e": int(class_counts["e"]),
            "bad_cache_entries": int(sum(len(v) for v in bad_cache.values())),
            "bad_cache_updates": int(bad_cache_updates),
            "bad_candidates_skipped": int(bad_candidates_skipped),
            "tested_cache_hashes": int(len(tested_cache)),
            "tested_cache_paths": int(
                sum(len(v.get("paths", {})) for v in tested_cache.values() if isinstance(v, dict))
            ),
            "tested_cache_updates": int(tested_cache_updates),
            "tested_candidates_skipped": int(tested_candidates_skipped),
            "solved_hashes_skipped": int(solved_hashes_skipped),
            "live_state_skipped": int(live_state_skipped),
            "quick_prefilter_skipped": int(quick_prefilter_skipped),
            "ignored_hashes_skipped": int(ignored_hashes_skipped),
            "untrusted_verified_retests": int(untrusted_verified_retests),
            "tested_cache_fallback_retests": int(tested_cache_fallback_retests),
            "root_policy_candidates_skipped": int(root_policy_candidates_skipped),
            "root_policy_hashes_blocked": int(root_policy_hashes_blocked),
            "filesystem_candidates_skipped": int(filesystem_candidates_skipped),
            "filesystem_hashes_blocked": int(filesystem_hashes_blocked),
        }
        is_complete = bool(summary["remaining"] == 0 and reason == "final")
        summary["complete"] = is_complete
        summary["incomplete_reason"] = "" if is_complete else str(reason)
        payload = {
            "tool": "qb-stoppeddl-drain",
            "script": SCRIPT_NAME,
            "semver": SEMVER,
            "generated_at": run_started_at,
            "updated_at": ts_iso(),
            "progress_reason": reason,
            "bucket_dir": str(bucket_dir),
            "index_json": str(index_path),
            "bad_cache_json": str(bad_cache_path),
            "tested_cache_json": str(tested_cache_path),
            "ignored_hashes": ignore_hashes,
            "ignore_hashes_file": str(Path(args.ignore_hashes_file).expanduser()) if str(args.ignore_hashes_file or "").strip() else (str(default_ignore_file) if default_ignore_file.exists() else ""),
            "root_policy": {
                "allowed_roots": allowed_roots,
                "forbidden_roots": forbidden_roots,
            },
            "args": vars(args),
            "summary": summary,
            "entries": out_entries,
        }
        text = json.dumps(payload, indent=2) + "\n"
        report_path.write_text(text, encoding="utf-8")
        if bool(args.update_latest) and latest_report_path != report_path:
            latest_report_path.write_text(text, encoding="utf-8")
        return summary

    def flush_caches() -> None:
        # Persist tested/bad candidate state incrementally so interruption does not
        # lose already-graded paths in the current run.
        write_bad_cache(bad_cache_path, bad_cache)
        write_tested_cache(tested_cache_path, tested_cache)

    write_progress_report("started")
    stop_requested_global = False

    def stop_requested() -> bool:
        return bool(stop_file_path and stop_file_path.exists())

    for idx, h in enumerate(selected_hashes, start=1):
        if stop_requested():
            stop_requested_global = True
            print(f"status action=stop reason=stop_file_exists stop_file={stop_file_path}")
            write_progress_report("stop_file_exists")
            break
        entry = dict(entries_by_hash.get(h, {}))
        row_qb = by_hash_qb.get(h)
        name = str(entry.get("name") or (row_qb.name if row_qb else ""))
        size = int(entry.get("size") or (row_qb.size if row_qb else 0))
        torrent_file = Path(str(entry.get("torrent_file") or (bucket_dir / "torrents" / f"{h}.torrent"))).expanduser()
        print(f"[{idx}/{len(selected_hashes)}] hash={h[:12]} name={name[:80]}")

        row_out = {
            "hash": h,
            "name": name,
            "size": size,
            "bucket_state": str(entry.get("state") or ""),
            "torrent_file": str(torrent_file),
            "torrent_file_refresh": {
                "attempted": False,
                "ok": False,
                "error": "",
            },
            "status": "pending",
            "classification": "e",
            "recommended_path": "",
            "recommended_source": "",
            "candidates": [],
            "verify_report_json": "",
            "verify_stdout": "",
            "verify_stderr": "",
            "bad_cache": {
                "path": str(bad_cache_path),
                "skipped_candidates": [],
            },
            "tested_cache": {
                "path": str(tested_cache_path),
                "skipped_candidates": [],
                "retest_candidates": [],
                "hash_skip_reason": "",
            },
            "quick_prefilter": {
                "skipped_candidates": [],
            },
            "root_policy": {
                "allowed_roots": allowed_roots,
                "forbidden_roots": forbidden_roots,
                "skipped_candidates": [],
            },
            "donor_policy": {
                "allowed_roots": allowed_donor_roots,
                "forbidden_roots": forbidden_donor_roots,
                "skipped_candidates": [],
            },
            "filesystem_policy": {
                "same_filesystem_only": bool(args.same_filesystem_only),
                "target_save_path": "",
                "target_device_id": None,
                "target_storage_root": "",
                "skipped_candidates": [],
            },
            "global_db_candidates_added": 0,
            "quick_probe_report_json": "",
        }

        prior_tested_hash = tested_cache.get(h, {})
        prior_solved_a = bool(prior_tested_hash.get("solved_a", False))
        prior_solved_a_trusted = bool(prior_tested_hash.get("solved_a_trusted", False))
        if args.skip_hash_if_a and prior_solved_a and prior_solved_a_trusted:
            row_out["status"] = "skip_solved_a_cached"
            row_out["classification"] = "a"
            row_out["tested_cache"]["hash_skip_reason"] = "solved_a_cached"
            row_out["recommended_path"] = str(prior_tested_hash.get("solved_a_path") or "")
            out_entries.append(row_out)
            solved_hashes_skipped += 1
            write_progress_report(f"hash:{h}:skip_solved_a_cached")
            print("  skip solved_a_cached")
            continue
        if args.skip_hash_if_a and prior_solved_a and not prior_solved_a_trusted:
            row_out["tested_cache"]["hash_skip_reason"] = "retest_untrusted_solved_a"

        if args.skip_live_active and row_qb is not None:
            reason = live_skip_reason(row_qb)
            if reason:
                row_out["status"] = "skip_live_state"
                row_out["detail"] = reason
                row_out["live_qb_state"] = str(row_qb.state or "")
                row_out["live_qb_progress"] = float(row_qb.progress or 0.0)
                row_out["live_qb_amount_left"] = int(row_qb.amount_left or 0)
                out_entries.append(row_out)
                live_state_skipped += 1
                write_progress_report(f"hash:{h}:skip_live_state")
                print(
                    f"  skip live_state={row_qb.state} progress={float(row_qb.progress or 0.0):.6f} "
                    f"amount_left={int(row_qb.amount_left or 0)} reason={reason}"
                )
                continue

        if not torrent_file.exists():
            row_out["torrent_file_refresh"]["attempted"] = True
            try:
                blob = qb_client.export_torrent_file(h, out_path=torrent_file)
                refreshed = bool(blob) and torrent_file.exists() and torrent_file.stat().st_size > 0
                row_out["torrent_file_refresh"]["ok"] = bool(refreshed)
            except Exception as exc:
                row_out["torrent_file_refresh"]["error"] = str(exc)
            if row_out["torrent_file_refresh"]["ok"]:
                print(f"  refreshed missing torrent_file from qB path={torrent_file}")
            else:
                row_out["status"] = "no_torrent_file"
                row_out["classification"] = "e"
                class_counts["e"] += 1
                out_entries.append(row_out)
                write_progress_report(f"hash:{h}:no_torrent_file")
                continue

        cands: Dict[str, Candidate] = {}
        # Bucket/current qB hints
        save_path = str(entry.get("save_path") or (row_qb.save_path if row_qb else ""))
        content_path = str(entry.get("content_path") or (row_qb.content_path if row_qb else ""))
        if content_path:
            add_candidate(cands, content_path, "bucket_content_path", 40.0, "bucket content_path")
        if save_path:
            add_candidate(cands, save_path, "bucket_save_path", 30.0, "bucket save_path")
            if name:
                add_candidate(cands, str(Path(save_path) / name), "bucket_save_plus_name", 35.0, "save_path + name")

        # DB lookups
        db_self = db_row_for_hash(conn, h)
        payload_hash = ""
        if db_self:
            payload_hash = str(db_self.get("payload_hash") or "")
            db_save = str(db_self.get("ti_save_path") or "")
            db_root = str(db_self.get("ti_root_name") or "")
            payload_root = str(db_self.get("payload_root_path") or "")
            if payload_root:
                add_candidate(cands, payload_root, "db_self_payload_root", 100.0, "payload root for hash")
            if db_save:
                add_candidate(cands, db_save, "db_self_save_path", 60.0, "torrent_instances.save_path")
                if db_root:
                    add_candidate(
                        cands,
                        str(Path(db_save) / db_root),
                        "db_self_save_root",
                        90.0,
                        "save_path + root_name",
                    )

        if payload_hash:
            sibs = db_siblings_for_payload_hash(conn, payload_hash)
            for sib in sibs:
                sh = str(sib.get("torrent_hash") or "")
                source_suffix = "self" if sh == h else "sibling"
                s_save = str(sib.get("ti_save_path") or "")
                s_root = str(sib.get("ti_root_name") or "")
                s_payload_root = str(sib.get("payload_root_path") or "")
                if s_payload_root:
                    add_candidate(
                        cands,
                        s_payload_root,
                        f"db_payload_{source_suffix}_payload_root",
                        95.0 if source_suffix == "self" else 85.0,
                        "same payload_hash root",
                    )
                if s_save:
                    add_candidate(
                        cands,
                        s_save,
                        f"db_payload_{source_suffix}_save_path",
                        50.0,
                        "same payload_hash save_path",
                    )
                    if s_root:
                        add_candidate(
                            cands,
                            str(Path(s_save) / s_root),
                            f"db_payload_{source_suffix}_save_root",
                            75.0 if source_suffix == "self" else 65.0,
                            "same payload_hash save_path + root_name",
                        )

        # Live qB same-name+size siblings
        for sib in by_name_size_qb.get((name, size), []):
            sh = str(sib.hash or "").lower()
            if sh == h:
                continue
            st = str(sib.state or "").lower()
            base_score = 150.0 if live_seed_ready(sib) else (120.0 if st in TRUSTED_STATES else 45.0)
            add_candidate(
                cands,
                str(sib.content_path or ""),
                f"qb_same_name_size:{st}",
                base_score,
                "qB same name+size content_path",
            )
            if sib.save_path and sib.name:
                add_candidate(
                    cands,
                    str(Path(sib.save_path) / sib.name),
                    f"qb_same_name_size_save_name:{st}",
                    base_score - 3.0,
                    "qB same name+size save_path + name",
                )

        # Strong fallback: exact same qB name, even when size metadata is slightly off.
        target_name = str(name or "")
        if target_name:
            seen_exact_name_hashes: Set[str] = set()
            for sib in by_hash_qb.values():
                sh = str(sib.hash or "").lower()
                if not sh or sh == h or sh in seen_exact_name_hashes:
                    continue
                if str(sib.name or "") != target_name:
                    continue
                seen_exact_name_hashes.add(sh)
                st = str(sib.state or "").lower()
                sib_size = int(sib.size or 0)
                target_size = int(size or 0)
                size_ratio = 0.0
                if target_size > 0 and sib_size > 0:
                    size_ratio = float(min(sib_size, target_size)) / float(max(sib_size, target_size))
                base_score = 165.0 if live_seed_ready(sib) else (132.0 if st in TRUSTED_STATES else 55.0)
                base_score += (size_ratio * 8.0)
                note = "qB exact same name sibling"
                add_candidate(
                    cands,
                    str(sib.content_path or ""),
                    f"qb_same_name_exact:{st}",
                    base_score,
                    note,
                )
                if sib.save_path and sib.name:
                    add_candidate(
                        cands,
                        str(Path(sib.save_path) / sib.name),
                        f"qb_same_name_exact_save_name:{st}",
                        base_score - 2.0,
                        note + " save_path + name",
                    )

        # Fallback: same normalized name with near-size tolerance.
        # qB display rounds sizes, and some sibling torrents differ slightly in
        # metadata/padding while still being high-value candidates.
        target_name_norm = normalize_name(name)
        if target_name_norm:
            seen_nearsize_hashes: Set[str] = set()
            for sib in by_hash_qb.values():
                sh = str(sib.hash or "").lower()
                if not sh or sh == h or sh in seen_nearsize_hashes:
                    continue
                sib_name_norm = normalize_name(str(sib.name or ""))
                if not sib_name_norm or sib_name_norm != target_name_norm:
                    continue

                sib_size = int(sib.size or 0)
                target_size = int(size or 0)
                if target_size > 0 and sib_size > 0:
                    size_delta = abs(sib_size - target_size)
                    size_tol = max(64 * 1024 * 1024, int(target_size * 0.02))
                    if size_delta > size_tol:
                        continue
                    size_ratio = float(min(sib_size, target_size)) / float(max(sib_size, target_size))
                else:
                    size_delta = abs(sib_size - target_size)
                    size_ratio = 0.0

                seen_nearsize_hashes.add(sh)
                st = str(sib.state or "").lower()
                base_score = 112.0 if live_seed_ready(sib) else (86.0 if st in TRUSTED_STATES else 36.0)
                base_score += (size_ratio * 8.0)
                note = f"qB same normalized name near-size delta={size_delta}"
                add_candidate(
                    cands,
                    str(sib.content_path or ""),
                    f"qb_same_name_nearsize:{st}",
                    base_score,
                    note,
                )
                if sib.save_path and sib.name:
                    add_candidate(
                        cands,
                        str(Path(sib.save_path) / sib.name),
                        f"qb_same_name_nearsize_save_name:{st}",
                        base_score - 2.0,
                        note + " save_path + name",
                    )

        for extra_root in args.extra_root:
            root = str(extra_root or "").strip()
            if not root:
                continue
            add_candidate(cands, root, "extra_root", 20.0, "user extra root")
            if name:
                add_candidate(
                    cands,
                    str(Path(root) / name),
                    "extra_root_plus_name",
                    25.0,
                    "user extra root + torrent name",
                )

        if global_db_index is not None and name:
            added_global = add_global_db_candidates(
                cands=cands,
                index=global_db_index,
                torrent_hash=h,
                torrent_name=name,
                max_add=max(0, int(args.scan_db_global_max)),
            )
            row_out["global_db_candidates_added"] = int(added_global)

        per_hash_bad = bad_cache.get(h, {})
        per_hash_tested = (
            dict(prior_tested_hash.get("paths", {}))
            if isinstance(prior_tested_hash, dict)
            else {}
        )
        ranked: List[Tuple[float, float, float, Candidate, int, str]] = []
        tested_skipped_ranked: List[Tuple[float, float, float, Candidate, int, str]] = []
        target_save_path = str(save_path or "")
        target_storage_root = storage_root_label(target_save_path)
        target_device_id = _device_id_for_path(target_save_path)
        row_out["filesystem_policy"]["target_save_path"] = target_save_path
        row_out["filesystem_policy"]["target_device_id"] = target_device_id
        row_out["filesystem_policy"]["target_storage_root"] = target_storage_root
        donor_root_counts: Counter[str] = Counter()
        same_root_candidate_available = False
        pool_candidate_available = False
        for cand in cands.values():
            root_ok, root_reason = root_policy_check(cand.path, allowed_donor_roots, forbidden_donor_roots)
            if not root_ok:
                root_policy_candidates_skipped += 1
                row_out["donor_policy"]["skipped_candidates"].append(
                    {
                        "path": cand.path,
                        "source": cand.source,
                        "reason": root_reason,
                    }
                )
                continue
            key = canonical_alias(cand.path)
            prior_tested_meta = per_hash_tested.get(key, {})
            bad_meta = per_hash_bad.get(key, {})
            fail_count = int(bad_meta.get("fail_count", 0) or 0)
            last_cls = str(bad_meta.get("last_classification", "") or "")
            affinity = donor_affinity_score(cand.path, target_save_path)
            adjusted = float(cand.score) + affinity - (float(args.bad_penalty) * float(fail_count))
            root_label = storage_root_label(cand.path)
            donor_root_counts[root_label] += 1
            if root_label == "pool":
                pool_candidate_available = True
            if root_label == target_storage_root:
                same_root_candidate_available = True
            prior_verified = bool(prior_tested_meta.get("last_verified", False))
            prior_seen_checking = bool(prior_tested_meta.get("last_seen_checking_files", False))
            skip_due_to_tested = (not prior_verified) or prior_seen_checking
            if args.skip_tested_candidates and prior_tested_meta and skip_due_to_tested:
                tested_skipped_ranked.append((adjusted, affinity, float(cand.score), cand, fail_count, last_cls))
                tested_candidates_skipped += 1
                row_out["tested_cache"]["skipped_candidates"].append(
                    {
                        "path": cand.path,
                        "source": cand.source,
                        "last_classification": str(prior_tested_meta.get("last_classification") or ""),
                        "last_ratio": float(prior_tested_meta.get("last_ratio", 0.0) or 0.0),
                        "last_seen": str(prior_tested_meta.get("last_seen") or ""),
                        "reason": "skip_tested_candidate",
                    }
                )
                continue
            if args.skip_tested_candidates and prior_tested_meta and not skip_due_to_tested:
                untrusted_verified_retests += 1
                row_out["tested_cache"]["retest_candidates"].append(
                    {
                        "path": cand.path,
                        "source": cand.source,
                        "last_classification": str(prior_tested_meta.get("last_classification") or ""),
                        "last_ratio": float(prior_tested_meta.get("last_ratio", 0.0) or 0.0),
                        "last_seen": str(prior_tested_meta.get("last_seen") or ""),
                        "reason": "retest_untrusted_verified",
                    }
                )
            if args.skip_known_bad and fail_count >= int(args.bad_threshold):
                bad_candidates_skipped += 1
                row_out["bad_cache"]["skipped_candidates"].append(
                    {
                        "path": cand.path,
                        "source": cand.source,
                        "fail_count": fail_count,
                        "last_classification": last_cls,
                        "reason": "skip_known_bad",
                    }
                )
                continue
            ranked.append((adjusted, affinity, float(cand.score), cand, fail_count, last_cls))

        row_out["donor_insights"] = {
            "target_save_path": target_save_path,
            "target_storage_root": target_storage_root,
            "pool_donor_available": bool(pool_candidate_available),
            "same_root_donor_available": bool(same_root_candidate_available),
            "candidate_root_counts": dict(donor_root_counts),
            "affinity_strategy": "prefer_same_storage_root_then_longer_prefix",
            "selected_best_storage_root": "",
            "verified_pool_candidate": False,
        }

        if not ranked and tested_skipped_ranked:
            tested_cache_fallback_retests += 1
            row_out["tested_cache"]["hash_skip_reason"] = "fallback_retest_all_tested"
            ranked = tested_skipped_ranked
            print(f"  fallback retest_all_tested candidates={len(ranked)}")

        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        existing_ranked = [item for item in ranked if Path(item[3].path).exists()]
        if bool(args.same_filesystem_only) and existing_ranked:
            fs_filtered_ranked: List[Tuple[float, float, float, Candidate, int, str]] = []
            for item in existing_ranked:
                cand = item[3]
                cand_device_id = _device_id_for_path(cand.path)
                reason = ""
                allow = False
                if target_device_id is not None and cand_device_id is not None:
                    allow = target_device_id == cand_device_id
                    if not allow:
                        reason = f"device_mismatch:{cand_device_id}!={target_device_id}"
                else:
                    cand_storage_root = storage_root_label(cand.path)
                    allow = cand_storage_root == target_storage_root
                    if not allow:
                        reason = (
                            f"storage_root_mismatch:{cand_storage_root}!={target_storage_root}"
                        )
                if allow:
                    fs_filtered_ranked.append(item)
                    continue
                filesystem_candidates_skipped += 1
                row_out["filesystem_policy"]["skipped_candidates"].append(
                    {
                        "path": cand.path,
                        "source": cand.source,
                        "candidate_device_id": cand_device_id,
                        "reason": reason or "filesystem_guard_failed",
                    }
                )
            existing_ranked = fs_filtered_ranked
        quick_by_path: Dict[str, dict] = {}
        if existing_ranked and int(args.max_candidates) > 0:
            quick_window = max(20, int(args.max_candidates) * 20)
            probe_limit = min(len(existing_ranked), min(200, quick_window))
            probe_paths = [item[3].path for item in existing_ranked[:probe_limit]]
            quick_by_path, quick_json_path = run_quick_probe(
                verifier_python=verifier_python,
                verifier_script=verifier_script,
                torrent_file=torrent_file,
                reports_dir=reports_dir,
                torrent_hash=h,
                paths=probe_paths,
            )
            row_out["quick_probe_report_json"] = quick_json_path
            if quick_by_path:
                def quality_key(item: Tuple[float, float, float, Candidate, int, str]) -> Tuple[float, float, float, int, float, float, float]:
                    key = canonical_alias(item[3].path)
                    quick = quick_by_path.get(key, {})
                    exact = 1.0 if bool(quick.get("exact_tree")) else 0.0
                    quick_ratio = float(quick.get("quick_ratio", 0.0) or 0.0)
                    size_overlap = float(quick.get("size_overlap_ratio", 0.0) or 0.0)
                    source_rank = source_preference_rank(item[3].source)
                    return (
                        exact,
                        quick_ratio,
                        size_overlap,
                        int(source_rank),
                        float(item[0]),
                        float(item[1]),
                        float(item[2]),
                    )

                existing_ranked.sort(key=quality_key, reverse=True)
                filtered_ranked: List[Tuple[float, float, str, Candidate, int, str]] = []
                for item in existing_ranked:
                    cand = item[3]
                    cand_key = canonical_alias(cand.path)
                    quick = quick_by_path.get(cand_key, {})
                    quick_ratio = float(quick.get("quick_ratio", 0.0) or 0.0)
                    size_overlap = float(quick.get("size_overlap_ratio", 0.0) or 0.0)
                    exact_tree = bool(quick.get("exact_tree"))
                    if (
                        str(cand.source).startswith("db_global_")
                        and not exact_tree
                        and quick_ratio <= 0.0
                        and size_overlap <= 0.0
                    ):
                        quick_prefilter_skipped += 1
                        row_out["quick_prefilter"]["skipped_candidates"].append(
                            {
                                "path": cand.path,
                                "source": cand.source,
                                "quick_ratio": quick_ratio,
                                "size_overlap_ratio": size_overlap,
                                "reason": "drop_global_zero_signal",
                            }
                        )
                        continue
                    source = str(cand.source or "")
                    if source.startswith("qb_same_name") and "_save:" in source and not exact_tree and quick_ratio < 0.05:
                        quick_prefilter_skipped += 1
                        row_out["quick_prefilter"]["skipped_candidates"].append(
                            {
                                "path": cand.path,
                                "source": cand.source,
                                "quick_ratio": quick_ratio,
                                "size_overlap_ratio": size_overlap,
                                "reason": "drop_qb_save_root_low_signal",
                            }
                        )
                        continue
                    filtered_ranked.append(item)
                # Use precision prefilter only when at least one stronger candidate remains.
                if filtered_ranked:
                    existing_ranked = filtered_ranked
                if args.skip_hash_if_a:
                    for item in existing_ranked:
                        cand = item[3]
                        cand_key = canonical_alias(cand.path)
                        quick = quick_by_path.get(cand_key, {})
                        if bool(quick.get("exact_tree")) and str(cand.source).startswith("db_self"):
                            existing_ranked = [item]
                            break
        if int(args.max_candidates) > 0:
            existing_ranked = existing_ranked[: int(args.max_candidates)]
        ordered = [item[3] for item in existing_ranked]
        row_out["candidates"] = [
            {
                "path": item[3].path,
                "source": item[3].source,
                "score": item[3].score,
                "adjusted_score": item[0],
                "affinity_score": item[1],
                "bad_fail_count": item[4],
                "bad_last_classification": item[5],
                "storage_root": storage_root_label(item[3].path),
                "quick_ratio": float(quick_by_path.get(canonical_alias(item[3].path), {}).get("quick_ratio", -1.0)),
                "size_overlap_ratio": float(quick_by_path.get(canonical_alias(item[3].path), {}).get("size_overlap_ratio", -1.0)),
                "exact_tree_quick": bool(quick_by_path.get(canonical_alias(item[3].path), {}).get("exact_tree", False)),
                "note": item[3].note,
            }
            for item in (existing_ranked if int(args.max_candidates) > 0 else ranked)
        ]

        existing_paths = [c.path for c in ordered]
        if not existing_paths:
            if row_out["filesystem_policy"]["skipped_candidates"]:
                row_out["status"] = "no_candidate_paths_after_filesystem_policy"
                filesystem_hashes_blocked += 1
            elif row_out["donor_policy"]["skipped_candidates"]:
                row_out["status"] = "no_candidate_paths_after_root_policy"
                root_policy_hashes_blocked += 1
            else:
                row_out["status"] = "no_candidate_paths_exist"
            row_out["classification"] = "e"
            class_counts["e"] += 1
            out_entries.append(row_out)
            write_progress_report(f"hash:{h}:no_candidate_paths_exist")
            continue

        if ordered:
            lead = ordered[0]
            lead_quick = quick_by_path.get(canonical_alias(lead.path), {})
            print(
                f"  candidate source={lead.source} "
                f"quick={float(lead_quick.get('quick_ratio', -1.0)):.4f} "
                f"size_overlap={float(lead_quick.get('size_overlap_ratio', -1.0)):.4f} "
                f"path={compact_path(lead.path)}"
            )

        verify_json = reports_dir / f"verify-{h}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        source_by_path = {c.path: c.source for c in ordered}
        verify_results: List[dict] = []
        verify_stdout_lines: List[str] = []
        verify_stderr_lines: List[str] = []
        stop_on_a_hit = False
        stop_requested_hash = False

        for cidx, p in enumerate(existing_paths, start=1):
            if stop_requested():
                stop_requested_hash = True
                stop_requested_global = True
                print(
                    f"status action=stop reason=stop_file_exists "
                    f"hash={h} candidate={cidx}/{len(existing_paths)} stop_file={stop_file_path}"
                )
                break
            verify_json_one = reports_dir / f"verify-{h}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{cidx:03d}.json"
            cmd = [
                str(verifier_python),
                str(verifier_script),
                "--torrent",
                str(torrent_file),
                "--timeout",
                str(float(args.verify_timeout)),
                "--poll",
                str(float(args.verify_poll)),
                "--json-out",
                str(verify_json_one),
                "--quiet-summary",
                "--path",
                p,
            ]
            if args.show_verify_progress:
                cmd.append("--show-progress")

            if args.show_verify_progress:
                proc = subprocess.Popen(cmd)
            else:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            terminated_for_stop = False
            poll_sleep = max(0.2, float(args.verify_poll))
            while proc.poll() is None:
                if stop_requested():
                    terminated_for_stop = True
                    stop_requested_hash = True
                    stop_requested_global = True
                    print(
                        f"status action=stop reason=stop_file_exists "
                        f"hash={h} candidate={cidx}/{len(existing_paths)} stop_file={stop_file_path} "
                        "detail=terminating_verify_subprocess"
                    )
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                    break
                time.sleep(poll_sleep)

            if not args.show_verify_progress:
                out, err = proc.communicate()
                out = str(out or "").strip()
                err = str(err or "").strip()
                if out:
                    verify_stdout_lines.append(out)
                if err:
                    verify_stderr_lines.append(err)

            if terminated_for_stop:
                break

            if not verify_json_one.exists():
                continue
            try:
                verify_obj_one = json.loads(verify_json_one.read_text(encoding="utf-8"))
            except Exception:
                continue
            one_results = list(verify_obj_one.get("results", []))
            if not one_results:
                continue
            verify_results.extend(one_results)

            if args.stop_on_a:
                one_best = one_results[0]
                one_path = str(one_best.get("path") or p)
                one_source = source_by_path.get(one_path, source_by_path.get(p, "unknown"))
                one_letter = classify_letter(one_best, one_source)
                if one_letter == "a":
                    stop_on_a_hit = True
                    print(
                        f"  stop_on_a hit at candidate={cidx}/{len(existing_paths)} source={one_source} "
                        f"path={compact_path(one_path)}"
                    )
                    break

        if stop_requested_hash:
            row_out["status"] = "stop_requested"
            row_out["detail"] = f"stop_file_exists:{stop_file_path}"
            row_out["verify_stdout"] = "\n".join(verify_stdout_lines)
            row_out["verify_stderr"] = "\n".join(verify_stderr_lines)
            row_out["verify_report_json"] = str(verify_json)
            row_out["verify_stop_on_a_hit"] = bool(stop_on_a_hit)
            row_out["verify_candidates_selected"] = int(len(existing_paths))
            row_out["verify_candidates_tested"] = int(len(verify_results))
            out_entries.append(row_out)
            write_progress_report(f"stop_file_exists:hash:{h}")
            flush_caches()
            break

        row_out["verify_stdout"] = "\n".join(verify_stdout_lines)
        row_out["verify_stderr"] = "\n".join(verify_stderr_lines)
        row_out["verify_report_json"] = str(verify_json)
        row_out["verify_stop_on_a_hit"] = bool(stop_on_a_hit)
        row_out["verify_candidates_selected"] = int(len(existing_paths))
        row_out["verify_candidates_tested"] = int(len(verify_results))

        verify_obj = {
            "tool": "qb-libtorrent-verify",
            "generated_at": ts_iso(),
            "torrent": str(torrent_file),
            "results": verify_results,
        }
        verify_json.write_text(json.dumps(verify_obj, indent=2) + "\n", encoding="utf-8")

        if not verify_results:
            row_out["status"] = "verify_empty"
            row_out["classification"] = "e"
            class_counts["e"] += 1
            out_entries.append(row_out)
            write_progress_report(f"hash:{h}:verify_empty")
            continue

        # Update bad-candidate cache for this hash.
        per_hash = dict(bad_cache.get(h, {}))
        tested_hash_meta = dict(tested_cache.get(h, {})) if isinstance(tested_cache.get(h, {}), dict) else {}
        tested_paths_map = dict(tested_hash_meta.get("paths", {})) if isinstance(tested_hash_meta.get("paths", {}), dict) else {}
        for vr in verify_results:
            path_key = canonical_alias(str(vr.get("path") or ""))
            if not path_key:
                continue
            prior_tested = tested_paths_map.get(path_key, {})
            next_tested = {
                "path": str(vr.get("path") or ""),
                "test_count": int(prior_tested.get("test_count", 0) or 0) + 1,
                "last_classification": str(vr.get("classification") or "no_match"),
                "last_ratio": float(vr.get("verify_ratio", 0.0) or 0.0),
                "last_state": str(vr.get("verify_state") or ""),
                "last_verified": bool(vr.get("verified")),
                "last_verify_reason": str(vr.get("verify_reason") or ""),
                "last_seen_checking_files": bool(vr.get("seen_checking_files", False)),
                "last_seen": ts_iso(),
            }
            if prior_tested != next_tested:
                tested_cache_updates += 1
            tested_paths_map[path_key] = next_tested
            verified = bool(vr.get("verified"))
            if verified:
                if path_key in per_hash:
                    del per_hash[path_key]
                    bad_cache_updates += 1
                continue
            prior = per_hash.get(path_key, {})
            next_meta = {
                "path": str(vr.get("path") or ""),
                "fail_count": int(prior.get("fail_count", 0) or 0) + 1,
                "last_classification": str(vr.get("classification") or "no_match"),
                "last_ratio": float(vr.get("verify_ratio", 0.0) or 0.0),
                "last_state": str(vr.get("verify_state") or ""),
                "last_seen": ts_iso(),
            }
            if prior != next_meta:
                bad_cache_updates += 1
            per_hash[path_key] = next_meta
        if per_hash:
            bad_cache[h] = per_hash
        elif h in bad_cache:
            del bad_cache[h]
            bad_cache_updates += 1

        tested_hash_meta["paths"] = tested_paths_map

        def rank(v: dict) -> Tuple[int, int, float, float, int]:
            cls = str(v.get("classification", ""))
            cls_rank = {"exact_tree": 3, "close_match": 2, "partial_match": 1, "no_match": 0}.get(cls, 0)
            path = str(v.get("path") or "")
            src = source_by_path.get(path, "unknown")
            src_rank = source_preference_rank(src)
            affinity = donor_affinity_score(path, target_save_path)
            return (
                1 if bool(v.get("verified")) else 0,
                cls_rank,
                affinity,
                float(v.get("verify_ratio", 0.0)),
                int(src_rank),
            )

        best = sorted(verify_results, key=rank, reverse=True)[0]
        best_path = str(best.get("path") or "")
        best_source = source_by_path.get(best_path, "unknown")
        target_ok, target_reason = root_policy_check(best_path, allowed_roots, forbidden_roots)
        if not target_ok and bool(best.get("verified")):
            row_out["status"] = "verified_donor_outside_target_roots"
            row_out["classification"] = "d"
            row_out["recommended_path"] = ""
            row_out["recommended_source"] = best_source
            row_out["best_result"] = best
            row_out["detail"] = target_reason
            row_out["repair_hint"] = {
                "action": "relink_or_copy_from_donor_to_target_root",
                "donor_path": best_path,
                "target_save_path": str(entry.get("save_path") or (row_qb.save_path if row_qb else "")),
                "target_root_policy": {
                    "allowed_roots": allowed_roots,
                    "forbidden_roots": forbidden_roots,
                },
            }
            class_counts["d"] += 1
            out_entries.append(row_out)
            flush_caches()
            write_progress_report(f"hash:{h}:analyzed:d:donor_outside_target_roots")
            print(
                f"  class=d best={best.get('classification')} verified={best.get('verified')} "
                f"reason={target_reason} source={best_source}"
            )
            continue
        letter = classify_letter(best, best_source)
        best_reason = str(best.get("verify_reason") or "")
        best_elapsed = float(best.get("verify_elapsed_s", 0.0) or 0.0)
        best_quick = float(best.get("quick_ratio", 0.0) or 0.0)
        best_size_overlap = float(best.get("size_overlap_ratio", 0.0) or 0.0)

        row_out["status"] = "analyzed"
        row_out["classification"] = letter
        row_out["recommended_path"] = best_path
        row_out["recommended_source"] = best_source
        row_out["best_result"] = best
        row_out["donor_insights"]["selected_best_storage_root"] = storage_root_label(best_path)
        row_out["donor_insights"]["verified_pool_candidate"] = bool(
            bool(best.get("verified")) and storage_root_label(best_path) == "pool"
        )
        class_counts[letter] += 1
        out_entries.append(row_out)

        if letter == "a" and bool(best.get("verified")):
            tested_hash_meta["solved_a"] = True
            tested_hash_meta["solved_a_trusted"] = bool(best.get("seen_checking_files", False))
            tested_hash_meta["solved_a_path"] = best_path
            tested_hash_meta["solved_a_seen"] = ts_iso()
        if tested_cache.get(h) != tested_hash_meta:
            tested_cache_updates += 1
        tested_cache[h] = tested_hash_meta

        flush_caches()
        write_progress_report(f"hash:{h}:analyzed:{letter}")
        print(
            f"  class={letter} best={best.get('classification')} "
            f"verified={best.get('verified')} ratio={float(best.get('verify_ratio', 0.0)):.6f} "
            f"quick={best_quick:.4f} size_overlap={best_size_overlap:.4f} "
            f"reason={best_reason} elapsed={best_elapsed:.1f}s source={best_source}"
        )

    conn.close()
    flush_caches()

    summary = write_progress_report("stop_file_exists" if stop_requested_global else "final")
    print(
        f"summary selected={summary['selected']} processed={summary['processed']} "
        f"a={summary['a']} b={summary['b']} c={summary['c']} d={summary['d']} e={summary['e']} "
        f"bad_entries={summary['bad_cache_entries']} bad_updates={summary['bad_cache_updates']} "
        f"bad_skipped={summary['bad_candidates_skipped']} "
        f"tested_hashes={summary['tested_cache_hashes']} tested_paths={summary['tested_cache_paths']} "
        f"tested_updates={summary['tested_cache_updates']} tested_skipped={summary['tested_candidates_skipped']} "
        f"solved_skipped={summary['solved_hashes_skipped']} live_skipped={summary['live_state_skipped']} "
        f"quick_prefilter_skipped={summary['quick_prefilter_skipped']} "
        f"ignored_hashes_skipped={summary['ignored_hashes_skipped']} "
        f"untrusted_verified_retests={summary['untrusted_verified_retests']} "
        f"tested_cache_fallback_retests={summary['tested_cache_fallback_retests']} "
        f"root_policy_candidates_skipped={summary['root_policy_candidates_skipped']} "
        f"root_policy_hashes_blocked={summary['root_policy_hashes_blocked']} "
        f"filesystem_candidates_skipped={summary['filesystem_candidates_skipped']} "
        f"filesystem_hashes_blocked={summary['filesystem_hashes_blocked']}"
    )
    print(f"report_json={report_path}")
    print(f"latest_json={latest_report_path}")
    print(f"bad_cache_json={bad_cache_path}")
    print(f"tested_cache_json={tested_cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
