#!/usr/bin/env python3
"""Find Prowlarr releases with explicit freeleech evidence."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hashall.rt_torrent_replace import DEFAULT_PROWLARR_URL, load_prowlarr_api_key


SCRIPT_NAME = "prowlarr-freeleech-proof.py"
SEMVER = "0.2.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search Prowlarr read-only and emit releases with explicit freeleech evidence."
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--indexer-id", action="append", default=[], help="Optional Prowlarr indexer id; repeatable")
    parser.add_argument("--prowlarr-url", default=DEFAULT_PROWLARR_URL)
    parser.add_argument("--prowlarr-api-key-file", default="")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", default="", help="Write JSON proof report")
    parser.add_argument(
        "--expected-title",
        default="",
        help="Only prove freeleech from releases whose normalized title matches this value",
    )
    parser.add_argument(
        "--expected-size",
        type=int,
        default=0,
        help="Only prove freeleech from releases near this byte size",
    )
    parser.add_argument(
        "--size-tolerance-bytes",
        type=int,
        default=0,
        help="Allowed absolute byte difference for --expected-size; default requires exact size",
    )
    return parser


def ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def prowlarr_get(
    api_url: str,
    api_key_file: str,
    endpoint: str,
    params: list[tuple[str, str]],
    timeout: float,
) -> Any:
    api_key = load_prowlarr_api_key(api_key_file)
    url = f"{api_url.rstrip('/')}{endpoint}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    req = urllib.request.Request(url, headers={"X-Api-Key": api_key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_strings(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_strings(item))
        return out
    return [str(value)]


def freeleech_evidence(hit: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    fields: dict[str, Any] = {}
    for key in ("downloadVolumeFactor", "downloadVolume", "downloadFactor"):
        value = _number(hit.get(key))
        if value is not None:
            fields[key] = hit.get(key)
            if value == 0:
                reasons.append(f"{key}=0")
    for key in ("indexerFlags", "flags", "releaseFlags"):
        values = _strings(hit.get(key))
        if values:
            fields[key] = values
        if any("freeleech" in value.lower() for value in values):
            reasons.append(f"{key}=freeleech")
    return {"is_freeleech": bool(reasons), "reasons": reasons, "fields": fields}


def summarize_hit(hit: dict[str, Any]) -> dict[str, Any]:
    evidence = freeleech_evidence(hit)
    return {
        "title": hit.get("title") or "",
        "indexer": hit.get("indexer") or "",
        "indexer_id": hit.get("indexerId"),
        "seeders": int(hit.get("seeders") or 0),
        "grabs": int(hit.get("grabs") or 0),
        "size": int(hit.get("size") or 0),
        "info_url": hit.get("infoUrl") or hit.get("guid") or "",
        "download_url_present": bool(hit.get("downloadUrl")),
        "freeleech": evidence,
    }


def normalized_title(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def proof_match_reason(
    hit: dict[str, Any],
    *,
    expected_title: str = "",
    expected_size: int = 0,
    size_tolerance_bytes: int = 0,
) -> dict[str, Any]:
    reasons: list[str] = []
    title_ok = True
    size_ok = True
    if expected_title:
        expected_norm = normalized_title(expected_title)
        hit_norm = normalized_title(str(hit.get("title") or ""))
        title_ok = hit_norm == expected_norm
        if title_ok:
            reasons.append("title_exact_normalized")
    if expected_size:
        size = int(hit.get("size") or 0)
        delta = abs(size - expected_size)
        size_ok = delta <= size_tolerance_bytes
        if size_ok:
            reasons.append(f"size_within_tolerance:{delta}")
    return {
        "is_match": title_ok and size_ok,
        "reasons": reasons,
        "expected_title": expected_title,
        "expected_size": expected_size,
        "size_tolerance_bytes": size_tolerance_bytes,
    }


def main() -> int:
    args = build_parser().parse_args()
    params: list[tuple[str, str]] = [
        ("query", args.query),
        ("type", "search"),
        ("limit", str(args.limit)),
    ]
    for indexer_id in args.indexer_id:
        params.append(("indexerIds", str(indexer_id)))
    payload = prowlarr_get(
        args.prowlarr_url,
        args.prowlarr_api_key_file,
        "/api/v1/search",
        params,
        args.timeout,
    )
    hits = payload if isinstance(payload, list) else []
    summaries = [summarize_hit(hit) for hit in hits]
    for row in summaries:
        row["proof_match"] = proof_match_reason(
            row,
            expected_title=args.expected_title,
            expected_size=args.expected_size,
            size_tolerance_bytes=args.size_tolerance_bytes,
        )
    proof_filter_active = bool(args.expected_title or args.expected_size)
    eligible = [row for row in summaries if row["proof_match"]["is_match"]]
    proof_pool = eligible if proof_filter_active else summaries
    freeleech = [row for row in proof_pool if row["freeleech"]["is_freeleech"]]
    report = {
        "tool": "prowlarr-freeleech-proof",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "timestamp": ts(),
        "query": args.query,
        "expected_title": args.expected_title,
        "expected_size": args.expected_size,
        "size_tolerance_bytes": args.size_tolerance_bytes,
        "proof_filter_active": proof_filter_active,
        "indexer_ids": args.indexer_id,
        "hits": len(summaries),
        "eligible_hits": len(eligible) if proof_filter_active else len(summaries),
        "freeleech_hits": len(freeleech),
        "freeleech_proven": bool(freeleech),
        "freeleech": freeleech,
        "all_hits": summaries,
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        path = Path(args.output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if freeleech else 1


if __name__ == "__main__":
    raise SystemExit(main())
