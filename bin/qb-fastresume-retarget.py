#!/usr/bin/env python3
"""Patch qB fastresume paths from qb-repair-fresh prepare/apply report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


DEFAULT_FASTRESUME_DIR = Path(
    "/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Retarget qB fastresume path fields using qb-repair-fresh report data."
    )
    p.add_argument("--report", required=True, help="Path to qb-repair-fresh JSON report")
    p.add_argument(
        "--fastresume-dir",
        default=str(DEFAULT_FASTRESUME_DIR),
        help="Directory containing <hash>.fastresume files",
    )
    p.add_argument(
        "--allow-status",
        default="prepared,ok,planned",
        help="Comma-separated row statuses to patch (default: prepared,ok,planned)",
    )
    p.add_argument("--dryrun", action="store_true", help="Print intended changes only")
    return p.parse_args()


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
            value.keys(),
            key=lambda x: x if isinstance(x, bytes) else str(x).encode("utf-8"),
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


def patch_fastresume(
    path: Path,
    target_save: str,
    dryrun: bool,
    backup_suffix: str,
) -> Tuple[bool, str]:
    raw = path.read_bytes()
    doc = Bencode(raw).parse()
    if not isinstance(doc, dict):
        return False, "invalid_fastresume_dict"

    old_save_path = as_text(doc.get(b"save_path", b""))
    old_qbt_save = as_text(doc.get(b"qBt-savePath", b""))
    old_download_path = as_text(doc.get(b"qBt-downloadPath", b""))

    changed = False
    target_b = target_save.encode("utf-8")
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
        return True, "no_change"

    if dryrun:
        return True, (
            f"would_update save_path={old_save_path!r} qBt-savePath={old_qbt_save!r} "
            f"qBt-downloadPath={old_download_path!r} -> target={target_save!r}"
        )

    backup = path.with_name(path.name + backup_suffix)
    if not backup.exists():
        backup.write_bytes(raw)
    path.write_bytes(bencode(doc))
    return True, (
        f"updated save_path={old_save_path!r} qBt-savePath={old_qbt_save!r} "
        f"qBt-downloadPath={old_download_path!r} -> target={target_save!r}"
    )


def main() -> int:
    args = parse_args()
    report_path = Path(args.report).expanduser()
    fr_dir = Path(args.fastresume_dir).expanduser()
    allow_status = {
        s.strip().lower() for s in str(args.allow_status).split(",") if s.strip()
    }

    if not report_path.exists():
        print(f"ERROR report_not_found path={report_path}")
        return 2
    if not fr_dir.exists():
        print(f"ERROR fastresume_dir_not_found path={fr_dir}")
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = list(report.get("results", []))

    candidates: List[Tuple[str, str]] = []
    for row in rows:
        status = str(row.get("status", "")).lower()
        if status not in allow_status:
            continue
        h = str(row.get("hash", "")).strip().lower()
        target = str(row.get("qb_location") or row.get("target_save") or "").strip()
        if not h or not target.startswith("/"):
            continue
        candidates.append((h, target.rstrip("/")))

    print(
        f"fastresume_retarget start ts={datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"report={report_path} candidates={len(candidates)} dryrun={bool(args.dryrun)}"
    )

    backup_suffix = ".bak-codex-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    ok = 0
    err = 0
    skipped_missing = 0
    changed = 0

    for idx, (h, target) in enumerate(candidates, start=1):
        fr = fr_dir / f"{h}.fastresume"
        if not fr.exists():
            skipped_missing += 1
            print(f"[{idx}/{len(candidates)}] hash={h[:12]} skip missing_fastresume path={fr}")
            continue
        success, msg = patch_fastresume(
            fr,
            target,
            bool(args.dryrun),
            backup_suffix,
        )
        if success:
            ok += 1
            if "no_change" not in msg:
                changed += 1
            print(f"[{idx}/{len(candidates)}] hash={h[:12]} ok {msg}")
        else:
            err += 1
            print(f"[{idx}/{len(candidates)}] hash={h[:12]} error {msg}")

    print(
        f"fastresume_retarget done ok={ok} changed={changed} "
        f"missing={skipped_missing} error={err}"
    )
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

