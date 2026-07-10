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
SEMVER = "0.1.0"


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
    freeleech = [row for row in summaries if row["freeleech"]["is_freeleech"]]
    report = {
        "tool": "prowlarr-freeleech-proof",
        "script": SCRIPT_NAME,
        "semver": SEMVER,
        "timestamp": ts(),
        "query": args.query,
        "indexer_ids": args.indexer_id,
        "hits": len(summaries),
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
