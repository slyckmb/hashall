"""Repair a broken torrent from a known-good sibling in the same payload group."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from hashall.device import get_files_table_name
from hashall.fastresume import patch_fastresume_file
from hashall.link_executor import create_hardlink_atomic
from hashall.qbittorrent import QBitTorrent, get_qbittorrent_client


SCRIPT_NAME = "qb-repair-payload-group.sh"
SCRIPT_VERSION = "0.2.0"
SCRIPT_LAST_UPDATED = "2026-03-10"
DEFAULT_DB = Path.home() / ".hashall" / "catalog.db"
DEFAULT_FASTRESUME_DIR = Path("/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup")
DEFAULT_QB_CONTAINER = "qbittorrent_vpn"
DEFAULT_QB_URL = "http://localhost:9003"
DEFAULT_LOG_DIR = Path.home() / ".logs" / "hashall" / "reports" / "qbit-triage"
DEFAULT_OUT_DIR = Path("out") / "qb-repair-payload-group"
DEFAULT_SUCCESS_FILE = DEFAULT_LOG_DIR / "repair-consecutive-successes.txt"
GOOD_DONOR_STATES = {"stalledup", "stoppedup", "pausedup", "queuedup", "uploading", "forcedup"}
BROKEN_EXPECTED_STATES = {
    "stoppeddl",
    "pauseddl",
    "missingfiles",
    "error",
    "queueddl",
    "stalleddl",
    "downloading",
}
CHECKING_STATES = {"checkingdl", "checkingup", "checkingresumedata"}
GOOD_SEED_STATES = {"stalledup", "uploading", "queuedup", "stoppedup", "pausedup", "forcedup"}


def ts_human() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ts_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


@dataclass(frozen=True)
class PayloadIdentity:
    torrent_hash: str
    payload_hash: str
    root_path: str
    save_path: str
    root_name: str


@dataclass(frozen=True)
class DeviceMapping:
    device_id: int
    fs_uuid: str
    table_name: str
    mount_points: Tuple[Path, ...]


@dataclass(frozen=True)
class FileRecord:
    rel: str
    abs: str
    size: int
    qhash: Optional[str]


@dataclass(frozen=True)
class RepairPlanItem:
    file: str
    key: str
    broken_rel: str
    broken_abs: str
    good_rel: Optional[str]
    good_abs: Optional[str]
    action: str
    broken_qhash: Optional[str]
    good_qhash: Optional[str]
    same_inode: bool


class RunLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.log_path.open("a", encoding="utf-8")

    def close(self) -> None:
        self._handle.close()

    def line(self, message: str) -> None:
        print(message, flush=True)
        self._handle.write(message + "\n")
        self._handle.flush()


class CatalogLookup:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).expanduser()
        self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self._devices = self._load_devices()

    def close(self) -> None:
        self.conn.close()

    def _load_devices(self) -> List[DeviceMapping]:
        rows = self.conn.execute(
            """
            SELECT fs_uuid, device_id, mount_point, preferred_mount_point, files_table
            FROM devices
            ORDER BY device_id
            """
        ).fetchall()
        devices: List[DeviceMapping] = []
        cursor = self.conn.cursor()
        for row in rows:
            fs_uuid = str(row["fs_uuid"] or "").strip()
            device_id = int(row["device_id"])
            table_name = str(row["files_table"] or "").strip()
            if not table_name:
                table_name = str(
                    get_files_table_name(
                        cursor,
                        device_id=device_id,
                        fs_uuid=fs_uuid,
                        create=False,
                    )
                    or ""
                ).strip()
            if not table_name:
                continue
            mounts: List[Path] = []
            for raw in (row["preferred_mount_point"], row["mount_point"]):
                candidate = str(raw or "").strip()
                if candidate and candidate not in {str(p) for p in mounts}:
                    mounts.append(Path(candidate))
            if not mounts:
                continue
            devices.append(
                DeviceMapping(
                    device_id=device_id,
                    fs_uuid=fs_uuid,
                    table_name=table_name,
                    mount_points=tuple(mounts),
                )
            )
        return devices

    def resolve_file_table(self, abs_path: str) -> Optional[Tuple[DeviceMapping, str]]:
        candidate = Path(str(abs_path or "")).expanduser()
        if not candidate.is_absolute():
            return None
        best: Optional[Tuple[DeviceMapping, str, int]] = None
        for device in self._devices:
            for mount in device.mount_points:
                try:
                    rel = candidate.relative_to(mount).as_posix()
                except Exception:
                    continue
                score = len(mount.as_posix())
                if best is None or score > best[2]:
                    best = (device, rel, score)
        if best is None:
            return None
        return best[0], best[1]

    def quick_hash(self, abs_path: str) -> Optional[str]:
        resolved = self.resolve_file_table(abs_path)
        if resolved is None:
            return None
        device, rel_path = resolved
        row = self.conn.execute(
            f"SELECT quick_hash FROM {quote_ident(device.table_name)} "
            "WHERE path = ? AND status = 'active' LIMIT 1",
            (rel_path,),
        ).fetchone()
        value = str(row[0] or "").strip() if row else ""
        return value or None

    def payload_identity(self, torrent_hash: str) -> Optional[PayloadIdentity]:
        row = self.conn.execute(
            """
            SELECT lower(ti.torrent_hash) AS torrent_hash,
                   p.payload_hash,
                   p.root_path,
                   ti.save_path,
                   ti.root_name
            FROM torrent_instances ti
            JOIN payloads p ON p.payload_id = ti.payload_id
            WHERE lower(ti.torrent_hash) = ?
            LIMIT 1
            """,
            (str(torrent_hash or "").strip().lower(),),
        ).fetchone()
        if row is None:
            return None
        return PayloadIdentity(
            torrent_hash=str(row["torrent_hash"] or ""),
            payload_hash=str(row["payload_hash"] or ""),
            root_path=str(row["root_path"] or ""),
            save_path=str(row["save_path"] or ""),
            root_name=str(row["root_name"] or ""),
        )


def load_success_streak(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def store_success_streak(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(value)) + "\n", encoding="utf-8")


def ensure_same_payload_group(catalog: CatalogLookup, good_hash: str, broken_hash: str) -> Tuple[PayloadIdentity, PayloadIdentity]:
    good = catalog.payload_identity(good_hash)
    broken = catalog.payload_identity(broken_hash)
    if good is None:
        raise RuntimeError(f"good_hash_missing_from_catalog hash={good_hash}")
    if broken is None:
        raise RuntimeError(f"broken_hash_missing_from_catalog hash={broken_hash}")
    if not good.payload_hash or not broken.payload_hash:
        raise RuntimeError("payload_hash_missing")
    if good.payload_hash != broken.payload_hash:
        raise RuntimeError(
            "payload_group_mismatch "
            f"good_payload={good.payload_hash[:16]} broken_payload={broken.payload_hash[:16]}"
        )
    return good, broken


def _file_key(rel_path: str, size: int, total_files: int) -> str:
    parts = tuple(part for part in PurePosixPath(str(rel_path or "")).parts if part not in {"", "."})
    if total_files <= 1:
        logical = "__singlefile__"
    elif len(parts) > 1:
        logical = PurePosixPath(*parts[1:]).as_posix()
    elif parts:
        logical = parts[0]
    else:
        logical = str(rel_path or "")
    return f"{logical}|{int(size)}"


def build_repair_plan(
    *,
    good_save: str,
    broken_save: str,
    good_files: Sequence[Dict[str, Any]],
    broken_files: Sequence[Dict[str, Any]],
    quick_hash_lookup: Callable[[str], Optional[str]],
) -> List[RepairPlanItem]:
    good_index: Dict[str, List[FileRecord]] = {}
    broken_index: Dict[str, List[FileRecord]] = {}

    def _collect(
        items: Sequence[Dict[str, Any]],
        save_path: str,
        out: Dict[str, List[FileRecord]],
    ) -> List[FileRecord]:
        collected: List[FileRecord] = []
        total = len(items)
        for row in items:
            rel = str(row.get("name") or "").strip()
            size = int(row.get("size") or 0)
            key = _file_key(rel, size, total)
            abs_path = str(Path(save_path) / rel)
            record = FileRecord(
                rel=rel,
                abs=abs_path,
                size=size,
                qhash=quick_hash_lookup(abs_path),
            )
            out.setdefault(key, []).append(record)
            collected.append(record)
        return collected

    good_records = _collect(good_files, good_save, good_index)
    broken_records = _collect(broken_files, broken_save, broken_index)
    broken_qhash_counts: Dict[str, int] = {}
    for record in broken_records:
        if record.qhash:
            broken_qhash_counts[record.qhash] = broken_qhash_counts.get(record.qhash, 0) + 1

    plan: List[RepairPlanItem] = []
    for key, broken_list in broken_index.items():
        good_list = good_index.get(key, [])
        if len(broken_list) != 1 or len(good_list) > 1:
            for record in broken_list:
                plan.append(
                    RepairPlanItem(
                        file=record.rel,
                        key=key,
                        broken_rel=record.rel,
                        broken_abs=record.abs,
                        good_rel=good_list[0].rel if len(good_list) == 1 else None,
                        good_abs=good_list[0].abs if len(good_list) == 1 else None,
                        action="ambiguous_match",
                        broken_qhash=record.qhash,
                        good_qhash=good_list[0].qhash if len(good_list) == 1 else None,
                        same_inode=False,
                    )
                )
            continue
        if not good_list:
            record = broken_list[0]
            plan.append(
                RepairPlanItem(
                    file=record.rel,
                    key=key,
                    broken_rel=record.rel,
                    broken_abs=record.abs,
                    good_rel=None,
                    good_abs=None,
                    action="no_good_match",
                    broken_qhash=record.qhash,
                    good_qhash=None,
                    same_inode=False,
                )
            )
            continue

        broken_record = broken_list[0]
        good_record = good_list[0]
        same_inode = False
        try:
            if Path(broken_record.abs).exists() and Path(good_record.abs).exists():
                same_inode = os.stat(broken_record.abs).st_ino == os.stat(good_record.abs).st_ino
        except OSError:
            same_inode = False

        if same_inode:
            action = "already_hardlinked"
        elif broken_record.qhash and good_record.qhash and broken_record.qhash == good_record.qhash:
            action = "dup_copy"
        elif not Path(broken_record.abs).exists():
            action = "missing"
        elif broken_record.qhash and broken_qhash_counts.get(broken_record.qhash, 0) > 1:
            action = "garbage"
        elif (
            broken_record.qhash is not None
            and good_record.qhash is not None
            and broken_record.qhash != good_record.qhash
        ):
            action = "garbage"
        else:
            action = "unknown_keep"

        plan.append(
            RepairPlanItem(
                file=broken_record.rel,
                key=key,
                broken_rel=broken_record.rel,
                broken_abs=broken_record.abs,
                good_rel=good_record.rel,
                good_abs=good_record.abs,
                action=action,
                broken_qhash=broken_record.qhash,
                good_qhash=good_record.qhash,
                same_inode=same_inode,
            )
        )
    return sorted(plan, key=lambda item: item.file)


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def run_docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def wait_for_qb_api(qb_url: str, timeout_seconds: float = 60.0) -> None:
    deadline = time.time() + float(timeout_seconds)
    client = get_qbittorrent_client(base_url=qb_url)
    while time.time() < deadline:
        if client.is_reachable():
            return
        time.sleep(2)
    raise RuntimeError("qb_api_not_ready")


def parse_state(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def ensure_donor_state(info: QBitTorrent) -> None:
    state = parse_state(info.state)
    if state not in GOOD_DONOR_STATES:
        raise RuntimeError(f"good_state_invalid state={info.state}")
    if float(info.progress or 0.0) < 0.999:
        raise RuntimeError(f"good_progress_incomplete progress={info.progress}")


def state_progress_line(info: Optional[QBitTorrent]) -> str:
    if info is None:
        return "missing"
    return f"{info.state} {float(info.progress or 0.0) * 100.0:.1f}%"


def summarize_plan(plan: Sequence[RepairPlanItem]) -> Dict[str, int]:
    out: Dict[str, int] = {"files": len(plan)}
    for item in plan:
        out[item.action] = out.get(item.action, 0) + 1
    return out


def plan_has_blockers(plan: Sequence[RepairPlanItem]) -> bool:
    return any(item.action in {"ambiguous_match", "no_good_match"} for item in plan)


def create_missing_hardlink(canonical_path: Path, duplicate_path: Path) -> Tuple[bool, Optional[str]]:
    try:
        canonical_stat = canonical_path.stat()
        parent = duplicate_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        parent_stat = parent.stat()
        if canonical_stat.st_dev != parent_stat.st_dev:
            return False, "filesystem_mismatch"
        if duplicate_path.exists():
            return False, "duplicate_already_exists"
        os.link(canonical_path, duplicate_path)
        return True, None
    except OSError as exc:
        return False, str(exc)


def execute_same_fs_rebuild(
    *,
    plan: Sequence[RepairPlanItem],
    journal_path: Path,
    logger: RunLogger,
) -> None:
    rebuild_actions = {"garbage", "dup_copy", "missing"}
    for item in plan:
        if item.action not in rebuild_actions:
            continue
        good_path = Path(str(item.good_abs or ""))
        broken_path = Path(item.broken_abs)
        entry: Dict[str, Any] = {
            "ts": ts_human(),
            "action": "hardlink_rebuild",
            "file": item.file,
            "plan_action": item.action,
            "good_abs": str(good_path),
            "broken_abs": str(broken_path),
        }
        if not good_path.exists():
            entry["status"] = "failed"
            entry["detail"] = "good_missing"
            append_jsonl(journal_path, entry)
            raise RuntimeError(f"good_file_missing path={good_path}")
        if item.action == "missing":
            ok, error = create_missing_hardlink(good_path, broken_path)
            entry["status"] = "ok" if ok else "failed"
            if error:
                entry["detail"] = error
            append_jsonl(journal_path, entry)
            if not ok:
                raise RuntimeError(f"hardlink_create_failed path={broken_path} error={error}")
            logger.line(f"  ln  {good_path.name} -> {broken_path.parent}")
            continue

        ok, error, backup_path = create_hardlink_atomic(good_path, broken_path, create_backup=True)
        entry["status"] = "ok" if ok else "failed"
        if backup_path is not None:
            entry["backup_path"] = str(backup_path)
        if error:
            entry["detail"] = error
        append_jsonl(journal_path, entry)
        if not ok:
            raise RuntimeError(f"hardlink_replace_failed path={broken_path} error={error}")
        logger.line(f"  relink {broken_path.name}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def patch_fastresume_with_journal(
    *,
    fastresume_path: Path,
    target_save_path: str,
    backup_suffix: str,
    journal_path: Path,
) -> Dict[str, Any]:
    result = patch_fastresume_file(fastresume_path, target_save_path, backup_suffix)
    entry = {
        "ts": ts_human(),
        "action": "fastresume_patch",
        "changed": bool(result.changed),
        "fastresume_path": result.fastresume_path,
        "backup_path": result.backup_path,
        "old_save_path": result.old_save_path,
        "old_qBt-savePath": result.old_qbt_save_path,
        "old_qBt-downloadPath": result.old_qbt_download_path,
        "new_save_path": result.new_save_path,
        "new_qBt-savePath": result.new_qbt_save_path,
        "new_qBt-downloadPath": result.new_qbt_download_path,
    }
    append_jsonl(journal_path, entry)
    return entry


def stop_qb_container(container: str, logger: RunLogger) -> None:
    logger.line("  stopping qB...")
    result = run_docker("stop", container)
    line = (result.stdout or result.stderr or "").strip()
    if line:
        logger.line(f"  docker stop: {line}")


def start_qb_container(container: str, qb_url: str, logger: RunLogger) -> None:
    logger.line("  starting qB...")
    result = run_docker("start", container)
    line = (result.stdout or result.stderr or "").strip()
    if line:
        logger.line(f"  docker start: {line}")
    wait_for_qb_api(qb_url)
    logger.line("  qB API ready")


def monitor_recheck(qb_hash: str, qb_url: str, logger: RunLogger) -> str:
    qb = get_qbittorrent_client(base_url=qb_url)
    deadline = time.time() + 600.0
    final_state = "timeout"
    while time.time() < deadline:
        time.sleep(5)
        info = qb.get_torrent_info(qb_hash)
        if info is None:
            final_state = "missing"
            break
        state = parse_state(info.state)
        logger.line(f"  [{datetime.now().strftime('%H:%M:%S')}] {info.state}  {float(info.progress or 0.0) * 100.0:.1f}%")
        if state in CHECKING_STATES:
            continue
        if state == "stoppedup":
            final_state = "stoppedUP"
            break
        if state == "stoppeddl":
            final_state = f"stoppedDL:{info.progress}"
            break
        if state in {"downloading", "stalleddl", "queueddl", "uploading", "stalledup", "forcedup", "forceddl", "queuedup"}:
            qb.pause_torrent(qb_hash)
            final_state = f"stopped_active:{info.state}"
            break
        final_state = f"unknown:{info.state}"
        break
    return final_state


def monitor_seed_verify(qb_hash: str, qb_url: str, logger: RunLogger) -> bool:
    qb = get_qbittorrent_client(base_url=qb_url)
    deadline = time.time() + 90.0
    while time.time() < deadline:
        time.sleep(5)
        info = qb.get_torrent_info(qb_hash)
        state = parse_state(info.state if info else "missing")
        logger.line(f"  [{datetime.now().strftime('%H:%M:%S')}] {info.state if info else 'missing'}")
        if state in GOOD_SEED_STATES:
            continue
        if state in {"downloading", "stalleddl", "forceddl", "queueddl", "error", "missingfiles"}:
            qb.pause_torrent(qb_hash)
            return False
    qb.pause_torrent(qb_hash)
    return True


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Repair one qB torrent from a known-good sibling in the same payload group.",
    )
    parser.add_argument("--good", required=True, help="Good sibling hash")
    parser.add_argument("--broken", required=True, help="Broken sibling hash")
    parser.add_argument("--apply", action="store_true", help="Execute live changes")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"Catalog DB path (default: {DEFAULT_DB})")
    parser.add_argument(
        "--fastresume-dir",
        default=str(DEFAULT_FASTRESUME_DIR),
        help=f"qB fastresume directory (default: {DEFAULT_FASTRESUME_DIR})",
    )
    parser.add_argument(
        "--qb-container",
        default=DEFAULT_QB_CONTAINER,
        help=f"qB container name for restart (default: {DEFAULT_QB_CONTAINER})",
    )
    parser.add_argument(
        "--qb-url",
        default=DEFAULT_QB_URL,
        help=f"qB Web API URL (default: {DEFAULT_QB_URL})",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Per-run artifact root (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--success-file",
        default=str(DEFAULT_SUCCESS_FILE),
        help=f"Consecutive success counter file (default: {DEFAULT_SUCCESS_FILE})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    stamp = ts_stamp()
    broken_hash = str(args.broken or "").strip().lower()
    good_hash = str(args.good or "").strip().lower()
    run_dir = Path(args.out_dir).expanduser() / f"{stamp}-{broken_hash[:12]}"
    log_path = DEFAULT_LOG_DIR / f"qbit-repair-payload-{stamp}-{broken_hash[:12]}.log"
    logger = RunLogger(log_path)
    logger.line(f"script={SCRIPT_NAME} version={SCRIPT_VERSION} last_updated={SCRIPT_LAST_UPDATED}")
    logger.line(f"ts={ts_human()} log={log_path}")
    logger.line(f"work_dir={run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)

    streak_path = Path(args.success_file).expanduser()
    db_path = Path(args.db).expanduser()
    fastresume_dir = Path(args.fastresume_dir).expanduser()
    work_journal = run_dir / "journal.jsonl"
    good_files_path = run_dir / "good-files.json"
    broken_files_path = run_dir / "broken-files.json"
    plan_path = run_dir / "repair-plan.json"
    metadata_path = run_dir / "run-metadata.json"
    metadata = {
        "good_hash": good_hash,
        "broken_hash": broken_hash,
        "apply": bool(args.apply),
        "db": str(db_path),
        "fastresume_dir": str(fastresume_dir),
        "qb_container": args.qb_container,
        "qb_url": args.qb_url,
        "ts": ts_human(),
    }
    write_json(metadata_path, metadata)

    success = False
    catalog = CatalogLookup(db_path)
    try:
        logger.line(f"━━━ REPAIR good={good_hash[:12]} broken={broken_hash[:12]} apply={args.apply} ━━━")
        logger.line("▸ P1 validate")
        good_identity, broken_identity = ensure_same_payload_group(catalog, good_hash, broken_hash)
        logger.line(f"  payload_hash={good_identity.payload_hash[:16]}...")

        qb = get_qbittorrent_client(base_url=args.qb_url)
        info_by_hash = qb.get_torrents_by_hashes([good_hash, broken_hash])
        good_info = info_by_hash.get(good_hash)
        broken_info = info_by_hash.get(broken_hash)
        if good_info is None:
            raise RuntimeError("good_hash_missing_from_qb")
        if broken_info is None:
            raise RuntimeError("broken_hash_missing_from_qb")

        ensure_donor_state(good_info)
        broken_state = parse_state(broken_info.state)
        if broken_state not in BROKEN_EXPECTED_STATES:
            logger.line(f"  WARN broken_state={broken_info.state} expected=stoppedDL-ish")

        logger.line(f"  good   state={state_progress_line(good_info)} save={good_info.save_path}")
        logger.line(f"  broken state={state_progress_line(broken_info)} save={broken_info.save_path}")

        good_device = catalog.resolve_file_table(good_info.save_path + "/.placeholder")
        broken_device = catalog.resolve_file_table(broken_info.save_path + "/.placeholder")
        same_fs = bool(good_device and broken_device and good_device[0].fs_uuid == broken_device[0].fs_uuid)
        logger.line(f"  same_fs={same_fs}")

        logger.line("▸ P2 content analysis")
        good_files = [{"name": row.name, "size": row.size} for row in qb.get_torrent_files(good_hash)]
        broken_files = [{"name": row.name, "size": row.size} for row in qb.get_torrent_files(broken_hash)]
        write_json(good_files_path, good_files)
        write_json(broken_files_path, broken_files)
        plan = build_repair_plan(
            good_save=good_info.save_path,
            broken_save=broken_info.save_path,
            good_files=good_files,
            broken_files=broken_files,
            quick_hash_lookup=catalog.quick_hash,
        )
        write_json(plan_path, [asdict(item) for item in plan])
        summary = summarize_plan(plan)
        logger.line(
            "  files={files} ".format(**summary)
            + " ".join(f"{key}={value}" for key, value in sorted(summary.items()) if key != "files")
        )
        for item in plan:
            if item.action != "already_hardlinked":
                logger.line(f"    {item.action:20} {item.file[:80]}")
        if plan_has_blockers(plan):
            raise RuntimeError("repair_plan_blocked ambiguous_or_missing_matches")

        logger.line(f"▸ P3 hardlink rebuild same_fs={same_fs}")
        target_save_path = broken_info.save_path
        if args.apply:
            if same_fs:
                execute_same_fs_rebuild(plan=plan, journal_path=work_journal, logger=logger)
            else:
                target_save_path = good_info.save_path
                logger.line(f"  cross-fs setLocation target={target_save_path}")
        else:
            if same_fs:
                logger.line("  [dry-run] would rebuild hardlinks for garbage/dup_copy/missing")
            else:
                logger.line(f"  [dry-run] would setLocation broken -> {good_info.save_path}")
                target_save_path = good_info.save_path

        logger.line("▸ P4 qB fix")
        fastresume_path = fastresume_dir / f"{broken_hash}.fastresume"
        patch_suffix = f".repair-{stamp}"
        if args.apply:
            if not same_fs or target_save_path != broken_info.save_path:
                ok = qb.set_location(broken_hash, target_save_path)
                if not ok:
                    raise RuntimeError(f"set_location_failed error={qb.last_error or 'unknown'}")
                logger.line(f"  setLocation ok target={target_save_path}")
            else:
                logger.line("  setLocation skipped save_path already correct")

            patched_backup = ""
            qb_stopped = False
            try:
                if not fastresume_path.exists():
                    raise RuntimeError(f"fastresume_missing path={fastresume_path}")
                stop_qb_container(args.qb_container, logger)
                qb_stopped = True
                patch_entry = patch_fastresume_with_journal(
                    fastresume_path=fastresume_path,
                    target_save_path=target_save_path,
                    backup_suffix=patch_suffix,
                    journal_path=work_journal,
                )
                patched_backup = str(patch_entry.get("backup_path") or "")
                logger.line(
                    "  fastresume patched changed={changed} backup={backup}".format(
                        changed=patch_entry["changed"],
                        backup=patched_backup or "-",
                    )
                )
            except Exception:
                if qb_stopped and patched_backup and Path(patched_backup).exists():
                    shutil.copy2(patched_backup, fastresume_path)
                    logger.line(f"  restored fastresume backup={patched_backup}")
                raise
            finally:
                if qb_stopped:
                    start_qb_container(args.qb_container, args.qb_url, logger)
        else:
            logger.line("  [dry-run] would setLocation + stop qB + patch fastresume + restart")

        logger.line("▸ P5 recheck + monitor")
        final_state = "dry-run"
        if args.apply:
            qb = get_qbittorrent_client(base_url=args.qb_url)
            if not qb.recheck_torrent(broken_hash):
                raise RuntimeError(f"recheck_failed error={qb.last_error or 'unknown'}")
            final_state = monitor_recheck(broken_hash, args.qb_url, logger)
            logger.line(f"  recheck result={final_state}")
        else:
            logger.line("  [dry-run] would dispatch recheck")

        logger.line("▸ P6 start + verify")
        if args.apply and final_state == "stoppedUP":
            qb = get_qbittorrent_client(base_url=args.qb_url)
            if not qb.resume_torrent(broken_hash):
                raise RuntimeError(f"resume_failed error={qb.last_error or 'unknown'}")
            logger.line("  resumed; monitoring 90s for stable UP")
            success = monitor_seed_verify(broken_hash, args.qb_url, logger)
            logger.line("  verify result=" + ("success" if success else "failed"))
        elif args.apply:
            logger.line(f"  skip start final_state={final_state}")
        else:
            logger.line("  [dry-run]")

        logger.line("▸ P7 streak")
        streak = load_success_streak(streak_path)
        if success:
            streak += 1
            store_success_streak(streak_path, streak)
            logger.line(f"  SUCCESS streak={streak}")
            if streak >= 10:
                logger.line("  READY_FOR_BATCH threshold=10")
        elif args.apply:
            store_success_streak(streak_path, 0)
            logger.line("  FAIL streak reset")
        else:
            logger.line("  [dry-run]")
        logger.line("━━━ DONE ━━━")
        return 0
    finally:
        catalog.close()
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
