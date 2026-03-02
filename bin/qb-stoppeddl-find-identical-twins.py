#!/usr/bin/env python3
"""Find verified 100% identical qB siblings for stoppedDL and emit apply-compatible report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.qbittorrent import QBitFile, QBitTorrent, get_qbittorrent_client

SEMVER = "0.2.1"
SCRIPT_NAME = Path(__file__).name
VERIFY_TOOL = REPO_ROOT / "bin" / "qb-libtorrent-verify.py"
DEFAULT_SAFE_STATES = {
    "uploading",
    "stalledup",
    "stoppedup",
    "pausedup",
    "queuedup",
    "forcedup",
    "checkingup",
}


@dataclass(frozen=True)
class SignatureResult:
    ok: bool
    items: Tuple[Tuple[str, int], ...]
    reason: str


@dataclass(frozen=True)
class VerifyAttempt:
    sibling_hash: str
    sibling_state: str
    path: str
    source: str
    letter: str
    result: dict
    json_report: str


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
    seen: Set[str] = set()
    dedup: List[str] = []
    for cand in out:
        c = str(cand).rstrip("/")
        if c and c not in seen:
            seen.add(c)
            dedup.append(c)
    return dedup


def resolve_existing(path: str) -> str:
    for cand in alias_variants(path):
        if Path(cand).exists():
            return cand
    return str(path or "").rstrip("/")


def is_complete_seed(row: QBitTorrent, safe_states: Set[str]) -> bool:
    state = str(row.state or "").lower()
    if state not in safe_states:
        return False
    if float(row.progress or 0.0) < 0.999999:
        return False
    if int(row.amount_left or 0) != 0:
        return False
    return True


def name_size_key(row: QBitTorrent) -> Tuple[str, int]:
    return (str(row.name or "").strip().casefold(), int(row.size or 0))


def fetch_signature(
    qb,
    torrent_hash: str,
    cache: Dict[str, SignatureResult],
) -> SignatureResult:
    h = str(torrent_hash or "").strip().lower()
    if h in cache:
        return cache[h]
    try:
        files: Sequence[QBitFile] = qb.get_torrent_files(h)
    except Exception as e:  # pragma: no cover
        result = SignatureResult(ok=False, items=tuple(), reason=f"files_error:{e}")
        cache[h] = result
        return result
    if not files:
        result = SignatureResult(ok=False, items=tuple(), reason="no_files")
        cache[h] = result
        return result
    items = tuple(sorted((str(f.name or ""), int(f.size or 0)) for f in files))
    result = SignatureResult(ok=True, items=items, reason="ok")
    cache[h] = result
    return result


def candidate_payload_root(row: QBitTorrent) -> str:
    content_path = str(row.content_path or "").strip()
    save_path = str(row.save_path or "").strip()
    name = str(row.name or "").strip()
    if content_path:
        return content_path
    if save_path and name:
        return str(Path(save_path) / name)
    return save_path


def candidate_payload_paths(row: QBitTorrent) -> List[str]:
    content_path = str(row.content_path or "").strip()
    save_path = str(row.save_path or "").strip()
    name = str(row.name or "").strip()
    raw: List[str] = []
    if content_path:
        raw.append(content_path)
    if save_path and name:
        raw.append(str(Path(save_path) / name))
    if save_path:
        raw.append(save_path)
    seen: Set[str] = set()
    out: List[str] = []
    for p in raw:
        pp = str(p or "").strip().rstrip("/")
        if not pp:
            continue
        for cand in alias_variants(pp):
            c = str(cand or "").strip().rstrip("/")
            if c and c not in seen:
                seen.add(c)
                out.append(c)
    return out


def choose_candidate_path(row: QBitTorrent) -> str:
    name_cf = str(row.name or "").strip().casefold()
    cands = candidate_payload_paths(row)
    if not cands:
        return resolve_existing(candidate_payload_root(row))
    scored: List[Tuple[Tuple[int, int, int, int], str]] = []
    for cand in cands:
        p = Path(cand)
        exists = p.exists()
        is_dir = p.is_dir() if exists else False
        base_match = 1 if (name_cf and p.name.casefold() == name_cf) else 0
        score = (
            1 if exists else 0,
            base_match,
            1 if is_dir else 0,
            len(cand),
        )
        scored.append((score, cand))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def state_rank(state: str) -> int:
    s = str(state or "").lower()
    order = {
        "uploading": 7,
        "stalledup": 6,
        "stoppedup": 5,
        "pausedup": 4,
        "queuedup": 3,
        "forcedup": 2,
        "checkingup": 1,
    }
    return order.get(s, 0)


def sorted_twin_candidates(cands: List[QBitTorrent]) -> List[QBitTorrent]:
    return sorted(
        cands,
        key=lambda r: (
            state_rank(str(r.state or "").lower()),
            int(r.completion_on or 0),
            int(r.downloaded or 0),
            str(r.hash or ""),
        ),
        reverse=True,
    )


def classify_letter(result: dict) -> str:
    verified = bool(result.get("verified", False))
    exact_tree = bool(result.get("exact_tree", False))
    ratio = float(result.get("verify_ratio", 0.0) or 0.0)
    if verified and exact_tree:
        return "a"
    if verified:
        return "c"
    if ratio > 0.0:
        return "d"
    return "e"


def ensure_torrent_file(qb, target_hash: str, torrent_file: Path) -> bool:
    if torrent_file.exists() and torrent_file.stat().st_size > 0:
        return True
    blob = qb.export_torrent_file(target_hash, torrent_file)
    return bool(blob) and torrent_file.exists() and torrent_file.stat().st_size > 0


def run_verify(
    *,
    torrent_path: Path,
    candidate_path: str,
    reports_dir: Path,
    target_hash: str,
    sibling_hash: str,
    timeout_s: int,
    poll_s: int,
    show_progress: bool,
) -> Tuple[dict, str, str, str]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_out = reports_dir / f"verify-identical-{target_hash}-{sibling_hash}-{stamp}.json"
    cmd = [
        sys.executable,
        str(VERIFY_TOOL),
        "--torrent",
        str(torrent_path),
        "--path",
        str(candidate_path),
        "--timeout",
        str(int(timeout_s)),
        "--poll",
        str(max(1, int(poll_s))),
        "--json-out",
        str(json_out),
        "--quiet-summary",
    ]
    if show_progress:
        cmd.append("--show-progress")

    proc = subprocess.run(cmd, capture_output=True, text=True)

    fallback = {
        "path": str(candidate_path),
        "classification": "no_match",
        "verified": False,
        "verify_ratio": 0.0,
        "exact_tree": False,
        "reason": f"verify_failed_rc:{proc.returncode}",
    }

    if not json_out.exists():
        return fallback, str(json_out), (proc.stdout or "").strip(), (proc.stderr or "").strip()

    try:
        payload = json.loads(json_out.read_text(encoding="utf-8"))
        results = payload.get("results") or []
        if results:
            r0 = dict(results[0])
            if not r0.get("reason"):
                r0["reason"] = "verified_from_libtorrent"
            return r0, str(json_out), (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except Exception as e:
        fallback["reason"] = f"verify_json_parse_error:{e}"

    return fallback, str(json_out), (proc.stdout or "").strip(), (proc.stderr or "").strip()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Find verified 100% identical stoppedDL twins in qB and emit a "
            "drain-compatible report for qb-stoppeddl-apply.py"
        )
    )
    p.add_argument(
        "--bucket-dir",
        default="~/.cache/hashall/qb-stoppeddl-bucket",
        help="Bucket root directory (default: ~/.cache/hashall/qb-stoppeddl-bucket)",
    )
    p.add_argument(
        "--states",
        default="stoppeddl",
        help="Comma-separated target states to solve (default: stoppeddl)",
    )
    p.add_argument(
        "--seed-states",
        default="uploading,stalledup,stoppedup,pausedup,queuedup,forcedup,checkingup",
        help="Allowed sibling states considered seed-safe candidates",
    )
    p.add_argument(
        "--hashes",
        default="",
        help="Optional explicit hash/prefix filter for targets",
    )
    p.add_argument(
        "--hashes-file",
        default="",
        help="Optional hash filter file (one per line, # comments allowed)",
    )
    p.add_argument(
        "--ignore-hashes",
        default="",
        help="Optional hash/prefix ignore filter",
    )
    p.add_argument(
        "--ignore-hashes-file",
        default="",
        help="Optional ignore hash file (one per line, # comments allowed)",
    )
    p.add_argument(
        "--report-json",
        default="",
        help="Optional output report path (default: <bucket>/reports/drain-identical-twins-<ts>.json)",
    )
    p.add_argument(
        "--write-drain-latest",
        action="store_true",
        help="Also write/update <bucket>/reports/drain-latest.json with this report",
    )
    p.add_argument(
        "--matches-hashes-file",
        default="",
        help="Optional output file for matched target hashes (one per line)",
    )
    p.add_argument(
        "--pairs-tsv",
        default="",
        help="Optional TSV output with target_hash, twin_hash, source, path",
    )
    p.add_argument(
        "--verify-timeout",
        type=int,
        default=1800,
        help="libtorrent verify timeout per candidate (default: 1800)",
    )
    p.add_argument(
        "--verify-poll",
        type=int,
        default=1,
        help="libtorrent verify poll seconds (default: 1)",
    )
    p.add_argument(
        "--show-verify-progress",
        action="store_true",
        help="Print libtorrent verify progress lines",
    )
    p.add_argument(
        "--max-verify-candidates",
        type=int,
        default=0,
        help="Max exact siblings to verify per hash (0 = all)",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    now = emit_start_banner()

    bucket_dir = Path(args.bucket_dir).expanduser()
    reports_dir = bucket_dir / "reports"
    torrents_dir = bucket_dir / "torrents"
    reports_dir.mkdir(parents=True, exist_ok=True)
    torrents_dir.mkdir(parents=True, exist_ok=True)

    report_path = (
        Path(args.report_json).expanduser()
        if str(args.report_json or "").strip()
        else reports_dir / f"drain-identical-twins-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )

    latest_path = reports_dir / "drain-latest.json"
    matches_hashes_path = (
        Path(args.matches_hashes_file).expanduser()
        if str(args.matches_hashes_file or "").strip()
        else reports_dir / "identical-twin-matches-hashes.txt"
    )
    pairs_tsv_path = (
        Path(args.pairs_tsv).expanduser()
        if str(args.pairs_tsv or "").strip()
        else reports_dir / "identical-twin-pairs.tsv"
    )

    target_states = parse_states(args.states)
    seed_states = parse_states(args.seed_states)
    hash_filters = set(parse_hash_tokens(args.hashes))
    hash_filters.update(read_hash_file(args.hashes_file))
    ignore_filters = set(parse_hash_tokens(args.ignore_hashes))
    ignore_file_path = (
        Path(args.ignore_hashes_file).expanduser()
        if str(args.ignore_hashes_file or "").strip()
        else (bucket_dir / "download-whitelist-hashes.txt")
    )
    if ignore_file_path.exists():
        ignore_filters.update(read_hash_file(str(ignore_file_path)))

    qb = get_qbittorrent_client()
    if not qb.test_connection() or not qb.login():
        raise RuntimeError("qB connection/login failed")

    all_rows = qb.get_torrents()

    targets: List[QBitTorrent] = []
    ignored_count = 0
    for row in all_rows:
        h = str(row.hash or "").lower()
        st = str(row.state or "").lower()
        if st not in target_states:
            continue
        if ignore_filters and hash_matches_filters(h, ignore_filters):
            ignored_count += 1
            continue
        if hash_filters and not hash_matches_filters(h, hash_filters):
            continue
        targets.append(row)
    targets.sort(key=lambda r: str(r.hash or "").lower())

    target_hashes: Set[str] = {str(t.hash or "").lower() for t in targets}
    complete_rows: List[QBitTorrent] = []
    for row in all_rows:
        h = str(row.hash or "").lower()
        if h in target_hashes:
            continue
        if is_complete_seed(row, seed_states):
            complete_rows.append(row)

    by_name_size: Dict[Tuple[str, int], List[QBitTorrent]] = {}
    for row in complete_rows:
        by_name_size.setdefault(name_size_key(row), []).append(row)

    sig_cache: Dict[str, SignatureResult] = {}
    entries: List[dict] = []
    matched_hashes: List[str] = []
    pair_lines: List[str] = ["target_hash\ttwin_hash\tsource\trecommended_path"]
    class_counts = {"a": 0, "b": 0, "c": 0, "d": 0, "e": 0}
    signature_compared = 0
    candidate_considered = 0
    verify_attempts = 0
    signature_exact_candidates = 0
    candidate_path_missing = 0
    candidate_signature_failed = 0
    candidate_signature_differs = 0
    verify_rc_failures = 0
    targets_no_sibling = 0
    targets_no_existing_paths = 0
    targets_no_verify_attempts = 0
    targets_no_exact_signature = 0

    max_verify_candidates = max(0, int(args.max_verify_candidates))

    for idx, target in enumerate(targets, start=1):
        h = str(target.hash or "").lower()
        name = str(target.name or "")
        size = int(target.size or 0)
        torrent_file = torrents_dir / f"{h}.torrent"
        print(f"[{idx}/{len(targets)}] hash={h[:12]} name={name[:80]}")

        row_out = {
            "hash": h,
            "name": name,
            "size": size,
            "bucket_state": str(target.state or ""),
            "torrent_file": str(torrent_file),
            "status": "pending",
            "classification": "e",
            "recommended_path": "",
            "recommended_source": "",
            "best_result": {},
            "candidates": [],
            "verify_report_json": "",
            "verify_stdout": "",
            "verify_stderr": "",
            "detail": "",
        }

        twin_pool = by_name_size.get(name_size_key(target), [])
        if not twin_pool:
            row_out["status"] = "no_sibling_name_size"
            row_out["detail"] = "no_complete_sibling_same_name_size"
            targets_no_sibling += 1
            class_counts["e"] += 1
            entries.append(row_out)
            print("  class=e reason=no_complete_sibling_same_name_size")
            continue

        target_sig = fetch_signature(qb, h, sig_cache)
        if not target_sig.ok:
            row_out["status"] = "target_signature_failed"
            row_out["detail"] = target_sig.reason
            class_counts["e"] += 1
            entries.append(row_out)
            print(f"  class=e reason=target_signature_failed:{target_sig.reason}")
            continue

        if not ensure_torrent_file(qb, h, torrent_file):
            row_out["status"] = "target_torrent_missing"
            row_out["detail"] = "cannot_export_torrent"
            class_counts["e"] += 1
            entries.append(row_out)
            print("  class=e reason=target_torrent_missing")
            continue

        candidate_meta: Dict[str, dict] = {}
        for sib in twin_pool:
            candidate_considered += 1
            sh = str(sib.hash or "").lower()
            sig = fetch_signature(qb, sh, sig_cache)
            source = f"qb_identical_twin:{str(sib.state or '').lower()}"
            path = choose_candidate_path(sib)
            p = Path(path)
            path_exists = p.exists()
            path_name_matches_target = 1 if (name and p.name.casefold() == name.casefold()) else 0
            signature_ok = bool(sig.ok)
            signature_exact = bool(sig.ok and sig.items == target_sig.items)
            if not path_exists:
                candidate_path_missing += 1
            if not signature_ok:
                candidate_signature_failed += 1
            elif signature_exact:
                signature_exact_candidates += 1
            else:
                candidate_signature_differs += 1
            if signature_ok:
                signature_compared += 1
            row_out["candidates"].append(
                {
                    "hash": sh,
                    "source": source,
                    "path": path,
                    "path_exists": path_exists,
                    "path_name_matches_target": bool(path_name_matches_target),
                    "status": (
                        "signature_failed"
                        if not signature_ok
                        else "exact_match"
                        if signature_exact
                        else "not_exact"
                    ),
                    "reason": (
                        sig.reason
                        if not signature_ok
                        else "signature_equal"
                        if signature_exact
                        else "signature_differs"
                    ),
                }
            )
            candidate_meta[sh] = {
                "row": sib,
                "source": source,
                "path": path,
                "path_exists": bool(path_exists),
                "path_name_matches_target": int(path_name_matches_target),
                "signature_ok": bool(signature_ok),
                "signature_exact": bool(signature_exact),
            }

        ranked_candidates = sorted(
            candidate_meta.values(),
            key=lambda c: (
                1 if c["path_exists"] else 0,
                1 if c["signature_exact"] else 0,
                c["path_name_matches_target"],
                1 if c["signature_ok"] else 0,
                state_rank(str(c["row"].state or "").lower()),
                int(c["row"].completion_on or 0),
                int(c["row"].downloaded or 0),
                str(c["row"].hash or ""),
            ),
            reverse=True,
        )

        if not ranked_candidates:
            row_out["status"] = "no_sibling_candidates"
            row_out["detail"] = "same_name_size_pool_empty"
            targets_no_sibling += 1
            class_counts["e"] += 1
            entries.append(row_out)
            print("  class=e reason=no_sibling_candidates")
            continue

        if not any(c["signature_exact"] for c in ranked_candidates):
            targets_no_exact_signature += 1

        attempts: List[VerifyAttempt] = []
        verify_candidates = [c for c in ranked_candidates if c["path_exists"]]
        if not verify_candidates:
            row_out["status"] = "no_existing_candidate_paths"
            row_out["detail"] = "all_sibling_candidate_paths_missing"
            targets_no_existing_paths += 1
            class_counts["e"] += 1
            entries.append(row_out)
            print("  class=e reason=no_existing_candidate_paths")
            continue

        for n, meta in enumerate(verify_candidates, start=1):
            if max_verify_candidates > 0 and n > max_verify_candidates:
                break
            sib = meta["row"]
            sh = str(sib.hash or "").lower()
            sstate = str(sib.state or "").lower()
            source = str(meta["source"])
            candidate_path = str(meta["path"])
            verify_attempts += 1
            result, verify_json, verify_stdout, verify_stderr = run_verify(
                torrent_path=torrent_file,
                candidate_path=candidate_path,
                reports_dir=reports_dir,
                target_hash=h,
                sibling_hash=sh,
                timeout_s=int(args.verify_timeout),
                poll_s=int(args.verify_poll),
                show_progress=bool(args.show_verify_progress),
            )
            letter = classify_letter(result)
            attempts.append(
                VerifyAttempt(
                    sibling_hash=sh,
                    sibling_state=sstate,
                    path=candidate_path,
                    source=source,
                    letter=letter,
                    result=result,
                    json_report=verify_json,
                )
            )
            if str(result.get("reason") or "").startswith("verify_failed_rc:"):
                verify_rc_failures += 1
            if letter == "a":
                break

        if not attempts:
            row_out["status"] = "no_verify_attempts"
            row_out["detail"] = "verify_candidates_filtered_or_unavailable"
            targets_no_verify_attempts += 1
            class_counts["e"] += 1
            entries.append(row_out)
            print("  class=e reason=no_verify_attempts")
            continue

        best_attempt = sorted(
            attempts,
            key=lambda a: (
                4 if a.letter == "a" else 3 if a.letter == "c" else 2 if a.letter == "d" else 1,
                float(a.result.get("verify_ratio", 0.0) or 0.0),
                state_rank(a.sibling_state),
            ),
            reverse=True,
        )[0]

        best_result = dict(best_attempt.result)
        best_result["source_hash"] = best_attempt.sibling_hash
        best_result["source_state"] = best_attempt.sibling_state

        row_out["recommended_source"] = best_attempt.source
        row_out["recommended_path"] = best_attempt.path
        row_out["best_result"] = best_result
        row_out["verify_report_json"] = best_attempt.json_report

        ratio = float(best_result.get("verify_ratio", 0.0) or 0.0)
        if best_attempt.letter == "a":
            row_out["status"] = "exact_twin_verified"
            row_out["classification"] = "a"
            class_counts["a"] += 1
            matched_hashes.append(h)
            pair_lines.append(f"{h}\t{best_attempt.sibling_hash}\t{best_attempt.source}\t{best_attempt.path}")
            print(
                f"  class=a twin={best_attempt.sibling_hash[:12]} source={best_attempt.source} "
                f"ratio={ratio:.6f} path={best_attempt.path}"
            )
        elif best_attempt.letter == "c":
            row_out["status"] = "verified_close_match"
            row_out["classification"] = "c"
            class_counts["c"] += 1
            print(
                f"  class=c twin={best_attempt.sibling_hash[:12]} source={best_attempt.source} "
                f"ratio={ratio:.6f}"
            )
        elif best_attempt.letter == "d":
            row_out["status"] = "partial_match"
            row_out["classification"] = "d"
            class_counts["d"] += 1
            print(
                f"  class=d twin={best_attempt.sibling_hash[:12]} source={best_attempt.source} "
                f"ratio={ratio:.6f}"
            )
        else:
            row_out["status"] = "no_match"
            row_out["classification"] = "e"
            row_out["detail"] = str(best_result.get("reason") or "no_match")
            class_counts["e"] += 1
            print(
                f"  class=e twin={best_attempt.sibling_hash[:12]} source={best_attempt.source} "
                f"ratio={ratio:.6f} reason={row_out['detail']}"
            )

        entries.append(row_out)

    summary = {
        "selected": len(targets),
        "processed": len(entries),
        "remaining": max(0, len(targets) - len(entries)),
        "a": class_counts["a"],
        "b": class_counts["b"],
        "c": class_counts["c"],
        "d": class_counts["d"],
        "e": class_counts["e"],
        "ignored_hashes_skipped": int(ignored_count),
        "candidate_considered": int(candidate_considered),
        "signature_compared": int(signature_compared),
        "signature_exact_candidates": int(signature_exact_candidates),
        "verify_attempts": int(verify_attempts),
        "matched_pairs": int(len(matched_hashes)),
        "candidate_path_missing": int(candidate_path_missing),
        "candidate_signature_failed": int(candidate_signature_failed),
        "candidate_signature_differs": int(candidate_signature_differs),
        "verify_rc_failures": int(verify_rc_failures),
        "targets_no_sibling": int(targets_no_sibling),
        "targets_no_exact_signature": int(targets_no_exact_signature),
        "targets_no_existing_paths": int(targets_no_existing_paths),
        "targets_no_verify_attempts": int(targets_no_verify_attempts),
    }

    report_obj = {
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "started_at": now,
        "finished_at": ts_iso(),
        "progress_reason": "final",
        "params": {
            "bucket_dir": str(bucket_dir),
            "states": sorted(target_states),
            "seed_states": sorted(seed_states),
            "hash_filters": sorted(hash_filters),
            "ignore_filters": sorted(ignore_filters),
            "verify_timeout": int(args.verify_timeout),
            "verify_poll": int(args.verify_poll),
            "show_verify_progress": bool(args.show_verify_progress),
            "max_verify_candidates": int(max_verify_candidates),
        },
        "summary": summary,
        "entries": entries,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_obj, indent=2), encoding="utf-8")
    matches_hashes_path.parent.mkdir(parents=True, exist_ok=True)
    matches_hashes_path.write_text("\n".join(matched_hashes) + ("\n" if matched_hashes else ""), encoding="utf-8")
    pairs_tsv_path.parent.mkdir(parents=True, exist_ok=True)
    pairs_tsv_path.write_text("\n".join(pair_lines) + "\n", encoding="utf-8")

    if bool(args.write_drain_latest):
        latest_path.write_text(json.dumps(report_obj, indent=2), encoding="utf-8")

    print(
        f"summary selected={summary['selected']} processed={summary['processed']} "
        f"a={summary['a']} c={summary['c']} d={summary['d']} e={summary['e']} "
        f"matched_pairs={summary['matched_pairs']} verify_attempts={summary['verify_attempts']} "
        f"ignored_hashes_skipped={summary['ignored_hashes_skipped']} "
        f"candidate_considered={summary['candidate_considered']} signature_compared={summary['signature_compared']}"
    )
    print(f"report_json={report_path}")
    print(f"matches_hashes_txt={matches_hashes_path}")
    print(f"pairs_tsv={pairs_tsv_path}")
    if bool(args.write_drain_latest):
        print(f"latest_json={latest_path}")
    print("next_apply_cmd=")
    print(
        "python3 bin/qb-stoppeddl-apply.py "
        f"--bucket-dir {bucket_dir} "
        f"--drain-report {report_path} "
        f"--allow-class a "
        "--no-wait-recheck "
        "--apply"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
