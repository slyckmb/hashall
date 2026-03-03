#!/usr/bin/env python3
"""Standalone qB repair pipeline (v2).

This tool intentionally uses new logic inspired by cross-seed matching behavior:
1) Match by exact file tree (rel path + size)
2) Match by size with filename tie-break
3) Match by size only (strict ambiguity checks)

Workflow:
- `plan`: classify broken hashes and pick safe parent sources
- `prepare`: build unique hardlinked payload roots from plan mappings
- `patch-fastresume`: patch save_path fields in fastresume for prepared hashes
- `recheck`: pause + setLocation + recheck for prepared hashes
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import stat
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import QBitFile, QBitTorrent, get_qbittorrent_client


BROKEN_STATES_DEFAULT = "missingFiles,stoppedDL"
TRUSTED_STATES_DEFAULT = "stalledUP,uploading,stoppedUP,queuedUP,checkingUP,forcedUP,pausedUP"
FASTRESUME_DIR_DEFAULT = Path(
    "/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"
)
DOWNLOAD_BAD_STATES = {
    "downloading",
    "stalleddl",
    "forceddl",
    "metadl",
    "queueddl",
    "allocating",
}
CHECKING_STATES = {"checkingdl", "checkingup", "checkingresumedata"}
SEED_READY_STATES = {"stalledup", "uploading", "queu eup", "stoppedup", "pausedup"}


@dataclass(frozen=True)
class ManifestEntry:
    rel_path: str
    name: str
    size: int


def ts_human() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ts_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def split_csv(value: str) -> List[str]:
    return [v.strip() for v in str(value or "").split(",") if v.strip()]


def norm_rel(path: str) -> str:
    p = str(path or "").replace("\\", "/").strip()
    p = p.lstrip("./").lstrip("/")
    return p


def canonical_alias_path(path: str) -> str:
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
    return p


def alias_variants(path: str) -> List[str]:
    p = str(path or "").strip().rstrip("/")
    if not p:
        return []
    out: List[str] = [p]
    if p == "/data/media" or p.startswith("/data/media/"):
        out.append("/stash/media" + p[len("/data/media") :])
    if p == "/stash/media" or p.startswith("/stash/media/"):
        out.append("/data/media" + p[len("/stash/media") :])
    if p == "/pool/data/seeds" or p.startswith("/pool/data/seeds/"):
        out.append("/data/media/torrents/seeding" + p[len("/pool/data/seeds") :])
    if p == "/data/media/torrents/seeding" or p.startswith(
        "/data/media/torrents/seeding/"
    ):
        out.append("/pool/data/seeds" + p[len("/data/media/torrents/seeding") :])
    out.append(canonical_alias_path(p))
    dedup: List[str] = []
    seen = set()
    for cand in out:
        c = cand.rstrip("/")
        if c and c not in seen:
            seen.add(c)
            dedup.append(c)
    return dedup


def first_existing_path(path: str) -> Optional[str]:
    for cand in alias_variants(path):
        if Path(cand).exists():
            return cand
    return None


def source_file_from_variants(base_save: str, rel_path: str) -> Optional[Path]:
    rel = norm_rel(rel_path)
    for base in alias_variants(base_save):
        cand = Path(base) / rel
        if cand.exists():
            return cand
    return None


def normalize_title(name: str) -> str:
    out = []
    for ch in str(name or "").lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def manifest_from_files(files: Sequence[QBitFile]) -> List[ManifestEntry]:
    out: List[ManifestEntry] = []
    for f in files:
        rel = norm_rel(f.name)
        if not rel:
            continue
        out.append(ManifestEntry(rel_path=rel, name=Path(rel).name, size=int(f.size)))
    out.sort(key=lambda e: (e.rel_path, e.size))
    return out


def manifest_root_name(entries: Sequence[ManifestEntry]) -> Optional[str]:
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0].rel_path
    roots = {e.rel_path.split("/", 1)[0] for e in entries if "/" in e.rel_path}
    if len(roots) == 1:
        return list(roots)[0]
    return None


def choose_unique_target_save(source_save: str, torrent_hash: str, subdir: str) -> str:
    src = str(source_save or "").strip().rstrip("/")
    if not src:
        return str(Path(subdir) / torrent_hash.lower())
    # Keep target on the same mounted path style as the source to avoid EXDEV.
    base = first_existing_path(src) or src
    return str(Path(base) / subdir / torrent_hash.lower())


def choose_qb_location(target_save: str, current_save: str) -> str:
    curr = str(current_save or "").strip().rstrip("/")
    target = str(target_save or "").strip().rstrip("/")
    if curr.startswith("/stash/media/") or curr == "/stash/media":
        canon = canonical_alias_path(target)
        if canon.startswith("/data/media"):
            return "/stash/media" + canon[len("/data/media") :]
    if curr.startswith("/pool/data/seeds/") or curr == "/pool/data/seeds":
        canon = canonical_alias_path(target)
        prefix = "/data/media/torrents/seeding"
        if canon.startswith(prefix):
            return "/pool/data/seeds" + canon[len(prefix) :]
    return canonical_alias_path(target)


def mode_rank(mode: str) -> int:
    if mode == "exact":
        return 3
    if mode == "size_name":
        return 2
    if mode == "size_only":
        return 1
    return 0


def build_exact_map(
    target: Sequence[ManifestEntry], source: Sequence[ManifestEntry]
) -> Optional[Dict[str, str]]:
    source_by_rel_size = {(s.rel_path, s.size): s for s in source}
    mapping: Dict[str, str] = {}
    for t in target:
        s = source_by_rel_size.get((t.rel_path, t.size))
        if s is None:
            return None
        mapping[t.rel_path] = s.rel_path
    return mapping


def build_size_map(
    target: Sequence[ManifestEntry],
    source: Sequence[ManifestEntry],
    *,
    require_name_on_collisions: bool,
    strict_ambiguous: bool,
) -> Tuple[Optional[Dict[str, str]], str]:
    source_list = list(source)
    by_size: Dict[int, List[int]] = defaultdict(list)
    for idx, s in enumerate(source_list):
        by_size[s.size].append(idx)
    used: set[int] = set()
    mapping: Dict[str, str] = {}

    # Large files first is usually safer for uniqueness.
    for t in sorted(target, key=lambda e: (-e.size, e.rel_path)):
        cand_ids = [i for i in by_size.get(t.size, []) if i not in used]
        if not cand_ids:
            return None, f"missing_size:{t.size}:{t.rel_path}"

        pick: Optional[int] = None
        if len(cand_ids) == 1:
            pick = cand_ids[0]
        else:
            same_name = [i for i in cand_ids if source_list[i].name == t.name]
            if require_name_on_collisions and not same_name:
                return None, f"name_collision:{t.size}:{t.rel_path}"
            if len(same_name) == 1:
                pick = same_name[0]
            elif len(same_name) > 1:
                same_rel = [i for i in same_name if source_list[i].rel_path == t.rel_path]
                if len(same_rel) == 1:
                    pick = same_rel[0]
                elif strict_ambiguous:
                    return None, f"ambiguous_same_name:{t.size}:{t.rel_path}"
                else:
                    pick = same_name[0]
            else:
                # size-only fallback.
                same_rel = [i for i in cand_ids if source_list[i].rel_path == t.rel_path]
                if len(same_rel) == 1:
                    pick = same_rel[0]
                elif strict_ambiguous:
                    return None, f"ambiguous_size_only:{t.size}:{t.rel_path}"
                else:
                    pick = cand_ids[0]

        if pick is None:
            return None, f"no_pick:{t.size}:{t.rel_path}"
        used.add(pick)
        mapping[t.rel_path] = source_list[pick].rel_path
    return mapping, "ok"


def serialize_manifest(entries: Sequence[ManifestEntry]) -> List[Dict[str, Any]]:
    return [asdict(e) for e in entries]


def deserialize_manifest(entries: Sequence[Dict[str, Any]]) -> List[ManifestEntry]:
    out: List[ManifestEntry] = []
    for e in entries:
        out.append(
            ManifestEntry(
                rel_path=str(e.get("rel_path") or ""),
                name=str(e.get("name") or ""),
                size=int(e.get("size") or 0),
            )
        )
    return out


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
        keys = sorted(
            value.keys(),
            key=lambda x: x if isinstance(x, bytes) else str(x).encode("utf-8"),
        )
        for k in keys:
            kb = k if isinstance(k, bytes) else str(k).encode("utf-8")
            items.append(bencode(kb))
            items.append(bencode(value[k]))
        return b"d" + b"".join(items) + b"e"
    raise TypeError(f"Unsupported type for bencode: {type(value)!r}")


def as_text(v: Any) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "ignore")
    return str(v)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="qB repair v2 (fresh strategy)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Build repair plan from live qB state")
    p_plan.add_argument("--broken-states", default=BROKEN_STATES_DEFAULT)
    p_plan.add_argument("--trusted-states", default=TRUSTED_STATES_DEFAULT)
    p_plan.add_argument("--limit", type=int, default=0, help="Limit broken hashes processed")
    p_plan.add_argument("--max-candidates", type=int, default=60)
    p_plan.add_argument("--fuzzy-size", type=float, default=0.03)
    p_plan.add_argument("--unique-subdir", default="_qb-repair-v2")
    p_plan.add_argument("--manifest-cache", default="", help="Optional JSON cache path")
    p_plan.add_argument("--report-json", default="")

    p_prepare = sub.add_parser(
        "prepare", help="Build unique hardlinked payload roots from a plan report"
    )
    p_prepare.add_argument("--plan", required=True, help="Plan JSON path")
    p_prepare.add_argument("--apply", action="store_true", help="Perform filesystem edits")
    p_prepare.add_argument("--allow-modes", default="planned_exact,planned_size_name,planned_size_only")
    p_prepare.add_argument("--quarantine-exclusive-root", action="store_true", default=True)
    p_prepare.add_argument("--no-quarantine-exclusive-root", dest="quarantine_exclusive_root", action="store_false")
    p_prepare.add_argument("--report-json", default="")

    p_patch = sub.add_parser(
        "patch-fastresume", help="Patch fastresume save path fields from prepare report"
    )
    p_patch.add_argument("--report", required=True, help="Plan/prepare JSON path")
    p_patch.add_argument("--allow-status", default="prepared,prepared_noop")
    p_patch.add_argument("--fastresume-dir", default=str(FASTRESUME_DIR_DEFAULT))
    p_patch.add_argument("--apply", action="store_true")

    p_recheck = sub.add_parser(
        "recheck", help="Pause + setLocation + recheck for prepared rows"
    )
    p_recheck.add_argument("--report", required=True, help="Plan/prepare JSON path")
    p_recheck.add_argument("--allow-status", default="prepared,prepared_noop")
    p_recheck.add_argument("--apply", action="store_true")
    p_recheck.add_argument("--batch-size", type=int, default=40)
    p_recheck.add_argument("--protect-download", action="store_true", default=True)
    p_recheck.add_argument("--no-protect-download", dest="protect_download", action="store_false")
    p_recheck.add_argument("--monitor-seconds", type=int, default=300)
    p_recheck.add_argument("--poll", type=float, default=5.0)

    return p.parse_args()


def get_manifest_cache(path: str) -> Dict[str, List[ManifestEntry]]:
    if not path:
        return {}
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        out: Dict[str, List[ManifestEntry]] = {}
        for h, entries in (data.get("manifests") or {}).items():
            out[str(h).lower()] = deserialize_manifest(entries or [])
        return out
    except Exception:
        return {}


def write_manifest_cache(path: str, cache: Dict[str, List[ManifestEntry]]) -> None:
    if not path:
        return
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"updated_at": ts_human(), "manifests": {}}
    for h, manifest in cache.items():
        data["manifests"][h] = serialize_manifest(manifest)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_manifest(
    qb: Any, cache: Dict[str, List[ManifestEntry]], torrent_hash: str
) -> List[ManifestEntry]:
    h = torrent_hash.lower().strip()
    if h in cache:
        return cache[h]
    files = qb.get_torrent_files(h)
    manifest = manifest_from_files(files)
    cache[h] = manifest
    return manifest


def is_trusted_seed(t: QBitTorrent, trusted_states: set[str]) -> bool:
    state = str(t.state or "").lower()
    if state not in trusted_states:
        return False
    if float(t.progress or 0.0) < 0.9999:
        return False
    if int(t.amount_left or 0) > 0:
        return False
    return True


def shortlist_candidates(
    broken: QBitTorrent,
    trusted: Sequence[QBitTorrent],
    max_candidates: int,
    fuzzy_size: float,
) -> List[QBitTorrent]:
    bsize = int(broken.size or 0)
    if bsize <= 0:
        return []

    def within_size(t: QBitTorrent) -> bool:
        tsize = int(t.size or 0)
        if tsize <= 0:
            return False
        return abs(tsize - bsize) / float(bsize) <= fuzzy_size

    pool = [t for t in trusted if within_size(t)]
    if not pool:
        return []
    pool.sort(
        key=lambda t: (
            0 if int(t.size or 0) == bsize else 1,
            -name_similarity(broken.name, t.name),
            abs(int(t.size or 0) - bsize),
            t.hash,
        )
    )
    if max_candidates > 0:
        return pool[:max_candidates]
    return pool


def build_plan(args: argparse.Namespace) -> int:
    qb = get_qbittorrent_client()
    torrents = qb.get_torrents()
    by_hash = {t.hash.lower(): t for t in torrents}
    trusted_states = {s.lower() for s in split_csv(args.trusted_states)}
    broken_states = {s.lower() for s in split_csv(args.broken_states)}

    broken = [t for t in torrents if str(t.state or "").lower() in broken_states]
    broken.sort(key=lambda t: t.hash)
    if args.limit and args.limit > 0:
        broken = broken[: args.limit]
    trusted = [t for t in torrents if is_trusted_seed(t, trusted_states)]
    trusted_by_hash = {t.hash.lower(): t for t in trusted}

    manifest_cache = get_manifest_cache(args.manifest_cache)
    rows: List[Dict[str, Any]] = []

    print(
        f"plan start ts={ts_human()} broken={len(broken)} trusted={len(trusted)} "
        f"max_candidates={args.max_candidates} fuzzy_size={args.fuzzy_size:.4f}"
    )

    for i, b in enumerate(broken, start=1):
        h = b.hash.lower()
        row: Dict[str, Any] = {
            "idx": i,
            "hash": h,
            "name": b.name,
            "state": b.state,
            "size": int(b.size or 0),
            "progress": float(b.progress or 0.0),
            "save_path_before": str(b.save_path or ""),
            "content_path_before": str(b.content_path or ""),
            "status": "",
            "reason": "",
            "parent_hash": "",
            "parent_name": "",
            "parent_state": "",
            "mode": "",
            "name_similarity": 0.0,
            "mapped_files": 0,
            "total_files": 0,
            "mapped_bytes": 0,
            "total_bytes": 0,
            "source_save": "",
            "target_save": "",
            "target_root": "",
            "qb_location": "",
            "mapping": {},
        }

        target_manifest = get_manifest(qb, manifest_cache, h)
        if not target_manifest:
            row["status"] = "no_manifest"
            row["reason"] = "qb_files_empty"
            rows.append(row)
            print(f"[{i}/{len(broken)}] {h[:16]} status=no_manifest")
            continue

        total_bytes = sum(e.size for e in target_manifest)
        row["total_files"] = len(target_manifest)
        row["total_bytes"] = total_bytes

        candidates = shortlist_candidates(b, trusted, args.max_candidates, args.fuzzy_size)
        if not candidates:
            row["status"] = "no_candidate_pool"
            row["reason"] = "size_prefilter"
            rows.append(row)
            print(f"[{i}/{len(broken)}] {h[:16]} status=no_candidate_pool")
            continue

        matches: List[Dict[str, Any]] = []
        for cand in candidates:
            ph = cand.hash.lower()
            if ph == h:
                continue
            src_manifest = get_manifest(qb, manifest_cache, ph)
            if not src_manifest:
                continue

            mapping = build_exact_map(target_manifest, src_manifest)
            mode = ""
            fail_reason = ""
            if mapping is not None:
                mode = "exact"
            else:
                mapping, fail_reason = build_size_map(
                    target_manifest,
                    src_manifest,
                    require_name_on_collisions=True,
                    strict_ambiguous=True,
                )
                if mapping is not None:
                    mode = "size_name"
                else:
                    mapping, fail_reason = build_size_map(
                        target_manifest,
                        src_manifest,
                        require_name_on_collisions=False,
                        strict_ambiguous=True,
                    )
                    if mapping is not None:
                        mode = "size_only"

            if mapping is None:
                continue

            mapped_bytes = sum(
                e.size for e in target_manifest if e.rel_path in mapping
            )
            source_save = str(cand.save_path or "").strip()
            target_save = choose_unique_target_save(
                source_save, h, str(args.unique_subdir or "_qb-repair-v2").strip()
            )
            root_name = manifest_root_name(target_manifest)
            target_root = str(Path(target_save) / root_name) if root_name else target_save
            matches.append(
                {
                    "parent_hash": ph,
                    "parent_name": cand.name,
                    "parent_state": cand.state,
                    "mode": mode,
                    "name_similarity": round(name_similarity(b.name, cand.name), 6),
                    "mapped_files": len(mapping),
                    "total_files": len(target_manifest),
                    "mapped_bytes": int(mapped_bytes),
                    "total_bytes": int(total_bytes),
                    "source_save": source_save,
                    "target_save": target_save,
                    "target_root": target_root,
                    "qb_location": choose_qb_location(target_save, str(b.save_path or "")),
                    "mapping": mapping,
                }
            )

        if not matches:
            row["status"] = "no_live_match"
            row["reason"] = "no_exact_size_name_or_size_only"
            rows.append(row)
            print(f"[{i}/{len(broken)}] {h[:16]} status=no_live_match")
            continue

        matches.sort(
            key=lambda m: (
                -mode_rank(str(m["mode"])),
                -int(m["mapped_bytes"]),
                -float(m["name_similarity"]),
                m["parent_hash"],
            )
        )
        best = matches[0]
        top = [
            m
            for m in matches
            if mode_rank(str(m["mode"])) == mode_rank(str(best["mode"]))
            and int(m["mapped_bytes"]) == int(best["mapped_bytes"])
        ]
        if len({m["parent_hash"] for m in top}) > 1:
            row["status"] = "ambiguous_match"
            row["reason"] = f"multiple_top_mode={best['mode']} count={len(top)}"
            rows.append(row)
            print(
                f"[{i}/{len(broken)}] {h[:16]} status=ambiguous_match mode={best['mode']} count={len(top)}"
            )
            continue

        row.update(best)
        row["status"] = f"planned_{best['mode']}"
        row["reason"] = "ok"
        rows.append(row)
        print(
            f"[{i}/{len(broken)}] {h[:16]} status={row['status']} parent={str(row['parent_hash'])[:16]}"
        )

    summary: Dict[str, int] = defaultdict(int)
    for row in rows:
        summary[str(row.get("status") or "unknown")] += 1

    out = {
        "tool": "qb-repair-v2",
        "command": "plan",
        "ts": ts_human(),
        "args": vars(args),
        "summary": dict(summary),
        "counts": {
            "broken_considered": len(broken),
            "trusted_considered": len(trusted),
            "all_torrents": len(torrents),
        },
        "results": rows,
    }

    if args.report_json:
        report_path = Path(args.report_json).expanduser()
    else:
        report_path = (
            Path.home()
            / ".logs"
            / "hashall"
            / "reports"
            / "qbit-triage"
            / f"qb-repair-v2-plan-{ts_compact()}.json"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"report_json={report_path}")
    print(f"summary={json.dumps(dict(summary), sort_keys=True)}")

    write_manifest_cache(args.manifest_cache, manifest_cache)
    return 0


def load_report(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"report_not_found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def compute_known_roots(torrents: Sequence[QBitTorrent]) -> Dict[str, set[str]]:
    out: Dict[str, set[str]] = defaultdict(set)
    for t in torrents:
        h = str(t.hash or "").lower()
        cp = str(t.content_path or "").strip().rstrip("/")
        sp = str(t.save_path or "").strip().rstrip("/")
        nm = str(t.name or "").strip()
        roots = []
        if cp.startswith("/"):
            roots.append(cp)
        if sp.startswith("/") and nm:
            roots.append(str(Path(sp) / nm))
        if sp.startswith("/"):
            roots.append(sp)
        for r in roots:
            out[canonical_alias_path(r)].add(h)
    return out


def quarantine_root(
    root: Path, torrent_hash: str, dryrun: bool
) -> Tuple[bool, str]:
    stamp = ts_compact()
    suffix = f".bad.{stamp}.{torrent_hash[:12]}"
    dst = root.with_name(root.name + suffix)
    if dryrun:
        return True, f"would_rename:{root}->{dst}"
    root.rename(dst)
    return True, f"renamed:{root}->{dst}"


def prepare_from_plan(args: argparse.Namespace) -> int:
    report = load_report(args.plan)
    allow = {s.strip().lower() for s in split_csv(args.allow_modes)}
    rows = list(report.get("results") or [])
    qb = get_qbittorrent_client()
    all_torrents = qb.get_torrents()
    roots_in_use = compute_known_roots(all_torrents)
    apply_mode = bool(args.apply)

    out_rows: List[Dict[str, Any]] = []
    print(
        f"prepare start ts={ts_human()} apply={apply_mode} "
        f"allow_status={','.join(sorted(allow))}"
    )
    for i, row in enumerate(rows, start=1):
        cur = dict(row)
        h = str(cur.get("hash") or "").lower()
        status = str(cur.get("status") or "").lower()
        if status not in allow:
            out_rows.append(cur)
            continue

        mapping: Dict[str, str] = dict(cur.get("mapping") or {})
        target_save = str(cur.get("target_save") or "").strip()
        target_root = str(cur.get("target_root") or "").strip()
        source_save = str(cur.get("source_save") or "").strip()
        cur["prepare_apply"] = apply_mode
        cur["prepare_ts"] = ts_human()

        if not h or not mapping or not target_save or not source_save:
            cur["status"] = "prepare_error"
            cur["reason"] = "missing_hash_mapping_or_paths"
            out_rows.append(cur)
            print(f"[{i}/{len(rows)}] {h[:16]} status=prepare_error missing fields")
            continue

        target_save_path = Path(target_save)
        target_root_path = Path(target_root) if target_root else target_save_path

        target_exists = target_root_path.exists()
        root_key = canonical_alias_path(str(target_root_path))
        in_use_by = sorted(roots_in_use.get(root_key, set()) - {h})

        if target_exists and args.quarantine_exclusive_root and in_use_by:
            cur["status"] = "prepare_error"
            cur["reason"] = f"target_root_in_use_by_other_hashes:{len(in_use_by)}"
            cur["target_in_use_by"] = in_use_by[:20]
            out_rows.append(cur)
            print(
                f"[{i}/{len(rows)}] {h[:16]} status=prepare_error target root shared count={len(in_use_by)}"
            )
            continue

        linked = 0
        skipped_existing = 0
        failed = 0
        errors: List[str] = []
        quarantine_note = ""

        try:
            if target_exists and args.quarantine_exclusive_root:
                ok, note = quarantine_root(target_root_path, h, dryrun=not apply_mode)
                quarantine_note = note
                if not ok:
                    raise RuntimeError(note)

            if apply_mode:
                target_save_path.mkdir(parents=True, exist_ok=True)

            for target_rel, source_rel in sorted(mapping.items()):
                src = source_file_from_variants(source_save, source_rel)
                if src is None:
                    failed += 1
                    errors.append(f"source_missing:{source_rel}")
                    continue
                dst = target_save_path / norm_rel(target_rel)
                if dst.exists():
                    try:
                        sst = src.stat()
                        dstst = dst.stat()
                        same_inode = (
                            sst.st_ino == dstst.st_ino and sst.st_dev == dstst.st_dev
                        )
                    except OSError:
                        same_inode = False
                    if same_inode:
                        skipped_existing += 1
                        continue
                    failed += 1
                    errors.append(f"dest_conflict:{dst}")
                    continue
                if not apply_mode:
                    linked += 1
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(src, dst)
                    linked += 1
                except OSError as e:
                    failed += 1
                    if e.errno == getattr(os, "EXDEV", 18):
                        errors.append(f"cross_device:{src}->{dst}")
                    else:
                        errors.append(f"link_error:{src}->{dst}:{e}")

            if failed:
                cur["status"] = "prepare_error"
                cur["reason"] = f"link_failures:{failed}"
            else:
                cur["status"] = "prepared" if linked > 0 else "prepared_noop"
                cur["reason"] = "ok"

            cur["prepare_linked"] = linked
            cur["prepare_skipped_existing"] = skipped_existing
            cur["prepare_failed"] = failed
            if quarantine_note:
                cur["prepare_quarantine"] = quarantine_note
            if errors:
                cur["prepare_errors"] = errors[:50]
            print(
                f"[{i}/{len(rows)}] {h[:16]} status={cur['status']} "
                f"linked={linked} skipped={skipped_existing} failed={failed}"
            )
        except Exception as e:
            cur["status"] = "prepare_error"
            cur["reason"] = f"exception:{e}"
            print(f"[{i}/{len(rows)}] {h[:16]} status=prepare_error exception={e}")
        out_rows.append(cur)

    summary: Dict[str, int] = defaultdict(int)
    for row in out_rows:
        summary[str(row.get("status") or "unknown")] += 1

    out = dict(report)
    out["tool"] = "qb-repair-v2"
    out["command"] = "prepare"
    out["ts"] = ts_human()
    out["args"] = vars(args)
    out["summary"] = dict(summary)
    out["results"] = out_rows

    if args.report_json:
        out_path = Path(args.report_json).expanduser()
    else:
        out_path = (
            Path.home()
            / ".logs"
            / "hashall"
            / "reports"
            / "qbit-triage"
            / f"qb-repair-v2-prepare-{ts_compact()}.json"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"report_json={out_path}")
    print(f"summary={json.dumps(dict(summary), sort_keys=True)}")
    return 0


def patch_fastresume(args: argparse.Namespace) -> int:
    report = load_report(args.report)
    allow = {s.strip().lower() for s in split_csv(args.allow_status)}
    fr_dir = Path(args.fastresume_dir).expanduser()
    if not fr_dir.exists():
        print(f"ERROR fastresume_dir_not_found path={fr_dir}")
        return 2

    rows = list(report.get("results") or [])
    apply_mode = bool(args.apply)
    backup_suffix = f".bak-qb-repair-v2-{ts_compact()}"

    candidates: List[Tuple[str, str]] = []
    for row in rows:
        st = str(row.get("status") or "").lower()
        if st not in allow:
            continue
        h = str(row.get("hash") or "").lower().strip()
        target = str(row.get("qb_location") or row.get("target_save") or "").strip()
        if not h or not target.startswith("/"):
            continue
        candidates.append((h, target.rstrip("/")))

    changed = 0
    no_change = 0
    missing = 0
    failed = 0
    print(
        f"patch-fastresume start ts={ts_human()} apply={apply_mode} candidates={len(candidates)}"
    )
    for i, (h, target) in enumerate(candidates, start=1):
        p = fr_dir / f"{h}.fastresume"
        if not p.exists():
            missing += 1
            print(f"[{i}/{len(candidates)}] {h[:16]} status=missing_fastresume")
            continue
        try:
            raw = p.read_bytes()
            doc = Bencode(raw).parse()
            if not isinstance(doc, dict):
                failed += 1
                print(f"[{i}/{len(candidates)}] {h[:16]} status=invalid_fastresume")
                continue
            tb = target.encode("utf-8")
            c = False
            if doc.get(b"save_path") != tb:
                doc[b"save_path"] = tb
                c = True
            if doc.get(b"qBt-savePath") != tb:
                doc[b"qBt-savePath"] = tb
                c = True
            if doc.get(b"qBt-downloadPath", b"") != b"":
                doc[b"qBt-downloadPath"] = b""
                c = True
            if not c:
                no_change += 1
                print(f"[{i}/{len(candidates)}] {h[:16]} status=no_change")
                continue
            if apply_mode:
                backup = p.with_name(p.name + backup_suffix)
                if not backup.exists():
                    backup.write_bytes(raw)
                p.write_bytes(bencode(doc))
            changed += 1
            print(
                f"[{i}/{len(candidates)}] {h[:16]} status={'changed' if apply_mode else 'would_change'}"
            )
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(candidates)}] {h[:16]} status=error detail={e}")

    print(
        f"patch-fastresume done changed={changed} no_change={no_change} missing={missing} failed={failed}"
    )
    return 0 if failed == 0 else 1


def chunked(items: Sequence[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def recheck_apply(args: argparse.Namespace) -> int:
    report = load_report(args.report)
    allow = {s.strip().lower() for s in split_csv(args.allow_status)}
    rows = list(report.get("results") or [])
    todo: List[Dict[str, Any]] = []
    for row in rows:
        st = str(row.get("status") or "").lower()
        if st not in allow:
            continue
        h = str(row.get("hash") or "").lower().strip()
        loc = str(row.get("qb_location") or row.get("target_save") or "").strip()
        if h and loc.startswith("/"):
            todo.append({"hash": h, "location": loc})

    if not todo:
        print("recheck nothing_to_do")
        return 0

    qb = get_qbittorrent_client()
    apply_mode = bool(args.apply)
    print(
        f"recheck start ts={ts_human()} apply={apply_mode} hashes={len(todo)} batch={args.batch_size}"
    )
    if not apply_mode:
        for row in todo[:20]:
            print(f"dryrun hash={row['hash']} location={row['location']}")
        if len(todo) > 20:
            print(f"dryrun_more={len(todo) - 20}")
        return 0

    # Apply in batches to avoid huge payloads.
    all_hashes = [row["hash"] for row in todo]
    loc_by_hash = {row["hash"]: row["location"] for row in todo}
    for i, h in enumerate(all_hashes, start=1):
        qb.pause_torrent(h)
        ok_loc = qb.set_location(h, loc_by_hash[h])
        if not ok_loc:
            print(f"[{i}/{len(all_hashes)}] {h[:16]} status=set_location_failed")
            continue
        ok_chk = qb.recheck_torrent(h)
        if not ok_chk:
            print(f"[{i}/{len(all_hashes)}] {h[:16]} status=recheck_failed")
            continue
        print(f"[{i}/{len(all_hashes)}] {h[:16]} status=recheck_started")

    if not args.protect_download:
        return 0

    watch = set(all_hashes)
    deadline = time.time() + max(0, int(args.monitor_seconds))
    print(
        f"recheck monitor protect_download=true poll={args.poll}s monitor_seconds={args.monitor_seconds}"
    )
    while watch and time.time() < deadline:
        state_map = qb.get_torrents_by_hashes(list(watch))
        to_remove: List[str] = []
        for h in list(watch):
            t = state_map.get(h)
            if t is None:
                to_remove.append(h)
                continue
            st = str(t.state or "").lower()
            if st in DOWNLOAD_BAD_STATES:
                qb.pause_torrent(h)
                print(f"protect stop hash={h[:16]} state={st}")
            if st not in CHECKING_STATES:
                to_remove.append(h)
        for h in to_remove:
            watch.discard(h)
        time.sleep(max(0.5, float(args.poll)))

    print(f"recheck done remaining_watch={len(watch)}")
    return 0


def main() -> int:
    args = parse_args()
    if args.cmd == "plan":
        return build_plan(args)
    if args.cmd == "prepare":
        return prepare_from_plan(args)
    if args.cmd == "patch-fastresume":
        return patch_fastresume(args)
    if args.cmd == "recheck":
        return recheck_apply(args)
    print(f"ERROR unknown_command:{args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
