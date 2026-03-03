#!/usr/bin/env python3
"""Standalone qB repair tool with strict manifest matching.

This intentionally does not depend on the existing rehome repair scripts.
It uses:
  - qB API (torrent states, file manifests, setLocation, recheck)
  - hashall catalog DB (files_* tables) only to discover candidate roots

Safety model:
  - Never delete or overwrite files
  - Build missing targets only via hardlinks
  - Enforce download protection after recheck
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import errno
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import QBitFile, QBitTorrent, get_qbittorrent_client


DEFAULT_DB = Path.home() / ".hashall" / "catalog.db"
DEFAULT_STATES = ("missingFiles", "stoppedDL")
DOWNLOAD_STATES = {"downloading", "stalleddl"}


@dataclass(frozen=True)
class ManifestEntry:
    rel_path: str
    size: int


@dataclass
class MatchResult:
    save_path: str
    matched_files: int
    matched_bytes: int
    total_files: int
    total_bytes: int
    complete: bool
    sample_missing: List[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fresh qB repair using strict manifest matching and hardlink reconstruction."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to hashall catalog DB")
    parser.add_argument(
        "--states",
        default=",".join(DEFAULT_STATES),
        help="Comma-separated qB states to target (default: missingFiles,stoppedDL)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max torrents to process (0=all)")
    parser.add_argument(
        "--mode",
        choices=("dryrun", "prepare", "apply"),
        default="dryrun",
        help="dryrun prints plan; prepare builds/rehomes only; apply performs pause/setLocation/recheck",
    )
    parser.add_argument(
        "--hashes",
        default="",
        help="Pipe/comma/space separated torrent hashes to process (overrides --states filter)",
    )
    parser.add_argument(
        "--hashes-file",
        default="",
        help="Optional file containing hashes (one per line, # comments allowed)",
    )
    parser.add_argument(
        "--anchors",
        type=int,
        default=3,
        help="Number of largest files to use for DB candidate discovery (default: 3)",
    )
    parser.add_argument(
        "--candidate-scan-limit",
        type=int,
        default=40,
        help="How many candidate save paths to full-verify per torrent (default: 40)",
    )
    parser.add_argument("--poll", type=float, default=3.0, help="Recheck poll interval seconds")
    parser.add_argument(
        "--heartbeat",
        type=float,
        default=10.0,
        help="Status print interval while waiting after recheck",
    )
    parser.add_argument(
        "--stuck-seconds",
        type=float,
        default=45.0,
        help="If stuck in stoppedDL with no change this long, do one pause+recheck recovery",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="Per-torrent wait timeout seconds after recheck",
    )
    parser.add_argument(
        "--max-anchor-hits-per-table",
        type=int,
        default=500,
        help="Limit SQL rows per anchor query per files_* table",
    )
    parser.add_argument(
        "--force-unique-root",
        action="store_true",
        help="Always rebuild to a per-hash unique root via hardlinks before setLocation/recheck",
    )
    parser.add_argument(
        "--unique-root-subdir",
        default="_qb-unique-repair",
        help="Subdirectory under the source mount base for forced unique roots",
    )
    parser.add_argument(
        "--quarantine-exclusive-root",
        dest="quarantine_exclusive_root",
        action="store_true",
        default=True,
        help="Before rebuilding links, rename target root to .bad.<ts>.<hash> when exclusive",
    )
    parser.add_argument(
        "--no-quarantine-exclusive-root",
        dest="quarantine_exclusive_root",
        action="store_false",
        help="Disable exclusive-root quarantine rename before rebuild",
    )
    parser.add_argument(
        "--report-json",
        default="",
        help="Optional JSON report path (default: ~/.logs/hashall/reports/qbit-triage/fresh-repair-<ts>.json)",
    )
    return parser.parse_args()


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def canonical_alias_key(path: str) -> str:
    p = str(path or "").strip()
    if p.startswith("/stash/media/"):
        return "/data/media/" + p[len("/stash/media/") :]
    if p == "/stash/media":
        return "/data/media"
    if p.startswith("/pool/data/seeds/"):
        return "/data/media/torrents/seeding/" + p[len("/pool/data/seeds/") :]
    if p == "/pool/data/seeds":
        return "/data/media/torrents/seeding"
    return p


def alias_variants(path: str) -> List[str]:
    p = str(path or "").strip().rstrip("/")
    if not p:
        return []
    out = [p]
    if p == "/data/media/torrents/seeding" or p.startswith("/data/media/torrents/seeding/"):
        suffix = p[len("/data/media/torrents/seeding") :]
        out.append("/stash/media/torrents/seeding" + suffix)
        out.append("/pool/data/seeds" + suffix)
    elif p == "/stash/media/torrents/seeding" or p.startswith("/stash/media/torrents/seeding/"):
        suffix = p[len("/stash/media/torrents/seeding") :]
        out.append("/data/media/torrents/seeding" + suffix)
        out.append("/pool/data/seeds" + suffix)
    elif p == "/pool/data/seeds" or p.startswith("/pool/data/seeds/"):
        suffix = p[len("/pool/data/seeds") :]
        out.append("/data/media/torrents/seeding" + suffix)
        out.append("/stash/media/torrents/seeding" + suffix)
    elif p == "/data/media" or p.startswith("/data/media/"):
        out.append("/stash/media" + p[len("/data/media") :])
    elif p == "/stash/media" or p.startswith("/stash/media/"):
        out.append("/data/media" + p[len("/stash/media") :])
    deduped: List[str] = []
    seen = set()
    for cand in out:
        if cand and cand not in seen:
            seen.add(cand)
            deduped.append(cand)
    return deduped


def dedupe_paths(paths: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in paths:
        p = str(raw or "").strip().rstrip("/")
        if not p:
            continue
        key = canonical_alias_key(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def torrent_manifest(entries: Sequence[QBitFile]) -> List[ManifestEntry]:
    out: List[ManifestEntry] = []
    for f in entries:
        rel = str(f.name or "").strip().lstrip("/")
        if not rel:
            continue
        out.append(ManifestEntry(rel_path=rel, size=int(f.size or 0)))
    return out


def manifest_signature(manifest: Sequence[ManifestEntry]) -> Tuple[Tuple[str, int], ...]:
    return tuple((m.rel_path, int(m.size)) for m in manifest)


def manifest_signature_ignoreroot(manifest: Sequence[ManifestEntry]) -> Tuple[Tuple[str, int], ...]:
    out: List[Tuple[str, int]] = []
    for m in manifest:
        rel = str(m.rel_path or "")
        if "/" in rel:
            rel = rel.split("/", 1)[1]
        out.append((rel, int(m.size)))
    return tuple(out)


def manifest_relpath_map_ignoreroot(
    target_manifest: Sequence[ManifestEntry],
    source_manifest: Sequence[ManifestEntry],
) -> Optional[Dict[str, str]]:
    source_by_key: Dict[Tuple[str, int], List[str]] = defaultdict(list)
    for m in source_manifest:
        rel = str(m.rel_path or "")
        rel_key = rel.split("/", 1)[1] if "/" in rel else rel
        source_by_key[(rel_key, int(m.size))].append(rel)

    mapping: Dict[str, str] = {}
    for m in target_manifest:
        target_rel = str(m.rel_path or "")
        rel_key = target_rel.split("/", 1)[1] if "/" in target_rel else target_rel
        cands = source_by_key.get((rel_key, int(m.size)), [])
        if len(cands) != 1:
            return None
        mapping[target_rel] = cands[0]
    return mapping


def manifest_totals(manifest: Sequence[ManifestEntry]) -> Tuple[int, int]:
    total_files = len(manifest)
    total_bytes = int(sum(int(m.size) for m in manifest))
    return total_files, total_bytes


def is_single_file_manifest(manifest: Sequence[ManifestEntry]) -> bool:
    return len(manifest) == 1 and "/" not in manifest[0].rel_path


def derive_root_name(manifest: Sequence[ManifestEntry], fallback_name: str) -> str:
    if not manifest:
        return str(fallback_name or "").strip()
    first = manifest[0].rel_path
    if "/" in first:
        return first.split("/", 1)[0]
    return first


def normalize_qb_save_path(raw_save: str, root_name: str, manifest: Sequence[ManifestEntry]) -> str:
    save = str(raw_save or "").strip().rstrip("/")
    if not save.startswith("/"):
        return save
    p = Path(save)
    # Corrupted entries sometimes store save_path including root/file name.
    if root_name and p.name == root_name:
        return str(p.parent)
    if is_single_file_manifest(manifest):
        rel_name = manifest[0].rel_path
        if rel_name and p.name == rel_name:
            return str(p.parent)
    return save


def target_root_path(save_path: str, manifest: Sequence[ManifestEntry], root_name: str) -> Tuple[str, bool]:
    save = str(save_path or "").strip().rstrip("/")
    if not save.startswith("/") or not manifest:
        return save, True
    if is_single_file_manifest(manifest):
        return str(Path(save) / manifest[0].rel_path), False
    root = str(root_name or "").strip()
    if not root:
        root = manifest[0].rel_path.split("/", 1)[0]
    return str(Path(save) / root), True


def path_matches_root(candidate_path: str, root_path: str, is_dir: bool) -> bool:
    cand = canonical_alias_key(str(candidate_path or "").strip().rstrip("/"))
    root = canonical_alias_key(str(root_path or "").strip().rstrip("/"))
    if not cand or not root:
        return False
    if cand == root:
        return True
    if is_dir:
        return cand.startswith(root + "/")
    return False


def find_root_users(
    root_path: str,
    is_dir: bool,
    owner_hash: str,
    qb_torrents: Sequence[QBitTorrent],
    db_instances: Sequence[sqlite3.Row],
) -> Dict[str, object]:
    owner = str(owner_hash or "").lower().strip()
    users: List[Dict[str, str]] = []
    seen = set()

    for t in qb_torrents:
        h = str(t.hash or "").lower().strip()
        if not h or h == owner:
            continue
        matched_path = ""
        for cand in (str(t.content_path or ""), str(t.save_path or "")):
            if path_matches_root(cand, root_path, is_dir):
                matched_path = str(cand or "")
                break
        if not matched_path:
            continue
        key = ("qb", h)
        if key in seen:
            continue
        seen.add(key)
        users.append(
            {
                "source": "qb",
                "hash": h,
                "state": str(t.state or ""),
                "path": matched_path,
            }
        )

    for row in db_instances:
        h = str(row["torrent_hash"] or "").lower().strip()
        if not h or h == owner:
            continue
        save = str(row["save_path"] or "").strip()
        root_name = str(row["root_name"] or "").strip()
        candidates = [save]
        if save and root_name:
            candidates.append(str(Path(save) / root_name))
        matched_path = ""
        for cand in candidates:
            if path_matches_root(cand, root_path, is_dir):
                matched_path = cand
                break
        if not matched_path:
            continue
        key = ("db", h)
        if key in seen:
            continue
        seen.add(key)
        users.append(
            {
                "source": "db",
                "hash": h,
                "state": "",
                "path": matched_path,
            }
        )

    return {"exclusive": len(users) == 0, "users": users}


def quarantine_root(root_path: str, owner_hash: str) -> str:
    p = Path(root_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f".bad.{stamp}.{str(owner_hash or '').lower()[:12]}"
    candidate = Path(str(p) + suffix)
    n = 1
    while candidate.exists():
        candidate = Path(str(p) + suffix + f".{n}")
        n += 1
    p.rename(candidate)
    return str(candidate)


def check_manifest_on_fs(save_path: str, manifest: Sequence[ManifestEntry]) -> MatchResult:
    save = Path(save_path)
    total_files, total_bytes = manifest_totals(manifest)
    matched_files = 0
    matched_bytes = 0
    missing: List[str] = []
    for m in manifest:
        fp = save / m.rel_path
        try:
            st = fp.stat()
        except FileNotFoundError:
            if len(missing) < 5:
                missing.append(m.rel_path)
            continue
        except OSError:
            if len(missing) < 5:
                missing.append(m.rel_path)
            continue
        if fp.is_file() and int(st.st_size) == int(m.size):
            matched_files += 1
            matched_bytes += int(m.size)
        else:
            if len(missing) < 5:
                missing.append(m.rel_path)
    return MatchResult(
        save_path=str(save),
        matched_files=matched_files,
        matched_bytes=matched_bytes,
        total_files=total_files,
        total_bytes=total_bytes,
        complete=(matched_files == total_files and matched_bytes == total_bytes),
        sample_missing=missing,
    )


def parse_hash_input(raw: str, file_path: str) -> List[str]:
    chunks: List[str] = []
    if raw:
        chunks.extend(raw.replace("|", " ").replace(",", " ").split())
    if file_path:
        for line in Path(file_path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            chunks.extend(line.replace("|", " ").replace(",", " ").split())
    out: List[str] = []
    seen = set()
    for c in chunks:
        h = c.strip().lower()
        if len(h) != 40:
            continue
        if h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out


def discover_files_tables(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
    mounts = {
        str(r[0]): str(r[1] or "").strip()
        for r in conn.execute("SELECT device_id, mount_point FROM devices")
    }
    out: List[Tuple[str, str]] = []
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'files_%'"
    ):
        suffix = str(name).split("_", 1)[1]
        mount = mounts.get(suffix, "")
        if mount.startswith("/"):
            out.append((str(name), mount.rstrip("/")))
    return out


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def anchor_candidates_from_db(
    conn: sqlite3.Connection,
    table_mounts: Sequence[Tuple[str, str]],
    anchors: Sequence[ManifestEntry],
    max_hits_per_table: int,
    cache: Dict[Tuple[str, int], List[str]],
) -> Counter:
    counts: Counter = Counter()
    for anchor in anchors:
        cache_key = (anchor.rel_path, int(anchor.size))
        if cache_key in cache:
            for save in cache[cache_key]:
                counts[save] += 1
            continue

        this_anchor_saves: List[str] = []
        rel = anchor.rel_path
        like_pat = "%/" + rel
        rel_len = len(rel)
        for table, mount in table_mounts:
            q = (
                f"SELECT path FROM {quote_ident(table)} "
                "WHERE status='active' AND size=? AND (path=? OR path LIKE ?) "
                "LIMIT ?"
            )
            for (row_path,) in conn.execute(q, (int(anchor.size), rel, like_pat, int(max_hits_per_table))):
                rp = str(row_path or "").strip().rstrip("/")
                if not rp:
                    continue
                if rp == rel:
                    save_rel = ""
                elif rp.endswith("/" + rel):
                    save_rel = rp[: -(rel_len + 1)].rstrip("/")
                else:
                    continue
                if save_rel:
                    abs_save = str(Path(mount) / save_rel)
                else:
                    abs_save = mount
                this_anchor_saves.append(abs_save.rstrip("/"))

        cache[cache_key] = this_anchor_saves
        for save in this_anchor_saves:
            counts[save] += 1
    return counts


def choose_qb_location(target_save: str, current_save: str) -> str:
    target_vars = alias_variants(target_save) or [target_save]
    cur = str(current_save or "").strip()
    if cur.startswith("/data/media"):
        for cand in target_vars:
            if cand.startswith("/data/media"):
                return cand
    if cur.startswith("/stash/media"):
        for cand in target_vars:
            if cand.startswith("/stash/media"):
                return cand
    if cur.startswith("/pool/data/seeds"):
        for cand in target_vars:
            if cand.startswith("/pool/data/seeds"):
                return cand
    for cand in target_vars:
        if Path(cand).exists():
            return cand
    return target_vars[0]


def choose_unique_target_save(source_save: str, torrent_hash: str, unique_subdir: str) -> str:
    src = str(source_save or "").strip().rstrip("/")
    subdir = str(unique_subdir or "_qb-unique-repair").strip().strip("/")
    if not subdir:
        subdir = "_qb-unique-repair"
    if not src:
        src = "/data/media/torrents/seeding"
    bases = [
        "/data/media/torrents/seeding",
        "/stash/media/torrents/seeding",
        "/pool/data/seeds",
    ]
    for base in bases:
        if src == base or src.startswith(base + "/"):
            return str(Path(base) / subdir / torrent_hash)
    return str(Path(src) / subdir / torrent_hash)


def pick_source_candidate(
    ranked: Sequence[Tuple[str, int]],
    current_candidates: Sequence[str],
) -> Optional[str]:
    if not ranked:
        return None
    current_keys = {canonical_alias_key(p) for p in current_candidates}
    for save, _hits in ranked:
        if canonical_alias_key(save) in current_keys:
            return save
    return ranked[0][0]


def path_device_token(path: str) -> Optional[int]:
    p = Path(str(path or "").strip())
    while True:
        try:
            st = p.stat()
            return int(st.st_dev)
        except FileNotFoundError:
            if p.parent == p:
                return None
            p = p.parent
            continue
        except OSError:
            return None


def hardlink_build(
    source_save: str,
    target_save: str,
    manifest: Sequence[ManifestEntry],
    source_rel_map: Optional[Dict[str, str]] = None,
) -> Tuple[bool, Dict[str, int], str]:
    created = 0
    existed = 0
    source_missing = 0
    conflict = 0
    cross_device = 0

    src_base = Path(source_save)
    dst_base = Path(target_save)
    for m in manifest:
        source_rel = str(m.rel_path)
        if source_rel_map is not None:
            source_rel = str(source_rel_map.get(source_rel, source_rel))
        src = src_base / source_rel
        dst = dst_base / m.rel_path

        try:
            src_stat = src.stat()
        except FileNotFoundError:
            source_missing += 1
            continue
        except OSError:
            source_missing += 1
            continue

        if not src.is_file() or int(src_stat.st_size) != int(m.size):
            source_missing += 1
            continue

        if dst.exists():
            try:
                dst_stat = dst.stat()
            except OSError:
                conflict += 1
                continue
            if dst.is_file() and int(dst_stat.st_size) == int(m.size):
                existed += 1
                continue
            conflict += 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(str(src), str(dst))
            created += 1
        except OSError as e:
            if e.errno == errno.EXDEV:
                cross_device += 1
            else:
                conflict += 1

    ok = source_missing == 0 and conflict == 0 and cross_device == 0
    msg = (
        f"created={created} existed={existed} source_missing={source_missing} "
        f"conflict={conflict} cross_device={cross_device}"
    )
    return ok, {
        "created": created,
        "existed": existed,
        "source_missing": source_missing,
        "conflict": conflict,
        "cross_device": cross_device,
    }, msg


def wait_recheck_terminal(
    qb,
    torrent_hash: str,
    poll_s: float,
    timeout_s: float,
    heartbeat_s: float = 10.0,
    stuck_s: float = 45.0,
) -> Tuple[bool, str, Dict[str, object]]:
    deadline = time.monotonic() + timeout_s
    timeout_extended = False
    timeout_grace_s = max(60.0, min(300.0, float(timeout_s)))
    history: List[str] = []
    last_hb = 0.0
    last_signature: Optional[Tuple[str, float, int]] = None
    last_change = time.monotonic()
    recovery_attempted = False
    while True:
        info = qb.get_torrent_info(torrent_hash)
        if info is None:
            return False, "missing_torrent_info", {"history": history[-10:]}

        now = time.monotonic()
        state = str(info.state or "").lower()
        progress = float(info.progress or 0.0)
        amount_left = int(info.amount_left or 0)
        history.append(f"{state}:{progress:.4f}:{amount_left}")
        signature = (state, round(progress, 4), amount_left)
        if signature != last_signature:
            last_signature = signature
            last_change = now

        if (now - last_hb) >= max(1.0, heartbeat_s):
            elapsed = int(timeout_s - max(0.0, deadline - now))
            print(
                f"  wait state={state} progress={progress:.4f} "
                f"left={amount_left} elapsed_s={elapsed}"
            )
            last_hb = now

        if state.startswith("checking") or "moving" in state:
            pass
        elif state in DOWNLOAD_STATES and amount_left > 0:
            qb.pause_torrent(torrent_hash)
            return False, f"download_protection_triggered:{state}", {
                "state": state,
                "progress": progress,
                "amount_left": amount_left,
                "history": history[-10:],
            }
        elif state == "missingfiles":
            return False, "still_missing_files", {
                "state": state,
                "progress": progress,
                "amount_left": amount_left,
                "history": history[-10:],
            }
        elif progress >= 0.9999 and amount_left == 0:
            return True, "complete", {
                "state": state,
                "progress": progress,
                "amount_left": amount_left,
                "history": history[-10:],
            }
        elif state == "stoppeddl" and amount_left > 0 and (now - last_change) >= max(10.0, stuck_s):
            if not recovery_attempted:
                print("  recovery action=pause_recheck")
                if not qb.pause_torrent(torrent_hash):
                    return False, "recovery_pause_failed", {"history": history[-10:]}
                if not qb.recheck_torrent(torrent_hash):
                    return False, "recovery_recheck_failed", {"history": history[-10:]}
                recovery_attempted = True
                last_change = now
                continue
            return False, "stuck_terminal_after_recovery", {"history": history[-10:]}

        if now >= deadline:
            if not timeout_extended and (state.startswith("checking") or "moving" in state):
                timeout_extended = True
                deadline = now + timeout_grace_s
                print(
                    "  timeout grace extended "
                    f"state={state} extra_s={int(timeout_grace_s)}"
                )
                continue
            return False, "timeout_wait_terminal", {"history": history[-10:]}
        time.sleep(max(0.5, poll_s))


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"ERROR db_not_found path={db_path}")
        return 2

    requested_hashes = parse_hash_input(args.hashes, args.hashes_file)
    states = [s.strip() for s in str(args.states).split(",") if s.strip()]
    if not states and not requested_hashes:
        states = list(DEFAULT_STATES)

    qb = get_qbittorrent_client()
    if not qb.test_connection():
        print(f"ERROR qb_connection_failed detail={qb.last_error}")
        return 2
    if not qb.login():
        print(f"ERROR qb_login_failed detail={qb.last_error}")
        return 2

    all_torrents = qb.get_torrents()
    by_hash = {str(t.hash or "").lower(): t for t in all_torrents}
    torrents_by_name: Dict[str, List[QBitTorrent]] = defaultdict(list)
    for t in all_torrents:
        torrents_by_name[str(t.name or "")].append(t)
    complete_by_size: Dict[int, List[QBitTorrent]] = defaultdict(list)
    for t in all_torrents:
        if float(t.progress or 0.0) < 0.9999 or int(t.amount_left or 0) > 0:
            continue
        st = str(t.state or "").lower()
        if st in {"missingfiles", "downloading", "stalleddl"}:
            continue
        complete_by_size[int(t.size or 0)].append(t)
    if requested_hashes:
        selected = [by_hash[h] for h in requested_hashes if h in by_hash]
    else:
        wanted = set(states)
        selected = [t for t in all_torrents if str(t.state or "") in wanted]
    selected = sorted(selected, key=lambda t: (str(t.state), str(t.name), str(t.hash)))
    if int(args.limit) > 0:
        selected = selected[: int(args.limit)]

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    table_mounts = discover_files_tables(conn)
    anchor_cache: Dict[Tuple[str, int], List[str]] = {}
    peer_manifest_cache: Dict[str, Tuple[Tuple[str, int], ...]] = {}
    peer_manifest_ignoreroot_cache: Dict[str, Tuple[Tuple[str, int], ...]] = {}
    peer_manifest_entries_cache: Dict[str, List[ManifestEntry]] = {}
    source_rel_map_by_hash: Dict[str, Dict[str, str]] = {}
    db_instances = list(
        conn.execute("SELECT torrent_hash, save_path, root_name FROM torrent_instances")
    )

    report = {
        "generated_at": now_ts(),
        "mode": args.mode,
        "db_path": str(db_path),
        "states_filter": states,
        "requested_hash_count": len(requested_hashes),
        "selected": len(selected),
        "results": [],
        "summary": {},
    }

    print(
        f"fresh_repair start ts={now_ts()} mode={args.mode} selected={len(selected)} "
        f"states={','.join(states) if states else 'hashes_only'}"
    )

    summary = Counter()
    for idx, tor in enumerate(selected, start=1):
        h = str(tor.hash or "").lower()
        info = qb.get_torrent_info(h) or tor
        files = qb.get_torrent_files(h)
        manifest = torrent_manifest(files)
        target_sig = manifest_signature(manifest)
        target_sig_ignoreroot = manifest_signature_ignoreroot(manifest)
        total_files, total_bytes = manifest_totals(manifest)
        root_name = derive_root_name(manifest, info.name)
        source_rel_map_by_hash.pop(h, None)

        row = {
            "idx": idx,
            "hash": h,
            "name": str(info.name or ""),
            "state_before": str(info.state or ""),
            "progress_before": float(info.progress or 0.0),
            "amount_left_before": int(info.amount_left or 0),
            "save_path_before": str(info.save_path or ""),
            "content_path_before": str(info.content_path or ""),
            "manifest_files": total_files,
            "manifest_bytes": total_bytes,
            "root_name": root_name,
            "action": "",
            "status": "",
            "reason": "",
            "source_save": "",
            "target_save": "",
            "qb_location": "",
        }

        print(
            f"[{idx}/{len(selected)}] hash={h[:12]} state={row['state_before']} "
            f"files={total_files} bytes={total_bytes}"
        )

        if not manifest:
            row["status"] = "error"
            row["reason"] = "empty_manifest"
            summary["error"] += 1
            report["results"].append(row)
            print(f"  error empty_manifest")
            continue

        current_candidates = dedupe_paths(
            [
                normalize_qb_save_path(str(info.save_path or ""), root_name, manifest),
                str(Path(str(info.content_path or "")).parent),
            ]
            + alias_variants(normalize_qb_save_path(str(info.save_path or ""), root_name, manifest))
            + alias_variants(str(Path(str(info.content_path or "")).parent))
        )

        peer_counter: Counter = Counter()
        peer_reason_by_save: Dict[str, str] = {}
        peer_relmap_by_save: Dict[str, Dict[str, str]] = {}

        def consider_peer(peer: QBitTorrent) -> None:
            peer_hash = str(peer.hash or "").lower()
            if not peer_hash or peer_hash == h:
                return
            peer_manifest = peer_manifest_entries_cache.get(peer_hash)
            if peer_manifest is None:
                peer_manifest = torrent_manifest(qb.get_torrent_files(peer_hash))
                peer_manifest_entries_cache[peer_hash] = peer_manifest
            peer_sig = peer_manifest_cache.get(peer_hash)
            if peer_sig is None:
                peer_sig = manifest_signature(peer_manifest)
                peer_manifest_cache[peer_hash] = peer_sig
            peer_root = derive_root_name(peer_manifest, str(peer.name or ""))
            peer_save = normalize_qb_save_path(str(peer.save_path or ""), peer_root, peer_manifest)
            if not peer_save.startswith("/"):
                return

            if peer_sig == target_sig:
                peer_counter[peer_save] += 1
                if peer_reason_by_save.get(peer_save) != "peer_manifest_exact":
                    peer_reason_by_save[peer_save] = "peer_manifest_exact"
                return

            peer_sig_ignoreroot = peer_manifest_ignoreroot_cache.get(peer_hash)
            if peer_sig_ignoreroot is None:
                peer_sig_ignoreroot = manifest_signature_ignoreroot(peer_manifest)
                peer_manifest_ignoreroot_cache[peer_hash] = peer_sig_ignoreroot
            if peer_sig_ignoreroot != target_sig_ignoreroot:
                return

            rel_map = manifest_relpath_map_ignoreroot(manifest, peer_manifest)
            if rel_map is None:
                return
            peer_counter[peer_save] += 1
            peer_reason_by_save.setdefault(peer_save, "peer_manifest_ignoreroot")
            peer_relmap_by_save.setdefault(peer_save, rel_map)

        # First pass: same-name peers (cheap/high confidence).
        for peer in torrents_by_name.get(str(info.name or ""), []):
            consider_peer(peer)

        # Second pass: all complete peers with same total size.
        if not peer_counter:
            for peer in complete_by_size.get(int(info.size or total_bytes), []):
                consider_peer(peer)

        peer_ranked: List[Tuple[str, int]] = sorted(
            peer_counter.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )
        preferred_peer_source = (
            pick_source_candidate(peer_ranked, current_candidates) if peer_ranked else None
        )
        preferred_peer_reason = (
            str(peer_reason_by_save.get(preferred_peer_source, ""))
            if preferred_peer_source
            else ""
        )
        preferred_peer_rel_map = (
            peer_relmap_by_save.get(preferred_peer_source)
            if preferred_peer_source
            else None
        )

        full_current_match: Optional[MatchResult] = None
        for cand in current_candidates:
            mr = check_manifest_on_fs(cand, manifest)
            if mr.complete:
                full_current_match = mr
                break

        if full_current_match is not None:
            target_save = full_current_match.save_path
            if (
                str(info.state or "").lower() == "stoppeddl"
                and int(info.amount_left or 0) > 0
                and preferred_peer_source
                and canonical_alias_key(preferred_peer_source) != canonical_alias_key(target_save)
            ):
                row["source_save"] = preferred_peer_source
                row["target_save"] = preferred_peer_source
                row["qb_location"] = choose_qb_location(preferred_peer_source, str(info.save_path or ""))
                row["action"] = "set_location_recheck"
                row["reason"] = (
                    f"peer_manifest_override_stoppeddl:{preferred_peer_reason or 'unknown'}"
                )
                if preferred_peer_rel_map is not None:
                    source_rel_map_by_hash[h] = preferred_peer_rel_map
                    row["source_rel_map_count"] = len(preferred_peer_rel_map)
            else:
                qb_location = choose_qb_location(target_save, str(info.save_path or ""))
                row["source_save"] = target_save
                row["target_save"] = target_save
                row["qb_location"] = qb_location
                if canonical_alias_key(qb_location) == canonical_alias_key(str(info.save_path or "")):
                    row["action"] = "recheck_only"
                else:
                    row["action"] = "set_location_recheck"
        else:
            if peer_ranked:
                source_save = pick_source_candidate(peer_ranked, current_candidates) or peer_ranked[0][0]
                row["source_save"] = source_save
                row["target_save"] = source_save
                row["qb_location"] = choose_qb_location(source_save, str(info.save_path or ""))
                row["action"] = "set_location_recheck"
                row["reason"] = str(peer_reason_by_save.get(source_save, "peer_manifest_source"))
                source_rel_map = peer_relmap_by_save.get(source_save)
                if source_rel_map is not None:
                    source_rel_map_by_hash[h] = source_rel_map
                    row["source_rel_map_count"] = len(source_rel_map)
            else:
                anchors = sorted(manifest, key=lambda m: m.size, reverse=True)[: max(1, int(args.anchors))]
                anchor_hits = anchor_candidates_from_db(
                    conn,
                    table_mounts,
                    anchors,
                    int(args.max_anchor_hits_per_table),
                    anchor_cache,
                )
                ranked = sorted(anchor_hits.items(), key=lambda kv: (-int(kv[1]), kv[0]))
                ranked = ranked[: max(1, int(args.candidate_scan_limit))]

                full_candidates: List[Tuple[str, int]] = []
                for save, hits in ranked:
                    mr = check_manifest_on_fs(save, manifest)
                    if mr.complete:
                        full_candidates.append((save, int(hits)))

                if not full_candidates:
                    row["status"] = "error"
                    row["reason"] = "no_full_manifest_candidate"
                    row["candidate_anchor_hits"] = [
                        {"save_path": save, "hits": hits} for save, hits in ranked[:10]
                    ]
                    summary["error"] += 1
                    report["results"].append(row)
                    print(f"  error no_full_manifest_candidate")
                    continue

                source_save = pick_source_candidate(full_candidates, current_candidates) or full_candidates[0][0]
                target_save = normalize_qb_save_path(str(info.save_path or ""), root_name, manifest)
                if not target_save.startswith("/"):
                    target_save = source_save
                qb_location = choose_qb_location(target_save, str(info.save_path or ""))
                row["source_save"] = source_save
                row["target_save"] = target_save
                row["qb_location"] = qb_location

                target_match = check_manifest_on_fs(target_save, manifest)
                if target_match.complete:
                    row["action"] = "set_location_recheck"
                else:
                    target_dev = path_device_token(target_save)
                    same_dev = []
                    if target_dev is not None:
                        for save, hits in full_candidates:
                            if path_device_token(save) == target_dev:
                                same_dev.append((save, hits))
                    if same_dev:
                        source_save = pick_source_candidate(same_dev, current_candidates) or same_dev[0][0]
                        row["source_save"] = source_save
                        row["action"] = "build_links_set_location_recheck"
                    else:
                        # Hardlinks cannot cross filesystems. Fall back to direct setLocation.
                        row["target_save"] = row["source_save"]
                        row["qb_location"] = choose_qb_location(row["target_save"], str(info.save_path or ""))
                        row["action"] = "set_location_recheck"
                        row["reason"] = "cross_device_build_fallback"

        if bool(args.force_unique_root):
            source_for_unique = (
                str(row.get("source_save") or "").strip()
                or str(row.get("target_save") or "").strip()
            )
            if not source_for_unique.startswith("/"):
                row["status"] = "error"
                row["reason"] = "force_unique_root_missing_source"
                summary["error"] += 1
                report["results"].append(row)
                print(f"  error {row['reason']}")
                continue
            unique_target = choose_unique_target_save(
                source_for_unique,
                h,
                str(args.unique_root_subdir),
            )
            row["source_save"] = source_for_unique
            row["target_save"] = unique_target
            row["qb_location"] = choose_qb_location(unique_target, str(info.save_path or ""))
            row["action"] = "build_links_set_location_recheck"
            row["reason"] = "force_unique_root"

        if args.mode == "dryrun":
            row["status"] = "planned"
            row["reason"] = row["action"]
            summary["planned"] += 1
            report["results"].append(row)
            print(
                f"  plan action={row['action']} source={row['source_save']} "
                f"target={row['target_save']} qb_location={row['qb_location']}"
            )
            continue

        if args.mode == "prepare":
            if row["action"] == "build_links_set_location_recheck":
                if bool(args.quarantine_exclusive_root):
                    t_root, t_is_dir = target_root_path(row["target_save"], manifest, root_name)
                    row["target_root_path"] = t_root
                    row["target_root_type"] = "dir" if t_is_dir else "file"
                    if t_root.startswith("/") and Path(t_root).exists():
                        usage = find_root_users(
                            t_root,
                            t_is_dir,
                            h,
                            all_torrents,
                            db_instances,
                        )
                        row["target_root_users"] = usage.get("users", [])[:30]
                        if bool(usage.get("exclusive")):
                            renamed_to = quarantine_root(t_root, h)
                            row["quarantined_root_from"] = t_root
                            row["quarantined_root_to"] = renamed_to
                            print(f"  quarantine root={t_root} -> {renamed_to}")
                        else:
                            print(
                                "  quarantine skipped shared_root "
                                f"users={len(list(usage.get('users', [])))} root={t_root}"
                            )
                    else:
                        print(f"  quarantine skipped missing_root root={t_root}")

                source_rel_map = source_rel_map_by_hash.get(h)
                ok, build_stats, build_msg = hardlink_build(
                    row["source_save"],
                    row["target_save"],
                    manifest,
                    source_rel_map,
                )
                row["build_stats"] = build_stats
                if not ok:
                    row["status"] = "error"
                    row["reason"] = f"prepare_build_failed:{build_msg}"
                    summary["error"] += 1
                    report["results"].append(row)
                    print(f"  error {row['reason']}")
                    continue
                print(f"  build {build_msg}")
            row["status"] = "prepared"
            row["reason"] = row["action"]
            summary["prepared"] += 1
            report["results"].append(row)
            print(
                f"  prepared action={row['action']} source={row['source_save']} "
                f"target={row['target_save']} qb_location={row['qb_location']}"
            )
            continue

        # apply mode
        if not qb.pause_torrent(h):
            row["status"] = "error"
            row["reason"] = f"pause_failed:{qb.last_error or 'unknown'}"
            summary["error"] += 1
            report["results"].append(row)
            print(f"  error {row['reason']}")
            continue

        if row["action"] == "build_links_set_location_recheck":
            if bool(args.quarantine_exclusive_root):
                t_root, t_is_dir = target_root_path(row["target_save"], manifest, root_name)
                row["target_root_path"] = t_root
                row["target_root_type"] = "dir" if t_is_dir else "file"
                if t_root.startswith("/") and Path(t_root).exists():
                    usage = find_root_users(
                        t_root,
                        t_is_dir,
                        h,
                        all_torrents,
                        db_instances,
                    )
                    row["target_root_users"] = usage.get("users", [])[:30]
                    if bool(usage.get("exclusive")):
                        renamed_to = quarantine_root(t_root, h)
                        row["quarantined_root_from"] = t_root
                        row["quarantined_root_to"] = renamed_to
                        print(f"  quarantine root={t_root} -> {renamed_to}")
                    else:
                        print(
                            "  quarantine skipped shared_root "
                            f"users={len(list(usage.get('users', [])))} root={t_root}"
                        )
                else:
                    print(f"  quarantine skipped missing_root root={t_root}")

            source_rel_map = source_rel_map_by_hash.get(h)
            ok, build_stats, build_msg = hardlink_build(
                row["source_save"],
                row["target_save"],
                manifest,
                source_rel_map,
            )
            row["build_stats"] = build_stats
            if not ok:
                # Hardlinks cannot cross filesystems. Fall back to source location directly.
                if (
                    int(build_stats.get("cross_device", 0)) > 0
                    and int(build_stats.get("source_missing", 0)) == 0
                    and int(build_stats.get("conflict", 0)) == 0
                ):
                    row["build_fallback"] = "cross_device_set_location_source"
                    row["qb_location"] = choose_qb_location(row["source_save"], str(info.save_path or ""))
                    row["action"] = "set_location_recheck"
                    print(
                        "  build fallback action=set_location_recheck "
                        f"reason=cross_device source={row['source_save']}"
                    )
                else:
                    row["status"] = "error"
                    row["reason"] = f"build_failed:{build_msg}"
                    summary["error"] += 1
                    report["results"].append(row)
                    print(f"  error {row['reason']}")
                    continue
            print(f"  build {build_msg}")

        if canonical_alias_key(row["qb_location"]) != canonical_alias_key(str(info.save_path or "")):
            if not qb.set_location(h, row["qb_location"]):
                row["status"] = "error"
                row["reason"] = f"set_location_failed:{qb.last_error or 'unknown'}"
                summary["error"] += 1
                report["results"].append(row)
                print(f"  error {row['reason']}")
                continue
            print(f"  set_location ok location={row['qb_location']}")
        else:
            print("  set_location skipped alias-equivalent")

        if not qb.recheck_torrent(h):
            row["status"] = "error"
            row["reason"] = f"recheck_failed:{qb.last_error or 'unknown'}"
            summary["error"] += 1
            report["results"].append(row)
            print(f"  error {row['reason']}")
            continue
        print("  recheck started")

        ok, reason, detail = wait_recheck_terminal(
            qb,
            h,
            float(args.poll),
            float(args.timeout),
            float(args.heartbeat),
            float(args.stuck_seconds),
        )
        row["terminal_detail"] = detail
        if ok:
            row["status"] = "ok"
            row["reason"] = reason
            summary["ok"] += 1
            print(f"  ok terminal={reason} state={detail.get('state','')}")
        else:
            row["status"] = "error"
            row["reason"] = reason
            summary["error"] += 1
            print(f"  error terminal={reason}")
        report["results"].append(row)

    conn.close()

    report["summary"] = dict(summary)
    report["summary"]["selected"] = len(selected)
    report["summary"]["mode"] = args.mode
    report["summary"]["states"] = states

    if args.report_json:
        report_path = Path(args.report_json).expanduser()
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_path = (
            Path.home()
            / ".logs"
            / "hashall"
            / "reports"
            / "qbit-triage"
            / f"fresh-repair-{stamp}.json"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"fresh_repair done ts={now_ts()} selected={len(selected)} "
        f"ok={summary.get('ok',0)} planned={summary.get('planned',0)} error={summary.get('error',0)} "
        f"report={report_path}"
    )

    if args.mode == "dryrun":
        return 0
    return 1 if summary.get("error", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
