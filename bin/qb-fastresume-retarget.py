#!/usr/bin/env python3
"""Patch qB fastresume paths from qb-repair-fresh prepare/apply report."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
    p.add_argument(
        "--qb-container",
        default=None,
        help="Docker container name for qBittorrent. If specified, the container MUST be "
             "stopped before this tool will patch any fastresume files. Prevents race "
             "conditions where qBittorrent overwrites patches mid-run.",
    )
    return p.parse_args()


def _check_container_stopped(container: str) -> Optional[str]:
    """
    Verify a Docker container is stopped.

    Returns None if the container is confirmed stopped/not-running.
    Returns an error string if the container appears to be running or
    the status cannot be determined.
    """
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            # Container not found is safe — treat as stopped.
            stderr = (proc.stderr or "").strip()
            if "No such container" in stderr or "no such object" in stderr.lower():
                return None
            return f"docker_inspect_failed rc={proc.returncode} stderr={stderr!r}"
        running = (proc.stdout or "").strip().lower()
        if running == "true":
            return (
                f"Container {container!r} is RUNNING — "
                "stop it before patching fastresume files to prevent data races. "
                "Use: docker stop " + container
            )
        return None
    except FileNotFoundError:
        return "docker executable not found — cannot verify container state"
    except Exception as e:
        return f"container_check_error:{e}"


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

    # H5: Verify qBittorrent container is stopped before touching any fastresume
    # files.  qBittorrent continuously rewrites its own fastresume state; patching
    # while it runs is a race condition that can corrupt or lose changes.
    if args.qb_container and not args.dryrun:
        container_err = _check_container_stopped(str(args.qb_container))
        if container_err:
            print(f"ERROR container_running_abort {container_err}")
            return 2
        print(f"container_check ok container={args.qb_container} status=stopped")

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

