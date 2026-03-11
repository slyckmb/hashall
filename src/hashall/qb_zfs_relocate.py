"""Guarded qBittorrent ZFS dataset relocation workflow."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from hashall.bencode import as_text, bencode_decode
from hashall.fastresume import normalize_save_path, patch_fastresume_file, read_fastresume
from hashall.qbittorrent import QBittorrentClient, get_qbittorrent_client


SCRIPT_NAME = "qb-zfs-relocate"
SCRIPT_VERSION = "0.1.10"
SCRIPT_LAST_UPDATED = "2026-03-08"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FASTRESUME_DIR = Path(
    "/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"
)
DEFAULT_VERIFIER = REPO_ROOT / "bin" / "qb-libtorrent-verify.py"
DEFAULT_LOG_DIR = Path.home() / ".logs" / SCRIPT_NAME
DEFAULT_PILOT_SIZE = 5
DEFAULT_CLEANUP_PILOT_SIZE = 1
DEFAULT_CLEANUP_OBSERVE_SECONDS = 60.0
DEFAULT_CLEANUP_STAGE_DIRNAME = ".qb-zfs-relocate-staging"
DEFAULT_AUTO_CLEANUP_MODE = "off"
PAUSED_STATES = {
    "pausedup",
    "pauseddl",
    "stoppedup",
    "stoppeddl",
    "queuedup",
    "queueddl",
    "missingfiles",
    "error",
}
BAD_RESUME_STATES = {
    "missingfiles",
    "error",
    "checkingup",
    "checkingdl",
    "checkingresumedata",
    "downloading",
    "forceddl",
    "stalleddl",
    "metadl",
}
GOOD_RESUME_STATES = {
    "stalledup",
    "uploading",
    "forcedup",
    "pausedup",
    "queuedup",
    "stoppedup",
}
FINAL_CLEANUP_STATES = {"cleaned", "source_missing"}
_RUN_TEXT_LOG_PATH: Optional[Path] = None
_RUN_JSONL_LOG_PATH: Optional[Path] = None
_RUN_TEXT_LOG_HANDLE: Any = None


class RelocationError(RuntimeError):
    """Raised for fail-closed relocation workflow errors."""


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def format_hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--:--:--"
    try:
        total = int(round(float(seconds)))
    except Exception:
        return "--:--:--"
    if total < 0:
        total = 0
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def estimate_remaining_seconds(
    *,
    completed_items: int,
    completed_seconds: float,
    current_elapsed_seconds: float,
    remaining_items: int,
) -> Optional[float]:
    if remaining_items <= 0:
        return 0.0
    observed_items = int(completed_items) + (1 if current_elapsed_seconds > 0.0 else 0)
    observed_seconds = float(completed_seconds) + max(0.0, float(current_elapsed_seconds))
    if observed_items <= 0 or observed_seconds <= 0.0:
        return None
    avg_seconds = observed_seconds / float(observed_items)
    return avg_seconds * float(remaining_items)


def dedupe_preserve(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def normalize_hashes(values: Iterable[str]) -> List[str]:
    return dedupe_preserve(str(value or "").strip().lower() for value in values)


def normalize_batch_size(value: int) -> int:
    size = int(value or 0)
    if size < 0:
        raise RelocationError("batch_size_must_be_non_negative")
    return size


def normalize_cleanup_mode(value: str) -> str:
    mode = str(value or DEFAULT_AUTO_CLEANUP_MODE).strip().lower()
    if mode in {"", "0", "false", "no", "off"}:
        return "off"
    if mode == "safe":
        return mode
    raise RelocationError(f"unsupported_auto_cleanup_mode mode={value}")


def replace_root(path: str, source_root: str, dest_root: str) -> str:
    normalized_path = normalize_save_path(path)
    source = normalize_save_path(source_root)
    dest = normalize_save_path(dest_root)
    if normalized_path == source:
        return dest
    prefix = source + "/"
    if not normalized_path.startswith(prefix):
        raise RelocationError(
            f"path_outside_source_root path={normalized_path!r} source_root={source!r}"
        )
    return dest + normalized_path[len(source) :]


def path_is_same_or_child(path: str, root: str) -> bool:
    try:
        normalized_path = normalize_save_path(path)
        normalized_root = normalize_save_path(root)
    except Exception:
        return False
    return normalized_path == normalized_root or normalized_path.startswith(
        normalized_root + "/"
    )


def path_kind(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_dir():
        return "dir"
    if path.is_file():
        return "file"
    return "other"


def path_depth_under_root(path: str, root: str) -> int:
    normalized_path = normalize_save_path(path)
    normalized_root = normalize_save_path(root)
    if normalized_path == normalized_root:
        return 0
    prefix = normalized_root + "/"
    if not normalized_path.startswith(prefix):
        return -1
    rel = normalized_path[len(prefix) :]
    return len([part for part in rel.split("/") if part])


def paths_overlap(path_a: str, path_b: str) -> bool:
    normalized_a = normalize_save_path(path_a)
    normalized_b = normalize_save_path(path_b)
    return (
        normalized_a == normalized_b
        or normalized_a.startswith(normalized_b + "/")
        or normalized_b.startswith(normalized_a + "/")
    )


def is_cleanup_safe_state(state: str) -> bool:
    value = str(state or "").strip().lower()
    if not value:
        return False
    if value in BAD_RESUME_STATES:
        return False
    if value.startswith("checking") or value.startswith("downloading"):
        return False
    return True


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def resolve_log_dir() -> Path:
    return Path(
        os.environ.get("QB_ZFS_RELOCATE_LOG_DIR", str(DEFAULT_LOG_DIR))
    ).expanduser()


def sanitize_log_component(value: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_"
        for ch in str(value or "").strip().lower()
    )
    return cleaned.strip("_") or "run"


def _write_log_text(text: str, *, raw: bool = False) -> None:
    handle = _RUN_TEXT_LOG_HANDLE
    if handle is None:
        return
    if raw:
        handle.write(text)
        if text and not text.endswith("\n"):
            handle.write("\n")
    else:
        handle.write(text.rstrip("\n") + "\n")
    handle.flush()


def to_log_json(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_log_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_log_json(item) for item in value]
    return value


def _record_log_event(event: str, **fields: Any) -> None:
    if _RUN_JSONL_LOG_PATH is None:
        return
    payload: Dict[str, Any] = {"timestamp": ts_iso(), "event": event}
    payload.update({key: to_log_json(value) for key, value in fields.items()})
    append_jsonl(_RUN_JSONL_LOG_PATH, payload)


def format_event_line(event: str, **fields: Any) -> str:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", "\\n")
        if " " in text:
            text = json.dumps(text)
        parts.append(f"{key}={text}")
    return " ".join(parts)


def log_only(event: str, **fields: Any) -> None:
    _write_log_text(format_event_line(event, **fields))
    _record_log_event(event, **fields)


def emit_log(event: str, **fields: Any) -> None:
    line = format_event_line(event, **fields)
    print(line, flush=True)
    _write_log_text(line)
    _record_log_event(event, **fields)


def initialize_run_logging(*, phase: str, argv: Sequence[str], manifest_path: Optional[Path]) -> None:
    global _RUN_TEXT_LOG_PATH, _RUN_JSONL_LOG_PATH, _RUN_TEXT_LOG_HANDLE
    log_dir = resolve_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise RelocationError(f"log_dir_not_writable path={log_dir} error={exc}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"{stamp}-{sanitize_log_component(phase)}-pid{os.getpid()}"
    _RUN_TEXT_LOG_PATH = log_dir / f"{stem}.log"
    _RUN_JSONL_LOG_PATH = log_dir / f"{stem}.jsonl"
    _RUN_TEXT_LOG_HANDLE = _RUN_TEXT_LOG_PATH.open("a", encoding="utf-8", buffering=1)
    log_only(
        "log_open",
        phase=phase,
        cwd=os.getcwd(),
        manifest=str(manifest_path) if manifest_path else "",
        argv=json.dumps(list(argv)),
        text_log=_RUN_TEXT_LOG_PATH,
        jsonl_log=_RUN_JSONL_LOG_PATH,
    )


def close_run_logging() -> None:
    global _RUN_TEXT_LOG_PATH, _RUN_JSONL_LOG_PATH, _RUN_TEXT_LOG_HANDLE
    handle = _RUN_TEXT_LOG_HANDLE
    if handle is not None:
        handle.close()
    _RUN_TEXT_LOG_PATH = None
    _RUN_JSONL_LOG_PATH = None
    _RUN_TEXT_LOG_HANDLE = None


def emit_run_boundary(event: str, *, exit_code: Optional[int] = None, **extra_fields: Any) -> None:
    fields: Dict[str, Any] = {
        "script": SCRIPT_NAME,
        "version": SCRIPT_VERSION,
        "last_updated": SCRIPT_LAST_UPDATED,
        "timestamp": ts_iso(),
    }
    if exit_code is not None:
        fields["exit_code"] = int(exit_code)
    if _RUN_TEXT_LOG_PATH is not None:
        fields["text_log"] = _RUN_TEXT_LOG_PATH
    if _RUN_JSONL_LOG_PATH is not None:
        fields["jsonl_log"] = _RUN_JSONL_LOG_PATH
    fields.update(extra_fields)
    emit_log(event, **fields)


def emit_summary(summary: Dict[str, Any]) -> None:
    print("[📊 Summary]", flush=True)
    _write_log_text("[📊 Summary]")
    for key in sorted(summary.keys()):
        line = f"{key}={summary[key]}"
        print(line, flush=True)
        _write_log_text(line)
    _record_log_event("summary", summary=dict(summary))


def load_hashes_file(path: Path) -> List[str]:
    values: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = str(raw or "").strip()
        if not line or line.startswith("#"):
            continue
        values.append(line)
    return normalize_hashes(values)


def manifest_report_path(manifest_path: Path, phase: str, suffix: str = ".json") -> Path:
    return manifest_path.parent / f"{manifest_path.stem}-{phase}{suffix}"


def set_row_issues(row: Dict[str, Any], issues: Iterable[str]) -> None:
    row["issues"] = sorted(dedupe_preserve(str(issue) for issue in issues if str(issue).strip()))


def add_issue(row: Dict[str, Any], issue: str) -> None:
    issues = list(row.get("issues") or [])
    issues.append(issue)
    set_row_issues(row, issues)


def remove_issue(row: Dict[str, Any], issue: str) -> None:
    set_row_issues(row, [value for value in row.get("issues") or [] if value != issue])


def row_selection(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in rows if bool(row.get("selected"))]


def is_stopped_state(state: str) -> bool:
    value = str(state or "").strip().lower()
    return value in PAUSED_STATES or value.startswith("paused") or value.startswith("stopped")


def should_trust_offline_verify_over_qb_progress(row: Dict[str, Any]) -> bool:
    return bool(row.get("verified")) and str(row.get("copy_status") or "") == "reused_existing_dest"


def load_torrent_metadata(path: Path) -> Dict[str, Any]:
    doc = bencode_decode(path.read_bytes())
    if not isinstance(doc, dict):
        raise RelocationError(f"invalid_torrent_dict path={path}")
    info = doc.get(b"info")
    if not isinstance(info, dict):
        raise RelocationError(f"missing_torrent_info path={path}")
    root_name = as_text(info.get(b"name", b"")).strip()
    if not root_name:
        raise RelocationError(f"missing_torrent_name path={path}")
    files = info.get(b"files")
    entries: List[Dict[str, Any]] = []
    if isinstance(files, list):
        for raw in files:
            if not isinstance(raw, dict):
                raise RelocationError(f"invalid_torrent_file_entry path={path}")
            parts = raw.get(b"path.utf-8") or raw.get(b"path")
            if not isinstance(parts, list):
                raise RelocationError(f"invalid_torrent_file_path path={path}")
            rel_parts = [as_text(part).replace("\\", "/").strip("/") for part in parts]
            rel_path = "/".join(part for part in rel_parts if part)
            entries.append(
                {
                    "path": rel_path,
                    "size": int(raw.get(b"length", 0) or 0),
                }
            )
        is_multi_file = True
    else:
        entries.append(
            {
                "path": root_name,
                "size": int(info.get(b"length", 0) or 0),
            }
        )
        is_multi_file = False
    return {
        "root_name": root_name,
        "entries": entries,
        "is_multi_file": is_multi_file,
    }


def expected_content_path(save_path: str, metadata: Dict[str, Any]) -> str:
    return str(Path(normalize_save_path(save_path)) / str(metadata["root_name"]))


def build_manifest_row_for_relocation(
    *,
    torrent_hash: str,
    qb_client: QBittorrentClient,
    fastresume_dir: Path,
    torrent_dir: Path,
    target_save_path: str,
    source_root: str,
    dest_root: str,
    source_save_path: Optional[str] = None,
    info: Optional[Any] = None,
) -> Dict[str, Any]:
    issues: List[str] = []
    info = info or qb_client.get_torrent_info(torrent_hash)
    fastresume_path = fastresume_dir / f"{torrent_hash}.fastresume"
    torrent_path = torrent_dir / f"{torrent_hash}.torrent"
    if not torrent_path.exists():
        backup_torrent = fastresume_dir / f"{torrent_hash}.torrent"
        if backup_torrent.exists():
            torrent_path = backup_torrent
        elif hasattr(qb_client, "export_torrent_file"):
            blob = qb_client.export_torrent_file(torrent_hash, torrent_path)
            if not blob:
                issues.append("torrent_metadata_missing")
    if info is None:
        issues.append("qb_torrent_not_found")
    if not fastresume_path.exists():
        issues.append("fastresume_missing")
    if not torrent_path.exists():
        issues.append("torrent_metadata_missing")

    old_save_path = ""
    old_qbt_save_path = ""
    old_qbt_download_path = ""
    if fastresume_path.exists():
        try:
            fastresume = read_fastresume(fastresume_path)
            old_save_path = as_text(fastresume.get(b"save_path", b"")).strip()
            old_qbt_save_path = as_text(
                fastresume.get(b"qBt-savePath", b"")
            ).strip()
            old_qbt_download_path = as_text(
                fastresume.get(b"qBt-downloadPath", b"")
            ).strip()
        except Exception as exc:
            issues.append(f"fastresume_read_error:{exc}")

    metadata: Optional[Dict[str, Any]] = None
    if torrent_path.exists():
        try:
            metadata = load_torrent_metadata(torrent_path)
        except Exception as exc:
            issues.append(f"torrent_metadata_error:{exc}")

    if info is not None and old_save_path and normalize_save_path(old_save_path) != normalize_save_path(info.save_path):
        issues.append("save_path_mismatch_api_fastresume")
    if not old_save_path:
        old_save_path = str(source_save_path or getattr(info, "save_path", "") or "").strip()
    if not old_qbt_save_path:
        old_qbt_save_path = old_save_path

    content_path = str(getattr(info, "content_path", "") or "").strip() if info else ""
    expected_root_name = ""
    is_multi_file = False
    path_shape_match = False
    dest_content_path = ""
    target_save_path_n = normalize_save_path(target_save_path)
    if metadata is not None:
        expected_root_name = str(metadata["root_name"])
        is_multi_file = bool(metadata["is_multi_file"])
        if old_save_path:
            expected_old_content = expected_content_path(old_save_path, metadata)
            if not content_path:
                content_path = expected_old_content
            path_shape_match = normalize_save_path(content_path) == normalize_save_path(
                expected_old_content
            )
            dest_content_path = expected_content_path(target_save_path_n, metadata)
        else:
            issues.append("missing_old_save_path")

    dest_path_obj = Path(dest_content_path) if dest_content_path else Path("/")
    row = {
        "hash": torrent_hash,
        "name": getattr(info, "name", "") if info else "",
        "state": getattr(info, "state", "") if info else "",
        "progress": float(getattr(info, "progress", 0.0) or 0.0) if info else 0.0,
        "selected": True,
        "fastresume_path": str(fastresume_path),
        "torrent_path": str(torrent_path),
        "old_save_path": old_save_path,
        "old_qbt_save_path": old_qbt_save_path,
        "old_qbt_download_path": old_qbt_download_path,
        "content_path": content_path,
        "source_root": normalize_save_path(source_root),
        "dest_root": normalize_save_path(dest_root),
        "new_save_path": target_save_path_n,
        "dest_content_path": dest_content_path,
        "dest_exists": bool(dest_content_path and dest_path_obj.exists()),
        "dest_kind": path_kind(dest_path_obj) if dest_content_path else "missing",
        "is_multi_file": is_multi_file,
        "expected_root_name": expected_root_name,
        "path_shape_match": bool(path_shape_match),
        "verified": False,
        "actionable": False,
        "copy_status": "pending",
        "verify_status": "pending",
        "verify_report_path": "",
        "verify_classification": "",
        "source_recheck_status": "pending",
        "source_recheck_before_state": "",
        "source_recheck_before_progress": 0.0,
        "source_recheck_after_state": "",
        "source_recheck_after_progress": 0.0,
        "source_recheck_elapsed_seconds": 0.0,
        "cleanup_status": "pending",
        "cleanup_ready": False,
        "cleanup_issues": [],
        "cleanup_staged_path": "",
        "plan_issues": sorted(dedupe_preserve(issues)),
        "issues": sorted(dedupe_preserve(issues)),
    }
    return row


def build_manifest_for_relocations(
    *,
    qb_client: QBittorrentClient,
    relocations: Sequence[Dict[str, Any]],
    fastresume_dir: Path,
    torrent_dir: Path,
    source_root: str,
    dest_root: str,
    mode: str,
    apply_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    info_by_hash = qb_client.get_torrents_by_hashes(
        [str(relocation.get("torrent_hash") or "") for relocation in relocations]
    )
    rows = [
        build_manifest_row_for_relocation(
            torrent_hash=str(relocation.get("torrent_hash") or ""),
            qb_client=qb_client,
            fastresume_dir=fastresume_dir,
            torrent_dir=torrent_dir,
            target_save_path=str(relocation.get("target_save_path") or ""),
            source_root=source_root,
            dest_root=dest_root,
            source_save_path=str(relocation.get("source_save_path") or ""),
            info=info_by_hash.get(str(relocation.get("torrent_hash") or "").lower()),
        )
        for relocation in relocations
        if str(relocation.get("torrent_hash") or "").strip()
    ]
    return {
        "version": "1.0",
        "generated_at": ts_iso(),
        "mode": mode,
        "selection_mode": "rehome_relocations",
        "global_issues": [],
        "phase_history": [],
        "apply_context": dict(apply_context or {}),
        "rows": rows,
    }


class SubprocessRunner:
    """Thin subprocess wrapper that is easy to stub in tests."""

    def run(
        self,
        cmd: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = list(cmd)
        started_at = time.monotonic()
        log_only("command_start", cmd=command, capture_output=bool(capture_output))
        if capture_output:
            proc = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
            )
            if proc.stdout:
                for line in str(proc.stdout).splitlines():
                    _write_log_text(f"stdout> {line}")
            if proc.stderr:
                for line in str(proc.stderr).splitlines():
                    _write_log_text(f"stderr> {line}")
        else:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            chunks: List[str] = []
            assert process.stdout is not None
            for chunk in process.stdout:
                chunks.append(chunk)
                sys.stdout.write(chunk)
                sys.stdout.flush()
                _write_log_text(chunk, raw=True)
            process.stdout.close()
            returncode = int(process.wait())
            proc = subprocess.CompletedProcess(command, returncode, "".join(chunks), "")
        elapsed_seconds = max(0.0, time.monotonic() - started_at)
        log_only(
            "command_end",
            cmd=command,
            capture_output=bool(capture_output),
            rc=int(proc.returncode),
            elapsed=format_hms(elapsed_seconds),
            elapsed_s=round(elapsed_seconds, 3),
        )
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode,
                command,
                output=proc.stdout,
                stderr=proc.stderr,
            )
        return proc


class QBProcessController:
    """Abstract controller for qBittorrent process lifecycle."""

    def is_stopped(self) -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError


class DockerQbController(QBProcessController):
    """Docker-based qBittorrent lifecycle controller."""

    def __init__(self, container: str, runner: Optional[SubprocessRunner] = None):
        self.container = str(container or "").strip()
        self.runner = runner or SubprocessRunner()

    def is_stopped(self) -> bool:
        proc = self.runner.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", self.container]
        )
        if proc.returncode != 0:
            raise RelocationError(
                f"docker_inspect_failed container={self.container} stderr={(proc.stderr or '').strip()}"
            )
        return (proc.stdout or "").strip().lower() != "true"

    def stop(self) -> None:
        proc = self.runner.run(["docker", "stop", self.container])
        if proc.returncode != 0:
            raise RelocationError(
                f"docker_stop_failed container={self.container} stderr={(proc.stderr or '').strip()}"
            )

    def start(self) -> None:
        proc = self.runner.run(["docker", "start", self.container])
        if proc.returncode != 0:
            raise RelocationError(
                f"docker_start_failed container={self.container} stderr={(proc.stderr or '').strip()}"
            )


class CommandQbController(QBProcessController):
    """Command-based qBittorrent lifecycle controller."""

    def __init__(
        self,
        status_cmd: str,
        stop_cmd: str,
        start_cmd: str,
        runner: Optional[SubprocessRunner] = None,
    ):
        self.status_cmd = shlex.split(status_cmd)
        self.stop_cmd = shlex.split(stop_cmd)
        self.start_cmd = shlex.split(start_cmd)
        self.runner = runner or SubprocessRunner()

    def is_stopped(self) -> bool:
        proc = self.runner.run(self.status_cmd)
        if proc.returncode != 0:
            raise RelocationError(
                f"qb_status_cmd_failed stderr={(proc.stderr or '').strip()}"
            )
        state = (proc.stdout or "").strip().lower()
        return state in {"stopped", "inactive", "false", "0", "off"}

    def stop(self) -> None:
        proc = self.runner.run(self.stop_cmd)
        if proc.returncode != 0:
            raise RelocationError(
                f"qb_stop_cmd_failed stderr={(proc.stderr or '').strip()}"
            )

    def start(self) -> None:
        proc = self.runner.run(self.start_cmd)
        if proc.returncode != 0:
            raise RelocationError(
                f"qb_start_cmd_failed stderr={(proc.stderr or '').strip()}"
            )


class LibtorrentVerifier:
    """Offline verifier wrapper around qb-libtorrent-verify.py."""

    def __init__(
        self,
        *,
        runner: Optional[SubprocessRunner] = None,
        verifier_script: Optional[Path] = None,
        python_bin: Optional[str] = None,
    ):
        self.runner = runner or SubprocessRunner()
        self.verifier_script = Path(verifier_script or DEFAULT_VERIFIER)
        self.python_bin = str(python_bin or sys.executable)

    def verify(
        self,
        torrent_path: Path,
        candidate_path: Path,
        report_path: Path,
        *,
        timeout_seconds: float,
        quick_only: bool,
        show_progress: bool,
    ) -> Dict[str, Any]:
        if not self.verifier_script.exists():
            raise RelocationError(f"verifier_script_not_found path={self.verifier_script}")
        cmd = [
            self.python_bin,
            str(self.verifier_script),
            "--torrent",
            str(torrent_path),
            "--path",
            str(candidate_path),
            "--json-out",
            str(report_path),
            "--quiet-summary",
            "--timeout",
            str(float(timeout_seconds)),
        ]
        if show_progress:
            cmd.append("--show-progress")
        if quick_only:
            cmd.append("--quick-only")
        proc = self.runner.run(cmd, capture_output=not show_progress)
        if not report_path.exists():
            raise RelocationError(
                f"verify_report_missing path={report_path} rc={proc.returncode}"
            )
        payload = load_json(report_path)
        payload["_returncode"] = int(proc.returncode)
        payload["_stdout"] = (proc.stdout or "").strip()
        payload["_stderr"] = (proc.stderr or "").strip()
        return payload


class QBZFSRelocationTool:
    """Implements the plan/copy/verify/validate/patch/resume/cleanup/rollback phases."""

    def __init__(
        self,
        *,
        qb_client: Optional[QBittorrentClient] = None,
        runner: Optional[SubprocessRunner] = None,
        verifier: Optional[LibtorrentVerifier] = None,
        process_controller: Optional[QBProcessController] = None,
        sleep_fn=time.sleep,
    ):
        self.qb_client = qb_client or get_qbittorrent_client()
        self.runner = runner or SubprocessRunner()
        self.verifier = verifier or LibtorrentVerifier(runner=self.runner)
        self.process_controller = process_controller
        self.sleep_fn = sleep_fn

    def _save_manifest(
        self,
        manifest_path: Path,
        manifest: Dict[str, Any],
        *,
        phase: str,
        mode: str,
        report_path: Optional[Path] = None,
    ) -> None:
        manifest.setdefault("phase_history", []).append(
            {
                "phase": phase,
                "mode": mode,
                "timestamp": ts_iso(),
                "report_path": str(report_path) if report_path else "",
            }
        )
        manifest["updated_at"] = ts_iso()
        write_json(manifest_path, manifest)

    def _checkpoint_manifest(self, manifest_path: Path, manifest: Dict[str, Any]) -> None:
        manifest["updated_at"] = ts_iso()
        write_json(manifest_path, manifest)

    def _load_manifest(self, manifest_path: Path) -> Dict[str, Any]:
        manifest = load_json(manifest_path)
        if not isinstance(manifest, dict):
            raise RelocationError(f"invalid_manifest path={manifest_path}")
        manifest.setdefault("rows", [])
        manifest.setdefault("global_issues", [])
        for row in manifest.get("rows", []):
            row.setdefault("verify_classification", "")
            row.setdefault("source_recheck_status", "pending")
            row.setdefault("source_recheck_before_state", "")
            row.setdefault("source_recheck_before_progress", 0.0)
            row.setdefault("source_recheck_after_state", "")
            row.setdefault("source_recheck_after_progress", 0.0)
            row.setdefault("source_recheck_elapsed_seconds", 0.0)
            row.setdefault("cleanup_status", "pending")
            row.setdefault("cleanup_ready", False)
            row.setdefault("cleanup_issues", [])
            row.setdefault("cleanup_staged_path", "")
        return manifest

    def _selected_rows(self, manifest_path: Path) -> List[Dict[str, Any]]:
        return row_selection(self._load_manifest(manifest_path).get("rows", []))

    def _wait_for_stopped(self, torrent_hash: str, *, timeout_seconds: float = 60.0) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            info = self.qb_client.get_torrent_info(torrent_hash)
            if info and is_stopped_state(info.state):
                return
            self.sleep_fn(1.0)
        raise RelocationError(f"torrent_not_stopped hash={torrent_hash}")

    def _wait_for_qb_online(self, *, timeout_seconds: float = 60.0) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                if self.qb_client.test_connection():
                    return
            except Exception:
                pass
            self.sleep_fn(1.0)
        raise RelocationError("qBittorrent_not_online")

    def _ensure_controller(self) -> QBProcessController:
        if self.process_controller is None:
            raise RelocationError("qb_process_controller_required")
        return self.process_controller

    def _ensure_qb_online_for_orchestration(self, *, timeout_seconds: float) -> None:
        controller = self._ensure_controller()
        if controller.is_stopped():
            emit_log("qb_start", phase="plan", reason="prepare_for_orchestration")
            controller.start()
        if not self.qb_client.test_connection():
            emit_log(
                "qb_wait",
                phase="plan",
                reason="wait_for_qb_webui",
                timeout_seconds=timeout_seconds,
            )
            self._wait_for_qb_online(timeout_seconds=timeout_seconds)

    def _pause_selected(self, rows: Sequence[Dict[str, Any]]) -> None:
        hashes = [row["hash"] for row in rows if row.get("selected")]
        if not hashes:
            return
        if not self.qb_client.pause_torrents(hashes):
            raise RelocationError("pause_selected_failed")
        for torrent_hash in hashes:
            self._wait_for_stopped(torrent_hash)

    def _refresh_rows_from_qb(self, rows: Sequence[Dict[str, Any]]) -> None:
        for row in rows:
            info = self.qb_client.get_torrent_info(str(row.get("hash") or ""))
            if info is None:
                continue
            row["state"] = str(info.state or "")
            row["progress"] = float(info.progress or 0.0)

    def _cleanup_journal_path(self, manifest_path: Path, journal_path: Optional[Path]) -> Path:
        return journal_path or manifest_report_path(manifest_path, "cleanup-journal", ".jsonl")

    def _cleanup_stage_path(self, manifest_path: Path, row: Dict[str, Any]) -> Path:
        existing = str(row.get("cleanup_staged_path") or "").strip()
        if existing:
            return Path(existing)
        source_root = normalize_save_path(str(row.get("source_root") or ""))
        source_path = Path(str(row.get("content_path") or ""))
        stage_name = f"{row['hash']}-{source_path.name or row['hash']}"
        return (
            Path(source_root)
            / DEFAULT_CLEANUP_STAGE_DIRNAME
            / manifest_path.stem
            / stage_name
        )

    def _prune_empty_stage_parents(self, manifest_path: Path, stage_path: Path, source_root: str) -> None:
        stage_root = Path(normalize_save_path(source_root)) / DEFAULT_CLEANUP_STAGE_DIRNAME / manifest_path.stem
        current = stage_path.parent
        while current != stage_root.parent and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _load_cleanup_verify_summary(
        self,
        row: Dict[str, Any],
    ) -> tuple[bool, Dict[str, Any], str]:
        if not bool(row.get("verified")):
            return False, {}, "cleanup_verify_not_marked_verified"
        report_path_raw = str(row.get("verify_report_path") or "").strip()
        if not report_path_raw:
            return False, {}, "cleanup_verify_report_missing"
        report_path = Path(report_path_raw)
        if not report_path.exists():
            return False, {}, "cleanup_verify_report_missing"
        payload = load_json(report_path)
        summary = dict(payload.get("summary") or {})
        if int(summary.get("verified", 0) or 0) <= 0:
            return False, summary, "cleanup_verify_report_not_verified"
        best_path = str(summary.get("best_path") or "")
        if best_path != str(row.get("dest_content_path") or ""):
            return False, summary, "cleanup_verify_report_path_mismatch"
        return True, summary, ""

    def _recheck_source_after_verify_failure(
        self,
        row: Dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        info = self.qb_client.get_torrent_info(str(row.get("hash") or ""))
        before_state = str(getattr(info, "state", "") or "")
        before_progress = float(getattr(info, "progress", 0.0) or 0.0)
        snapshot: Dict[str, Any] = {
            "requested": False,
            "completed": False,
            "timed_out": False,
            "before_state": before_state,
            "before_progress": before_progress,
            "after_state": before_state,
            "after_progress": before_progress,
            "elapsed_seconds": 0.0,
        }
        if info is None:
            snapshot["status"] = "torrent_missing"
            return snapshot
        emit_log(
            "source_recheck_start",
            phase="verify",
            hash=row["hash"],
            state=before_state,
            progress=before_progress,
        )
        if not self.qb_client.recheck_torrent(row["hash"]):
            snapshot["status"] = "request_failed"
            return snapshot
        snapshot["requested"] = True
        deadline = time.time() + max(1.0, float(timeout_seconds))
        started_at = time.monotonic()
        last_emit_at = 0.0
        while True:
            info = self.qb_client.get_torrent_info(str(row.get("hash") or ""))
            state = str(getattr(info, "state", "") or "")
            progress = float(getattr(info, "progress", 0.0) or 0.0)
            snapshot["after_state"] = state
            snapshot["after_progress"] = progress
            elapsed = max(0.0, time.monotonic() - started_at)
            snapshot["elapsed_seconds"] = elapsed
            if info is not None and not state.lower().startswith("checking"):
                snapshot["completed"] = True
                snapshot["status"] = "completed"
                emit_log(
                    "source_recheck_end",
                    phase="verify",
                    hash=row["hash"],
                    status="completed",
                    elapsed=format_hms(elapsed),
                    state=state,
                    progress=progress,
                )
                return snapshot
            if time.time() >= deadline:
                snapshot["timed_out"] = True
                snapshot["status"] = "timeout"
                emit_log(
                    "source_recheck_end",
                    phase="verify",
                    hash=row["hash"],
                    status="timeout",
                    elapsed=format_hms(elapsed),
                    state=state,
                    progress=progress,
                )
                return snapshot
            now = time.monotonic()
            if last_emit_at <= 0.0 or now - last_emit_at >= 5.0:
                emit_log(
                    "source_recheck_progress",
                    phase="verify",
                    hash=row["hash"],
                    elapsed=format_hms(elapsed),
                    eta=format_hms(max(0.0, deadline - time.time())),
                    state=state,
                    progress=progress,
                )
                last_emit_at = now
            self.sleep_fn(1.0)

    def _cleanup_qb_snapshot(self, row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            info = self.qb_client.get_torrent_info(str(row.get("hash") or ""))
        except Exception as exc:
            return {"found": False, "error": str(exc)}
        if info is None:
            return {"found": False}
        return {
            "found": True,
            "state": str(getattr(info, "state", "") or ""),
            "progress": float(getattr(info, "progress", 0.0) or 0.0),
            "save_path": str(getattr(info, "save_path", "") or ""),
        }

    def _cleanup_snapshot_issues(
        self,
        row: Dict[str, Any],
        snapshot: Dict[str, Any],
    ) -> List[str]:
        issues: List[str] = []
        if not snapshot.get("found"):
            issues.append(
                "cleanup_qb_query_failed"
                if snapshot.get("error")
                else "cleanup_qb_torrent_missing"
            )
            return issues
        save_path = str(snapshot.get("save_path") or "")
        new_save_path = str(row.get("new_save_path") or "")
        if not save_path or not new_save_path:
            issues.append("cleanup_save_path_missing")
        else:
            if normalize_save_path(save_path) != normalize_save_path(new_save_path):
                issues.append("cleanup_save_path_mismatch")
        progress = float(snapshot.get("progress", 0.0) or 0.0)
        if progress < 1.0:
            issues.append("cleanup_torrent_not_complete")
        state = str(snapshot.get("state") or "")
        if not is_cleanup_safe_state(state):
            issues.append("cleanup_state_not_safe")
        return issues

    def _append_cleanup_journal(
        self,
        journal_path: Path,
        *,
        row: Dict[str, Any],
        action: str,
        decision: str,
        status: str,
        source_path: Path,
        staged_path: Path,
        snapshot: Optional[Dict[str, Any]] = None,
        details: str = "",
    ) -> None:
        append_jsonl(
            journal_path,
            {
                "timestamp": ts_iso(),
                "hash": row["hash"],
                "name": row.get("name", ""),
                "action": action,
                "decision": decision,
                "status": status,
                "details": details,
                "source_path": str(source_path),
                "staged_path": str(staged_path),
                "new_save_path": row.get("new_save_path", ""),
                "verify_report_path": row.get("verify_report_path", ""),
                "cleanup_status": row.get("cleanup_status", ""),
                "qb_state": str((snapshot or {}).get("state") or ""),
                "qb_progress": float((snapshot or {}).get("progress", 0.0) or 0.0),
                "qb_save_path": str((snapshot or {}).get("save_path") or ""),
            },
        )

    def _observe_cleanup_row(
        self,
        row: Dict[str, Any],
        *,
        observe_seconds: float,
    ) -> Dict[str, Any]:
        deadline = time.time() + max(0.0, float(observe_seconds))
        first_pass = True
        last_emit_at = 0.0
        started_at = time.monotonic()
        latest_snapshot: Dict[str, Any] = {}
        while first_pass or time.time() < deadline:
            first_pass = False
            latest_snapshot = self._cleanup_qb_snapshot(row)
            issues = self._cleanup_snapshot_issues(row, latest_snapshot)
            if issues:
                raise RelocationError(",".join(issues))
            now = time.monotonic()
            if observe_seconds > 0.0 and (
                last_emit_at <= 0.0 or now - last_emit_at >= 5.0
            ):
                emit_log(
                    "cleanup_observe_progress",
                    phase="cleanup",
                    hash=row["hash"],
                    elapsed=format_hms(now - started_at),
                    eta=format_hms(max(0.0, deadline - time.time())),
                    state=str(latest_snapshot.get("state") or ""),
                )
                last_emit_at = now
            if time.time() < deadline:
                self.sleep_fn(1.0)
        return latest_snapshot

    def _torrent_matches_source_root(self, info: Any, source_root: str) -> bool:
        candidates = [
            str(getattr(info, "save_path", "") or "").strip(),
            str(getattr(info, "content_path", "") or "").strip(),
        ]
        return any(path_is_same_or_child(candidate, source_root) for candidate in candidates if candidate)

    def _resolve_plan_selection(
        self,
        *,
        hashes: Sequence[str],
        source_root: str,
        batch_size: int,
    ) -> tuple[List[str], Dict[str, Any], Dict[str, Any]]:
        requested_batch_size = normalize_batch_size(batch_size)
        all_hashes = normalize_hashes(hashes)
        if all_hashes:
            selected_hashes = (
                all_hashes[:requested_batch_size]
                if requested_batch_size
                else all_hashes
            )
            return (
                selected_hashes,
                self.qb_client.get_torrents_by_hashes(selected_hashes),
                {
                    "mode": "explicit_hashes",
                    "hashes": selected_hashes,
                    "matched": len(all_hashes),
                    "batch_size": requested_batch_size,
                },
            )
        if not hasattr(self.qb_client, "get_torrents"):
            raise RelocationError("qb_client_list_torrents_not_supported")
        all_torrents = list(self.qb_client.get_torrents() or [])
        info_by_hash: Dict[str, Any] = {}
        for info in all_torrents:
            torrent_hash = str(getattr(info, "hash", "") or "").strip().lower()
            if torrent_hash:
                info_by_hash[torrent_hash] = info
        all_hashes = normalize_hashes(
            torrent_hash
            for torrent_hash, info in info_by_hash.items()
            if self._torrent_matches_source_root(info, source_root)
            and Path(str(getattr(info, "content_path", "") or "").strip()).exists()
        )
        selected_hashes = (
            all_hashes[:requested_batch_size]
            if requested_batch_size
            else all_hashes
        )
        if not selected_hashes:
            raise RelocationError(f"no_torrents_found_under_source_root source_root={source_root}")
        return (
            selected_hashes,
            {torrent_hash: info_by_hash[torrent_hash] for torrent_hash in selected_hashes},
            {
                "mode": "auto_source_root",
                "source_root": source_root,
                "hashes": selected_hashes,
                "matched": len(all_hashes),
                "batch_size": requested_batch_size,
            },
        )

    def plan(
        self,
        *,
        manifest_path: Path,
        hashes: Sequence[str],
        source_root: str,
        dest_root: str,
        batch_size: int = 0,
        fastresume_dir: Path,
        torrent_dir: Path,
        export_torrents_dir: Optional[Path],
    ) -> int:
        source_root_n = normalize_save_path(source_root)
        dest_root_n = normalize_save_path(dest_root)
        if source_root_n == dest_root_n:
            raise RelocationError("source_and_destination_roots_must_differ")
        selected_hashes, info_by_hash, selection = self._resolve_plan_selection(
            hashes=hashes,
            source_root=source_root_n,
            batch_size=batch_size,
        )
        rows: List[Dict[str, Any]] = []
        for torrent_hash in selected_hashes:
            issues: List[str] = []
            info = info_by_hash.get(torrent_hash)
            fastresume_path = fastresume_dir / f"{torrent_hash}.fastresume"
            torrent_path = torrent_dir / f"{torrent_hash}.torrent"
            if not torrent_path.exists() and export_torrents_dir is not None and hasattr(
                self.qb_client, "export_torrent_file"
            ):
                export_target = export_torrents_dir / f"{torrent_hash}.torrent"
                blob = self.qb_client.export_torrent_file(torrent_hash, export_target)
                if blob:
                    torrent_path = export_target
            if info is None:
                issues.append("qb_torrent_not_found")
            if not fastresume_path.exists():
                issues.append("fastresume_missing")
            if not torrent_path.exists():
                issues.append("torrent_metadata_missing")

            old_save_path = ""
            old_qbt_save_path = ""
            old_qbt_download_path = ""
            if fastresume_path.exists():
                try:
                    fastresume = read_fastresume(fastresume_path)
                    old_save_path = as_text(fastresume.get(b"save_path", b"")).strip()
                    old_qbt_save_path = as_text(
                        fastresume.get(b"qBt-savePath", b"")
                    ).strip()
                    old_qbt_download_path = as_text(
                        fastresume.get(b"qBt-downloadPath", b"")
                    ).strip()
                except Exception as exc:
                    issues.append(f"fastresume_read_error:{exc}")

            metadata: Optional[Dict[str, Any]] = None
            if torrent_path.exists():
                try:
                    metadata = load_torrent_metadata(torrent_path)
                except Exception as exc:
                    issues.append(f"torrent_metadata_error:{exc}")

            if info is not None and old_save_path and normalize_save_path(old_save_path) != normalize_save_path(info.save_path):
                issues.append("save_path_mismatch_api_fastresume")
            if not old_save_path and info is not None:
                old_save_path = str(info.save_path or "").strip()
            if not old_qbt_save_path:
                old_qbt_save_path = old_save_path

            new_save_path = ""
            content_path = str(getattr(info, "content_path", "") or "").strip() if info else ""
            expected_root_name = ""
            is_multi_file = False
            path_shape_match = False
            dest_content_path = ""
            if metadata is not None:
                expected_root_name = str(metadata["root_name"])
                is_multi_file = bool(metadata["is_multi_file"])
                if old_save_path:
                    try:
                        new_save_path = replace_root(old_save_path, source_root_n, dest_root_n)
                        expected_old_content = expected_content_path(old_save_path, metadata)
                        if not content_path:
                            content_path = expected_old_content
                        path_shape_match = (
                            normalize_save_path(content_path)
                            == normalize_save_path(expected_old_content)
                        )
                        dest_content_path = expected_content_path(new_save_path, metadata)
                    except Exception as exc:
                        issues.append(str(exc))
                else:
                    issues.append("missing_old_save_path")

            dest_path_obj = Path(dest_content_path) if dest_content_path else Path("/")
            row = {
                "hash": torrent_hash,
                "name": getattr(info, "name", "") if info else "",
                "state": getattr(info, "state", "") if info else "",
                "progress": float(getattr(info, "progress", 0.0) or 0.0) if info else 0.0,
                "selected": True,
                "fastresume_path": str(fastresume_path),
                "torrent_path": str(torrent_path),
                "old_save_path": old_save_path,
                "old_qbt_save_path": old_qbt_save_path,
                "old_qbt_download_path": old_qbt_download_path,
                "content_path": content_path,
                "source_root": source_root_n,
                "dest_root": dest_root_n,
                "new_save_path": new_save_path,
                "dest_content_path": dest_content_path,
                "dest_exists": bool(dest_content_path and dest_path_obj.exists()),
                "dest_kind": path_kind(dest_path_obj) if dest_content_path else "missing",
                "is_multi_file": is_multi_file,
                "expected_root_name": expected_root_name,
                "path_shape_match": bool(path_shape_match),
                "verified": False,
                "actionable": False,
                "copy_status": "pending",
                "verify_status": "pending",
                "verify_report_path": "",
                "verify_classification": "",
                "source_recheck_status": "pending",
                "source_recheck_before_state": "",
                "source_recheck_before_progress": 0.0,
                "source_recheck_after_state": "",
                "source_recheck_after_progress": 0.0,
                "source_recheck_elapsed_seconds": 0.0,
                "patch_status": "pending",
                "resume_status": "pending",
                "cleanup_status": "pending",
                "cleanup_ready": False,
                "cleanup_issues": [],
                "cleanup_staged_path": "",
                "plan_issues": sorted(dedupe_preserve(issues)),
                "issues": sorted(dedupe_preserve(issues)),
            }
            rows.append(row)

        manifest = {
            "tool": SCRIPT_NAME,
            "version": SCRIPT_VERSION,
            "generated_at": ts_iso(),
            "updated_at": ts_iso(),
            "source_root": source_root_n,
            "dest_root": dest_root_n,
            "fastresume_dir": str(fastresume_dir),
            "torrent_dir": str(torrent_dir),
            "selection": selection,
            "global_issues": [],
            "phase_history": [],
            "rows": rows,
        }
        report_path = manifest_report_path(manifest_path, "plan")
        write_json(report_path, {"phase": "plan", "rows": rows, "generated_at": ts_iso()})
        self._save_manifest(manifest_path, manifest, phase="plan", mode="apply", report_path=report_path)
        emit_summary(
            {
                "selection_mode": selection["mode"],
                "selected": len(selected_hashes),
                "rows": len(rows),
                "ready": sum(1 for row in rows if not row["issues"]),
                "issues": sum(1 for row in rows if row["issues"]),
            }
        )
        return 0

    def migrate(
        self,
        *,
        manifest_path: Path,
        hashes: Sequence[str],
        source_root: str,
        dest_root: str,
        batch_size: int,
        fastresume_dir: Path,
        torrent_dir: Path,
        export_torrents_dir: Optional[Path],
        apply: bool,
        timeout_seconds: float,
        quick_only: bool,
        recheck_source_on_verify_fail: bool = False,
        recheck_timeout_seconds: float = 1800.0,
        allow_partials: bool,
        journal_path: Path,
        auto_stop_qb: bool,
        auto_cleanup_mode: str,
        cleanup_journal_path: Optional[Path],
        pilot_size: int,
        observe_seconds: float,
        resume_remaining: bool,
        recheck_on_failure: bool,
        cleanup_pilot_size: int,
        cleanup_batch_size: int,
        cleanup_observe_seconds: float,
        cleanup_min_depth: int,
    ) -> int:
        cleanup_mode = normalize_cleanup_mode(auto_cleanup_mode)
        if apply and auto_stop_qb:
            self._ensure_qb_online_for_orchestration(timeout_seconds=timeout_seconds)
        phases = [
            (
                "plan",
                lambda: self.plan(
                    manifest_path=manifest_path,
                    hashes=hashes,
                    source_root=source_root,
                    dest_root=dest_root,
                    batch_size=batch_size,
                    fastresume_dir=fastresume_dir,
                    torrent_dir=torrent_dir,
                    export_torrents_dir=export_torrents_dir,
                ),
            ),
            ("copy", lambda: self.copy(manifest_path=manifest_path, apply=apply)),
            (
                "verify",
                lambda: self.verify(
                    manifest_path=manifest_path,
                    timeout_seconds=timeout_seconds,
                    quick_only=quick_only,
                    recheck_source_on_fail=recheck_source_on_verify_fail,
                    recheck_timeout_seconds=recheck_timeout_seconds,
                ),
            ),
            (
                "validate",
                lambda: self.validate(
                    manifest_path=manifest_path,
                    allow_partials=allow_partials,
                    for_patch=True,
                    journal_path=journal_path,
                    require_stopped_qb=bool(apply),
                    require_torrents_stopped=bool(apply),
                ),
            ),
            (
                "patch",
                lambda: self.patch(
                    manifest_path=manifest_path,
                    journal_path=journal_path,
                    apply=apply,
                    auto_stop_qb=auto_stop_qb,
                ),
            ),
            (
                "resume",
                lambda: self.resume(
                    manifest_path=manifest_path,
                    apply=apply,
                    pilot_size=pilot_size,
                    observe_seconds=observe_seconds,
                    resume_remaining=resume_remaining,
                    recheck_on_failure=recheck_on_failure,
                ),
            ),
        ]
        for phase, run_phase in phases:
            emit_log("phase_start", phase=phase, mode="apply" if apply else "dryrun")
            code = int(run_phase() or 0)
            emit_log("phase_end", phase=phase, code=code)
            if code != 0:
                return code
            if apply and auto_stop_qb and phase == "verify":
                controller = self._ensure_controller()
                if not controller.is_stopped():
                    emit_log("qb_stop", phase="validate", reason="prepare_for_patch")
                    controller.stop()
            if not apply and phase == "copy":
                rows = self._selected_rows(manifest_path)
                if not rows:
                    raise RelocationError("no_selected_rows_after_copy")
                if not all(bool(row.get("dest_exists")) for row in rows):
                    missing = sum(1 for row in rows if not bool(row.get("dest_exists")))
                    for skipped in ("verify", "validate", "patch", "resume"):
                        emit_log(
                            "phase_skip",
                            phase=skipped,
                            reason="dryrun_destination_payload_missing",
                            missing=missing,
                        )
                    return 0
        if cleanup_mode == "safe":
            if not apply:
                emit_log("phase_skip", phase="cleanup", reason="auto_cleanup_apply_only")
                return 0
            emit_log("phase_start", phase="cleanup", mode="apply")
            code = int(
                self.cleanup(
                    manifest_path=manifest_path,
                    apply=True,
                    confirm_cleanup=True,
                    journal_path=cleanup_journal_path,
                    cleanup_pilot_size=cleanup_pilot_size,
                    cleanup_batch_size=cleanup_batch_size,
                    cleanup_observe_seconds=cleanup_observe_seconds,
                    cleanup_min_depth=cleanup_min_depth,
                )
                or 0
            )
            emit_log("phase_end", phase="cleanup", code=code)
            if code != 0:
                return code
        return 0

    def copy(self, *, manifest_path: Path, apply: bool) -> int:
        manifest = self._load_manifest(manifest_path)
        rows = row_selection(manifest["rows"])
        if apply:
            self._pause_selected(rows)
            self._refresh_rows_from_qb(rows)
        results: List[Dict[str, Any]] = []
        processed_seconds = 0.0
        total_rows = len(rows)
        for index, row in enumerate(rows, start=1):
            started_at = time.monotonic()
            source_path = Path(str(row.get("content_path") or ""))
            dest_parent = Path(str(row.get("new_save_path") or ""))
            dest_content = Path(str(row.get("dest_content_path") or ""))
            emit_log(
                "item_start",
                phase="copy",
                index=index,
                total=total_rows,
                hash=row["hash"],
                name=row.get("name", ""),
                source=source_path,
                dest=dest_parent,
                mode="apply" if apply else "dryrun",
            )
            proc: Optional[subprocess.CompletedProcess[str]] = None
            if not source_path.exists():
                if dest_content.exists():
                    # Idempotent/stale-root remediation path: reuse the verified destination.
                    row["copy_status"] = "reused_existing_dest"
                else:
                    row["copy_status"] = "source_missing"
                    add_issue(row, "source_payload_missing")
            elif not row.get("new_save_path"):
                row["copy_status"] = "missing_target"
                add_issue(row, "new_save_path_missing")
            else:
                cmd = [
                    "rsync",
                    "-aHAX",
                    "--numeric-ids",
                    "--itemize-changes",
                ]
                if apply:
                    cmd.extend(["--human-readable", "--info=progress2"])
                else:
                    cmd.append("--dry-run")
                cmd.extend([str(source_path), str(dest_parent)])
                if apply:
                    dest_parent.mkdir(parents=True, exist_ok=True)
                proc = self.runner.run(cmd, capture_output=not apply)
                row["copy_status"] = "copied" if apply and proc.returncode == 0 else "dryrun"
                if proc.returncode != 0:
                    row["copy_status"] = "copy_failed"
                    add_issue(row, "copy_failed")
                results.append(
                    {
                        "hash": row["hash"],
                        "status": row["copy_status"],
                        "rc": int(proc.returncode),
                        "cmd": cmd,
                    }
                )
            row["dest_exists"] = bool(dest_content and dest_content.exists())
            row["dest_kind"] = path_kind(dest_content) if str(row.get("dest_content_path") or "") else "missing"
            if proc is None:
                results.append({"hash": row["hash"], "status": row["copy_status"]})
            elapsed_seconds = max(0.0, time.monotonic() - started_at)
            remaining_items = total_rows - index
            eta_seconds = estimate_remaining_seconds(
                completed_items=index - 1,
                completed_seconds=processed_seconds,
                current_elapsed_seconds=elapsed_seconds,
                remaining_items=remaining_items,
            )
            processed_seconds += elapsed_seconds
            emit_log(
                "item_end",
                phase="copy",
                index=index,
                total=total_rows,
                hash=row["hash"],
                status=row.get("copy_status", ""),
                elapsed=format_hms(elapsed_seconds),
                eta=format_hms(eta_seconds),
                remaining=remaining_items,
            )
        report_path = manifest_report_path(manifest_path, "copy")
        write_json(report_path, {"phase": "copy", "apply": bool(apply), "results": results, "generated_at": ts_iso()})
        self._save_manifest(
            manifest_path,
            manifest,
            phase="copy",
            mode="apply" if apply else "dryrun",
            report_path=report_path,
        )
        emit_summary(
            {
                "copied": sum(1 for row in rows if row.get("copy_status") == "copied"),
                "dryrun": sum(1 for row in rows if row.get("copy_status") == "dryrun"),
                "reused_existing_dest": sum(
                    1 for row in rows if row.get("copy_status") == "reused_existing_dest"
                ),
                "copy_failed": sum(1 for row in rows if row.get("copy_status") == "copy_failed"),
                "rows": len(rows),
            }
        )
        return 0 if all(row.get("copy_status") != "copy_failed" for row in rows) else 1

    def verify(
        self,
        *,
        manifest_path: Path,
        timeout_seconds: float,
        quick_only: bool,
        recheck_source_on_fail: bool = False,
        recheck_timeout_seconds: float = 1800.0,
    ) -> int:
        manifest = self._load_manifest(manifest_path)
        rows = row_selection(manifest["rows"])
        verify_dir = manifest_report_path(manifest_path, "verify", suffix="")
        results: List[Dict[str, Any]] = []
        processed_seconds = 0.0
        total_rows = len(rows)
        for index, row in enumerate(rows, start=1):
            started_at = time.monotonic()
            torrent_path = Path(str(row.get("torrent_path") or ""))
            dest_content = Path(str(row.get("dest_content_path") or ""))
            emit_log(
                "item_start",
                phase="verify",
                index=index,
                total=total_rows,
                hash=row["hash"],
                name=row.get("name", ""),
                target=dest_content,
            )
            if not torrent_path.exists():
                row["verify_status"] = "torrent_missing"
                row["verified"] = False
                add_issue(row, "torrent_metadata_missing")
                results.append({"hash": row["hash"], "status": row["verify_status"]})
            elif not dest_content.exists():
                row["verify_status"] = "dest_missing"
                row["verified"] = False
                add_issue(row, "destination_payload_missing")
                results.append({"hash": row["hash"], "status": row["verify_status"]})
            else:
                report_path = verify_dir / f"{row['hash']}.json"
                payload = self.verifier.verify(
                    torrent_path,
                    dest_content,
                    report_path,
                    timeout_seconds=timeout_seconds,
                    quick_only=quick_only,
                    show_progress=True,
                )
                summary = dict(payload.get("summary") or {})
                verified = int(summary.get("verified", 0) or 0) > 0 and str(
                    summary.get("best_path") or ""
                ) == str(dest_content)
                row["verified"] = verified
                row["verify_status"] = "verified" if verified else "verify_failed"
                row["verify_report_path"] = str(report_path)
                row["verify_classification"] = str(summary.get("best_classification") or "")
                if verified:
                    remove_issue(row, "offline_verify_failed")
                    row["source_recheck_status"] = "not_needed"
                else:
                    add_issue(row, "offline_verify_failed")
                    if recheck_source_on_fail:
                        snapshot = self._recheck_source_after_verify_failure(
                            row,
                            timeout_seconds=recheck_timeout_seconds,
                        )
                        row["source_recheck_status"] = str(snapshot.get("status") or "pending")
                        row["source_recheck_before_state"] = str(snapshot.get("before_state") or "")
                        row["source_recheck_before_progress"] = float(snapshot.get("before_progress", 0.0) or 0.0)
                        row["source_recheck_after_state"] = str(snapshot.get("after_state") or "")
                        row["source_recheck_after_progress"] = float(snapshot.get("after_progress", 0.0) or 0.0)
                        row["source_recheck_elapsed_seconds"] = float(snapshot.get("elapsed_seconds", 0.0) or 0.0)
                results.append(
                    {
                        "hash": row["hash"],
                        "status": row["verify_status"],
                        "classification": row.get("verify_classification"),
                        "report_path": str(report_path),
                        "source_recheck_status": row.get("source_recheck_status"),
                        "source_recheck_after_state": row.get("source_recheck_after_state"),
                        "source_recheck_after_progress": row.get("source_recheck_after_progress"),
                    }
                )
            elapsed_seconds = max(0.0, time.monotonic() - started_at)
            remaining_items = total_rows - index
            eta_seconds = estimate_remaining_seconds(
                completed_items=index - 1,
                completed_seconds=processed_seconds,
                current_elapsed_seconds=elapsed_seconds,
                remaining_items=remaining_items,
            )
            processed_seconds += elapsed_seconds
            emit_log(
                "item_end",
                phase="verify",
                index=index,
                total=total_rows,
                hash=row["hash"],
                status=row.get("verify_status", ""),
                elapsed=format_hms(elapsed_seconds),
                eta=format_hms(eta_seconds),
                remaining=remaining_items,
                classification=row.get("verify_classification", ""),
            )
        report_path = manifest_report_path(manifest_path, "verify")
        write_json(report_path, {"phase": "verify", "results": results, "generated_at": ts_iso()})
        self._save_manifest(
            manifest_path,
            manifest,
            phase="verify",
            mode="apply",
            report_path=report_path,
        )
        emit_summary(
            {
                "verified": sum(1 for row in rows if row.get("verified")),
                "failed": sum(1 for row in rows if row.get("verify_status") == "verify_failed"),
                "rows": len(rows),
            }
        )
        return 0 if all(row.get("verified") for row in rows if row.get("dest_exists")) else 1

    def validate(
        self,
        *,
        manifest_path: Path,
        allow_partials: bool,
        for_patch: bool,
        journal_path: Optional[Path],
        require_stopped_qb: bool = True,
        require_torrents_stopped: bool = True,
    ) -> int:
        manifest = self._load_manifest(manifest_path)
        rows = row_selection(manifest["rows"])
        hashes = [str(row.get("hash") or "") for row in rows]
        duplicates = len(hashes) != len(set(hashes))
        global_issues: List[str] = []
        controller_stopped = False
        if duplicates:
            global_issues.append("duplicate_hashes_in_manifest")
        if for_patch:
            journal_target = journal_path or manifest_report_path(manifest_path, "patch-journal", ".jsonl")
            if not journal_target.parent.exists():
                global_issues.append("journal_parent_missing")
            if require_stopped_qb:
                controller = self._ensure_controller()
                controller_stopped = bool(controller.is_stopped())
                if not controller_stopped:
                    global_issues.append("qbittorrent_must_be_stopped_before_patch")
        for row in rows:
            issues = list(row.get("plan_issues") or [])
            torrent_path = Path(str(row.get("torrent_path") or ""))
            fastresume_path = Path(str(row.get("fastresume_path") or ""))
            dest_content = Path(str(row.get("dest_content_path") or ""))
            source_content = Path(str(row.get("content_path") or ""))
            new_save_path = str(row.get("new_save_path") or "")
            old_save_path = str(row.get("old_save_path") or "")
            if not torrent_path.exists():
                issues.append("torrent_metadata_missing")
            if not fastresume_path.exists():
                issues.append("fastresume_missing")
            if not dest_content.exists():
                issues.append("destination_payload_missing")
            if not new_save_path:
                issues.append("new_save_path_missing")
            else:
                try:
                    normalize_save_path(new_save_path)
                except Exception:
                    issues.append("destination_path_not_absolute")
            if old_save_path and new_save_path and normalize_save_path(old_save_path) == normalize_save_path(new_save_path):
                same_content_path = False
                try:
                    same_content_path = source_content == dest_content
                except Exception:
                    same_content_path = False
                if same_content_path:
                    issues.append("source_and_destination_paths_identical")
            if not bool(row.get("path_shape_match")):
                issues.append("path_shape_mismatch")
            if not bool(row.get("verified")):
                issues.append("offline_verify_failed")
            info = None if controller_stopped else self.qb_client.get_torrent_info(row["hash"])
            if info is not None:
                row["state"] = str(info.state or "")
                row["progress"] = float(info.progress or 0.0)
                if require_torrents_stopped and not is_stopped_state(info.state):
                    issues.append("torrent_not_stopped")
                if (
                    not allow_partials
                    and float(info.progress or 0.0) < 1.0
                    and not should_trust_offline_verify_over_qb_progress(row)
                ):
                    issues.append("torrent_not_complete")
            elif controller_stopped:
                cached_state = str(row.get("state") or "")
                cached_progress = float(row.get("progress", 0.0) or 0.0)
                if not cached_state:
                    issues.append("qb_state_unavailable_while_stopped")
                else:
                    if require_torrents_stopped and not is_stopped_state(cached_state):
                        issues.append("torrent_not_stopped")
                    if (
                        not allow_partials
                        and cached_progress < 1.0
                        and not should_trust_offline_verify_over_qb_progress(row)
                    ):
                        issues.append("torrent_not_complete")
            else:
                issues.append("qb_torrent_not_found")
            set_row_issues(row, issues)
            row["actionable"] = not bool(global_issues) and not bool(row["issues"])
        manifest["global_issues"] = sorted(dedupe_preserve(global_issues))
        report_path = manifest_report_path(manifest_path, "validate")
        write_json(
            report_path,
            {
                "phase": "validate",
                "generated_at": ts_iso(),
                "global_issues": manifest["global_issues"],
                "actionable": [row["hash"] for row in rows if row.get("actionable")],
            },
        )
        self._save_manifest(
            manifest_path,
            manifest,
            phase="validate",
            mode="apply",
            report_path=report_path,
        )
        emit_summary(
            {
                "actionable": sum(1 for row in rows if row.get("actionable")),
                "global_issues": len(manifest["global_issues"]),
                "rows": len(rows),
                "with_issues": sum(1 for row in rows if row.get("issues")),
            }
        )
        return 0 if not manifest["global_issues"] and any(row.get("actionable") for row in rows) else 1

    def patch(
        self,
        *,
        manifest_path: Path,
        journal_path: Path,
        apply: bool,
        auto_stop_qb: bool,
    ) -> int:
        manifest = self._load_manifest(manifest_path)
        rows = [row for row in row_selection(manifest["rows"]) if row.get("actionable")]
        if not rows:
            raise RelocationError("no_actionable_rows_for_patch")
        if apply:
            controller = self._ensure_controller()
            if auto_stop_qb and not controller.is_stopped():
                controller.stop()
            if not controller.is_stopped():
                raise RelocationError("qbittorrent_must_be_stopped_before_patch")
        backup_suffix = f".qb-zfs-relocate-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
        entries: List[Dict[str, Any]] = []
        for row in rows:
            fastresume_path = Path(row["fastresume_path"])
            if not apply:
                row["patch_status"] = "dryrun"
                entries.append(
                    {
                        "timestamp": ts_iso(),
                        "hash": row["hash"],
                        "name": row.get("name", ""),
                        "fastresume_path": str(fastresume_path),
                        "backup_path": str(fastresume_path.with_name(fastresume_path.name + backup_suffix)),
                        "old_save_path": row.get("old_save_path", ""),
                        "old_qBt-savePath": row.get("old_qbt_save_path", ""),
                        "old_qBt-downloadPath": row.get("old_qbt_download_path", ""),
                        "new_save_path": row.get("new_save_path", ""),
                        "patch_result": "dryrun",
                    }
                )
                continue
            result = patch_fastresume_file(fastresume_path, row["new_save_path"], backup_suffix)
            row["patch_status"] = "patched" if result.changed else "no_change"
            entries.append(
                {
                    "timestamp": ts_iso(),
                    "hash": row["hash"],
                    "name": row.get("name", ""),
                    "fastresume_path": result.fastresume_path,
                    "backup_path": result.backup_path,
                    "old_save_path": result.old_save_path,
                    "old_qBt-savePath": result.old_qbt_save_path,
                    "old_qBt-downloadPath": result.old_qbt_download_path,
                    "new_save_path": result.new_save_path,
                    "patch_result": row["patch_status"],
                }
            )
        if apply:
            for entry in entries:
                append_jsonl(journal_path, entry)
        report_path = manifest_report_path(manifest_path, "patch")
        write_json(report_path, {"phase": "patch", "apply": bool(apply), "results": entries, "generated_at": ts_iso()})
        self._save_manifest(
            manifest_path,
            manifest,
            phase="patch",
            mode="apply" if apply else "dryrun",
            report_path=report_path,
        )
        emit_summary(
            {
                "dryrun": sum(1 for row in rows if row.get("patch_status") == "dryrun"),
                "no_change": sum(1 for row in rows if row.get("patch_status") == "no_change"),
                "patched": sum(1 for row in rows if row.get("patch_status") == "patched"),
                "rows": len(rows),
            }
        )
        return 0

    def _observe_batch(
        self,
        rows: Sequence[Dict[str, Any]],
        *,
        batch_name: str,
        observe_seconds: float,
        recheck_on_failure: bool,
    ) -> None:
        observe_seconds = max(0.0, float(observe_seconds))
        deadline = time.time() + observe_seconds
        problems: List[str] = []
        first_pass = True
        started_at = time.monotonic()
        last_emit_at = 0.0
        while first_pass or time.time() < deadline:
            first_pass = False
            problems = []
            for row in rows:
                info = self.qb_client.get_torrent_info(row["hash"])
                if info is None:
                    problems.append(f"missing_info:{row['hash']}")
                    continue
                if normalize_save_path(info.save_path) != normalize_save_path(row["new_save_path"]):
                    problems.append(f"save_path_mismatch:{row['hash']}")
                    continue
                state = str(info.state or "").lower()
                if state in BAD_RESUME_STATES:
                    problems.append(f"bad_state:{row['hash']}:{state}")
            remaining_seconds = max(0.0, deadline - time.time())
            if not problems and remaining_seconds <= 0.0:
                emit_log(
                    "observe_end",
                    phase="resume",
                    batch=batch_name,
                    rows=len(rows),
                    elapsed=format_hms(time.monotonic() - started_at),
                    status="ok",
                )
                return
            now = time.monotonic()
            if last_emit_at <= 0.0 or now - last_emit_at >= 5.0:
                emit_log(
                    "observe_progress",
                    phase="resume",
                    batch=batch_name,
                    rows=len(rows),
                    elapsed=format_hms(now - started_at),
                    eta=format_hms(remaining_seconds),
                    problems=len(problems),
                )
                last_emit_at = now
            self.sleep_fn(1.0)
        if recheck_on_failure:
            for row in rows:
                info = self.qb_client.get_torrent_info(row["hash"])
                state = str(getattr(info, "state", "") or "").lower()
                if state in BAD_RESUME_STATES:
                    self.qb_client.recheck_torrent(row["hash"])
        if not problems:
            emit_log(
                "observe_end",
                phase="resume",
                batch=batch_name,
                rows=len(rows),
                elapsed=format_hms(time.monotonic() - started_at),
                status="ok",
            )
            return
        emit_log(
            "observe_end",
            phase="resume",
            batch=batch_name,
            rows=len(rows),
            elapsed=format_hms(time.monotonic() - started_at),
            status="failed",
            problems=len(problems),
        )
        raise RelocationError(",".join(problems) if problems else "pilot_observation_failed")

    def resume(
        self,
        *,
        manifest_path: Path,
        apply: bool,
        pilot_size: int,
        observe_seconds: float,
        resume_remaining: bool,
        recheck_on_failure: bool,
    ) -> int:
        manifest = self._load_manifest(manifest_path)
        allowed_patch_statuses = {"patched", "no_change"}
        if not apply:
            allowed_patch_statuses.add("dryrun")
        rows = [
            row
            for row in row_selection(manifest["rows"])
            if row.get("actionable") and row.get("patch_status") in allowed_patch_statuses
        ]
        if not rows:
            raise RelocationError("no_patch_ready_rows_for_resume")
        if apply:
            controller = self._ensure_controller()
            if controller.is_stopped():
                controller.start()
            self._wait_for_qb_online()
        eligible: List[Dict[str, Any]] = []
        for row in rows:
            info = self.qb_client.get_torrent_info(row["hash"])
            if info is None:
                row["resume_status"] = "missing_info"
                continue
            if not apply and row.get("patch_status") == "dryrun":
                eligible.append(row)
                continue
            if normalize_save_path(info.save_path) != normalize_save_path(row["new_save_path"]):
                row["resume_status"] = "save_path_mismatch"
                add_issue(row, "post_patch_save_path_mismatch")
                continue
            eligible.append(row)
        if not eligible:
            raise RelocationError("no_resume_eligible_rows")
        pilot = eligible[: max(1, int(pilot_size))]
        remaining = eligible[len(pilot) :]
        if not apply:
            for row in pilot:
                row["resume_status"] = "pilot_dryrun"
            for row in remaining:
                row["resume_status"] = "remaining_dryrun" if resume_remaining else "waiting_for_pilot"
        else:
            if not self.qb_client.resume_torrents([row["hash"] for row in pilot]):
                raise RelocationError("resume_pilot_failed")
            for row in pilot:
                row["resume_status"] = "pilot_resumed"
            self._observe_batch(
                pilot,
                batch_name="pilot",
                observe_seconds=observe_seconds,
                recheck_on_failure=recheck_on_failure,
            )
            for row in pilot:
                row["resume_status"] = "pilot_ok"
            if resume_remaining and remaining:
                if not self.qb_client.resume_torrents([row["hash"] for row in remaining]):
                    raise RelocationError("resume_remaining_failed")
                self._observe_batch(
                    remaining,
                    batch_name="remaining",
                    observe_seconds=observe_seconds,
                    recheck_on_failure=recheck_on_failure,
                )
                for row in remaining:
                    row["resume_status"] = "resumed_ok"
                    row["cleanup_ready"] = True
            for row in pilot:
                row["cleanup_ready"] = bool(resume_remaining or not remaining)
            if not resume_remaining:
                for row in remaining:
                    row["resume_status"] = "waiting_for_pilot"
        report_path = manifest_report_path(manifest_path, "resume")
        write_json(
            report_path,
            {
                "phase": "resume",
                "apply": bool(apply),
                "pilot": [row["hash"] for row in pilot],
                "remaining": [row["hash"] for row in remaining],
                "generated_at": ts_iso(),
            },
        )
        self._save_manifest(
            manifest_path,
            manifest,
            phase="resume",
            mode="apply" if apply else "dryrun",
            report_path=report_path,
        )
        emit_summary(
            {
                "pilot": len(pilot),
                "remaining": len(remaining),
                "resume_ok": sum(
                    1 for row in eligible if row.get("resume_status") in {"pilot_ok", "resumed_ok"}
                ),
                "waiting_for_pilot": sum(
                    1 for row in eligible if row.get("resume_status") == "waiting_for_pilot"
                ),
            }
        )
        return 0

    def cleanup(
        self,
        *,
        manifest_path: Path,
        apply: bool,
        confirm_cleanup: bool,
        journal_path: Optional[Path] = None,
        cleanup_pilot_size: int = DEFAULT_CLEANUP_PILOT_SIZE,
        cleanup_batch_size: int = 0,
        cleanup_observe_seconds: float = DEFAULT_CLEANUP_OBSERVE_SECONDS,
        cleanup_min_depth: int = 1,
    ) -> int:
        manifest = self._load_manifest(manifest_path)
        requested_batch_size = normalize_batch_size(cleanup_batch_size)
        requested_pilot_size = max(1, int(cleanup_pilot_size or DEFAULT_CLEANUP_PILOT_SIZE))
        requested_min_depth = max(1, int(cleanup_min_depth or 1))
        rows = [
            row
            for row in row_selection(manifest["rows"])
            if row.get("cleanup_ready") and row.get("cleanup_status") not in FINAL_CLEANUP_STATES
        ]
        if requested_batch_size:
            rows = rows[:requested_batch_size]
        if not rows:
            report_path = manifest_report_path(manifest_path, "cleanup")
            journal_target = self._cleanup_journal_path(manifest_path, journal_path)
            write_json(
                report_path,
                {
                    "phase": "cleanup",
                    "apply": bool(apply),
                    "journal_path": str(journal_target),
                    "pilot": [],
                    "remaining": [],
                    "results": [],
                    "generated_at": ts_iso(),
                },
            )
            self._save_manifest(
                manifest_path,
                manifest,
                phase="cleanup",
                mode="apply" if apply else "dryrun",
                report_path=report_path,
            )
            emit_summary(
                {
                    "blocked": 0,
                    "cleaned": 0,
                    "dryrun": 0,
                    "pilot": 0,
                    "remaining": 0,
                    "restored": 0,
                    "rows": 0,
                    "source_missing": 0,
                    "staged_dryrun": 0,
                }
            )
            return 0
        if apply and not confirm_cleanup:
            raise RelocationError("cleanup_requires_confirm_cleanup")
        if not self.qb_client.test_connection():
            raise RelocationError("qbittorrent_must_be_online_for_cleanup")
        journal_target = self._cleanup_journal_path(manifest_path, journal_path)
        prepared: List[Dict[str, Any]] = []
        for row in rows:
            issues: List[str] = []
            row["cleanup_issues"] = []
            source_path = Path(str(row.get("content_path") or ""))
            stage_path = self._cleanup_stage_path(manifest_path, row)
            source_root = str(row.get("source_root") or "")
            source_root_norm = ""
            source_norm = ""
            stage_norm = ""
            try:
                source_root_norm = normalize_save_path(source_root)
            except Exception:
                issues.append("cleanup_source_root_invalid")
            if not source_path.is_absolute():
                issues.append("cleanup_source_path_not_absolute")
            else:
                try:
                    source_norm = normalize_save_path(str(source_path))
                except Exception:
                    issues.append("cleanup_source_path_invalid")
            try:
                stage_norm = normalize_save_path(str(stage_path))
            except Exception:
                issues.append("cleanup_stage_path_invalid")
            if source_norm and source_root_norm:
                if not path_is_same_or_child(source_norm, source_root_norm):
                    issues.append("cleanup_path_outside_source_root")
                elif source_norm == source_root_norm:
                    issues.append("cleanup_path_is_source_root")
                elif path_depth_under_root(source_norm, source_root_norm) < requested_min_depth:
                    issues.append("cleanup_path_depth_below_minimum")
            if source_norm and stage_norm and paths_overlap(source_norm, stage_norm):
                issues.append("cleanup_source_stage_overlap")
            verified_ok, verify_summary, verify_issue = self._load_cleanup_verify_summary(row)
            if not verified_ok:
                issues.append(verify_issue)
            source_exists = source_path.exists()
            stage_exists = stage_path.exists()
            if source_exists and stage_exists:
                issues.append("cleanup_source_and_stage_both_exist")
            set_row_issues(row, row.get("issues") or [])
            row["cleanup_issues"] = sorted(dedupe_preserve(issues))
            prepared.append(
                {
                    "row": row,
                    "source_path": source_path,
                    "stage_path": stage_path,
                    "source_norm": source_norm,
                    "stage_norm": stage_norm,
                    "verify_summary": verify_summary,
                }
            )
        for index, item in enumerate(prepared):
            row = item["row"]
            for other in prepared[index + 1 :]:
                other_row = other["row"]
                source_norm = str(item.get("source_norm") or "")
                other_source_norm = str(other.get("source_norm") or "")
                stage_norm = str(item.get("stage_norm") or "")
                other_stage_norm = str(other.get("stage_norm") or "")
                if source_norm and other_source_norm and paths_overlap(source_norm, other_source_norm):
                    row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(row.get("cleanup_issues") or []) + ["cleanup_source_path_overlap"])
                    )
                    other_row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(other_row.get("cleanup_issues") or []) + ["cleanup_source_path_overlap"])
                    )
                if stage_norm and other_stage_norm and paths_overlap(stage_norm, other_stage_norm):
                    row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(row.get("cleanup_issues") or []) + ["cleanup_stage_path_overlap"])
                    )
                    other_row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(other_row.get("cleanup_issues") or []) + ["cleanup_stage_path_overlap"])
                    )
                if source_norm and other_stage_norm and paths_overlap(source_norm, other_stage_norm):
                    row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(row.get("cleanup_issues") or []) + ["cleanup_stage_source_overlap"])
                    )
                    other_row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(other_row.get("cleanup_issues") or []) + ["cleanup_stage_source_overlap"])
                    )
                if other_source_norm and stage_norm and paths_overlap(other_source_norm, stage_norm):
                    row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(row.get("cleanup_issues") or []) + ["cleanup_stage_source_overlap"])
                    )
                    other_row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(other_row.get("cleanup_issues") or []) + ["cleanup_stage_source_overlap"])
                    )
        actionable = [item for item in prepared if not item["row"].get("cleanup_issues")]
        pilot = actionable[:requested_pilot_size]
        remaining = actionable[len(pilot) :]
        results: List[Dict[str, Any]] = []
        failed = False
        processed_hashes = set()
        total_rows = len(prepared)

        def finish_item(
            row: Dict[str, Any],
            *,
            index: int,
            batch_name: str,
            source_path: Path,
            stage_path: Path,
            details: str = "",
        ) -> None:
            processed_hashes.add(str(row.get("hash") or ""))
            emit_log(
                "item_end",
                phase="cleanup",
                batch=batch_name,
                index=index,
                total=total_rows,
                hash=row["hash"],
                status=row.get("cleanup_status", ""),
                details=details,
            )
            results.append(
                {
                    "hash": row["hash"],
                    "status": row.get("cleanup_status", ""),
                    "details": details,
                    "source_path": str(source_path),
                    "staged_path": str(stage_path),
                }
            )

        for batch_name, batch_items in (("pilot", pilot), ("remaining", remaining)):
            for item in batch_items:
                row = item["row"]
                source_path = item["source_path"]
                stage_path = item["stage_path"]
                item_index = len(processed_hashes) + 1
                emit_log(
                    "item_start",
                    phase="cleanup",
                    batch=batch_name,
                    index=item_index,
                    total=total_rows,
                    hash=row["hash"],
                    name=row.get("name", ""),
                    source=source_path,
                    staged=stage_path,
                    mode="apply" if apply else "dryrun",
                )
                source_exists = source_path.exists()
                stage_exists = stage_path.exists()
                if not source_exists and not stage_exists:
                    row["cleanup_status"] = "source_missing"
                    row["cleanup_ready"] = False
                    finish_item(
                        row,
                        index=item_index,
                        batch_name=batch_name,
                        source_path=source_path,
                        stage_path=stage_path,
                    )
                    continue
                snapshot = self._cleanup_qb_snapshot(row)
                live_issues = self._cleanup_snapshot_issues(row, snapshot)
                if live_issues:
                    row["cleanup_status"] = "blocked"
                    row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(row.get("cleanup_issues") or []) + live_issues)
                    )
                    self._append_cleanup_journal(
                        journal_target,
                        row=row,
                        action="validate",
                        decision="block",
                        status=row["cleanup_status"],
                        source_path=source_path,
                        staged_path=stage_path,
                        snapshot=snapshot,
                        details=",".join(live_issues),
                    )
                    failed = True
                    finish_item(
                        row,
                        index=item_index,
                        batch_name=batch_name,
                        source_path=source_path,
                        stage_path=stage_path,
                        details=",".join(live_issues),
                    )
                    if apply:
                        self._checkpoint_manifest(manifest_path, manifest)
                        break
                    continue
                if not apply:
                    row["cleanup_status"] = "staged_dryrun" if stage_exists and not source_exists else "dryrun"
                    finish_item(
                        row,
                        index=item_index,
                        batch_name=batch_name,
                        source_path=source_path,
                        stage_path=stage_path,
                    )
                    continue
                if source_exists:
                    stage_path.parent.mkdir(parents=True, exist_ok=True)
                    if stage_path.exists():
                        row["cleanup_status"] = "blocked"
                        row["cleanup_issues"] = sorted(
                            dedupe_preserve(list(row.get("cleanup_issues") or []) + ["cleanup_stage_path_exists"])
                        )
                        self._append_cleanup_journal(
                            journal_target,
                            row=row,
                            action="stage",
                            decision="block",
                            status=row["cleanup_status"],
                            source_path=source_path,
                            staged_path=stage_path,
                            snapshot=snapshot,
                            details="cleanup_stage_path_exists",
                        )
                        failed = True
                        finish_item(
                            row,
                            index=item_index,
                            batch_name=batch_name,
                            source_path=source_path,
                            stage_path=stage_path,
                            details="cleanup_stage_path_exists",
                        )
                        self._checkpoint_manifest(manifest_path, manifest)
                        break
                    emit_log(
                        "cleanup_stage",
                        phase="cleanup",
                        hash=row["hash"],
                        source=source_path,
                        staged=stage_path,
                    )
                    source_path.rename(stage_path)
                    row["cleanup_status"] = "staged"
                    row["cleanup_staged_path"] = str(stage_path)
                    self._append_cleanup_journal(
                        journal_target,
                        row=row,
                        action="stage",
                        decision="rename",
                        status=row["cleanup_status"],
                        source_path=source_path,
                        staged_path=stage_path,
                        snapshot=snapshot,
                    )
                    self._checkpoint_manifest(manifest_path, manifest)
                try:
                    observed_snapshot = self._observe_cleanup_row(
                        row,
                        observe_seconds=cleanup_observe_seconds,
                    )
                    emit_log(
                        "cleanup_observe_end",
                        phase="cleanup",
                        hash=row["hash"],
                        elapsed=format_hms(float(cleanup_observe_seconds)),
                        status="ok",
                    )
                    self._append_cleanup_journal(
                        journal_target,
                        row=row,
                        action="observe",
                        decision="keep_staged",
                        status="ok",
                        source_path=source_path,
                        staged_path=stage_path,
                        snapshot=observed_snapshot,
                    )
                except RelocationError as exc:
                    details = str(exc)
                    restore_status = "restore_skipped"
                    if stage_path.exists() and not source_path.exists():
                        stage_path.rename(source_path)
                        row["cleanup_staged_path"] = ""
                        row["cleanup_status"] = "restored"
                        self._prune_empty_stage_parents(manifest_path, stage_path, str(row.get("source_root") or ""))
                        restore_status = "restored"
                    else:
                        row["cleanup_status"] = "observe_failed"
                    row["cleanup_issues"] = sorted(
                        dedupe_preserve(list(row.get("cleanup_issues") or []) + [details])
                    )
                    self._append_cleanup_journal(
                        journal_target,
                        row=row,
                        action="observe",
                        decision="restore",
                        status=row["cleanup_status"],
                        source_path=source_path,
                        staged_path=stage_path,
                        snapshot=self._cleanup_qb_snapshot(row),
                        details=details,
                    )
                    if restore_status == "restored":
                        self._append_cleanup_journal(
                            journal_target,
                            row=row,
                            action="restore",
                            decision="rename_back",
                            status=restore_status,
                            source_path=source_path,
                            staged_path=stage_path,
                            snapshot=self._cleanup_qb_snapshot(row),
                        )
                    failed = True
                    self._checkpoint_manifest(manifest_path, manifest)
                    finish_item(
                        row,
                        index=item_index,
                        batch_name=batch_name,
                        source_path=source_path,
                        stage_path=stage_path,
                        details=details,
                    )
                    break
                if stage_path.is_dir():
                    shutil.rmtree(stage_path)
                else:
                    stage_path.unlink()
                self._prune_empty_stage_parents(manifest_path, stage_path, str(row.get("source_root") or ""))
                row["cleanup_status"] = "cleaned"
                row["cleanup_ready"] = False
                row["cleanup_staged_path"] = ""
                self._append_cleanup_journal(
                    journal_target,
                    row=row,
                    action="delete",
                    decision="delete_staged",
                    status=row["cleanup_status"],
                    source_path=source_path,
                    staged_path=stage_path,
                    snapshot=self._cleanup_qb_snapshot(row),
                )
                self._checkpoint_manifest(manifest_path, manifest)
                finish_item(
                    row,
                    index=item_index,
                    batch_name=batch_name,
                    source_path=source_path,
                    stage_path=stage_path,
                )
            if failed:
                break
        for item in prepared:
            row = item["row"]
            if str(row.get("hash") or "") in processed_hashes:
                continue
            if row.get("cleanup_issues"):
                row["cleanup_status"] = "blocked"
                failed = True
                results.append(
                    {
                        "hash": row["hash"],
                        "status": row["cleanup_status"],
                        "details": ",".join(row.get("cleanup_issues") or []),
                        "source_path": str(item["source_path"]),
                        "staged_path": str(item["stage_path"]),
                    }
                )
        report_path = manifest_report_path(manifest_path, "cleanup")
        write_json(
            report_path,
            {
                "phase": "cleanup",
                "apply": bool(apply),
                "journal_path": str(journal_target),
                "pilot": [item["row"]["hash"] for item in pilot],
                "remaining": [item["row"]["hash"] for item in remaining],
                "results": results,
                "generated_at": ts_iso(),
            },
        )
        self._save_manifest(
            manifest_path,
            manifest,
            phase="cleanup",
            mode="apply" if apply else "dryrun",
            report_path=report_path,
        )
        emit_summary(
            {
                "cleaned": sum(1 for row in rows if row.get("cleanup_status") == "cleaned"),
                "dryrun": sum(1 for row in rows if row.get("cleanup_status") == "dryrun"),
                "staged_dryrun": sum(1 for row in rows if row.get("cleanup_status") == "staged_dryrun"),
                "blocked": sum(1 for row in rows if row.get("cleanup_status") == "blocked"),
                "restored": sum(1 for row in rows if row.get("cleanup_status") == "restored"),
                "source_missing": sum(1 for row in rows if row.get("cleanup_status") == "source_missing"),
                "pilot": len(pilot),
                "remaining": len(remaining),
                "rows": len(rows),
            }
        )
        return 0 if not failed and all(row.get("cleanup_status") != "blocked" for row in rows) else 1

    def rollback(
        self,
        *,
        manifest_path: Path,
        journal_path: Path,
        apply: bool,
        auto_stop_qb: bool,
    ) -> int:
        manifest = self._load_manifest(manifest_path)
        controller = self._ensure_controller()
        if auto_stop_qb and not controller.is_stopped():
            controller.stop()
        if not controller.is_stopped():
            raise RelocationError("qbittorrent_must_be_stopped_before_rollback")
        restored = 0
        if not journal_path.exists():
            raise RelocationError(f"patch_journal_missing path={journal_path}")
        entries = [
            json.loads(line)
            for line in journal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for entry in entries:
            backup_path = Path(str(entry.get("backup_path") or ""))
            fastresume_path = Path(str(entry.get("fastresume_path") or ""))
            if not backup_path.exists():
                continue
            if apply:
                shutil.copy2(backup_path, fastresume_path)
            restored += 1
        for row in row_selection(manifest["rows"]):
            if row.get("patch_status") in {"patched", "no_change"}:
                row["patch_status"] = "rolled_back" if apply else "rollback_dryrun"
        report_path = manifest_report_path(manifest_path, "rollback")
        write_json(report_path, {"phase": "rollback", "apply": bool(apply), "restored": restored, "generated_at": ts_iso()})
        self._save_manifest(
            manifest_path,
            manifest,
            phase="rollback",
            mode="apply" if apply else "dryrun",
            report_path=report_path,
        )
        emit_summary({"restored": restored, "rows": len(entries)})
        return 0


def add_common_manifest_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-m", "--manifest", required=True, help="Path to relocation manifest JSON")


def add_mutation_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dryrun", action="store_true", help="Preview changes without mutating")
    parser.add_argument("--apply", action="store_true", help="Execute mutations")


def resolve_apply(args: argparse.Namespace) -> bool:
    if bool(args.apply) and bool(args.dryrun):
        raise RelocationError("choose_only_one_of_apply_or_dryrun")
    return bool(args.apply)


def build_process_controller(
    args: argparse.Namespace,
    runner: SubprocessRunner,
) -> Optional[QBProcessController]:
    if getattr(args, "qb_container", None):
        return DockerQbController(str(args.qb_container), runner=runner)
    status_cmd = getattr(args, "qb_status_cmd", "") or ""
    stop_cmd = getattr(args, "qb_stop_cmd", "") or ""
    start_cmd = getattr(args, "qb_start_cmd", "") or ""
    if any([status_cmd, stop_cmd, start_cmd]):
        if not all([status_cmd, stop_cmd, start_cmd]):
            raise RelocationError("qb_status_cmd_qb_stop_cmd_qb_start_cmd_are_all_required")
        return CommandQbController(status_cmd, stop_cmd, start_cmd, runner=runner)
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description="Guarded qBittorrent ZFS dataset relocation workflow",
    )
    subparsers = parser.add_subparsers(dest="phase", required=True)

    p_plan = subparsers.add_parser("plan", help="Build relocation manifest")
    add_common_manifest_argument(p_plan)
    p_plan.add_argument("-s", "--source-root", required=True)
    p_plan.add_argument("-d", "--dest-root", required=True)
    p_plan.add_argument("-n", "--batch-size", type=int, default=0, help="Limit planning to the first N selected torrents")
    p_plan.add_argument("-H", "--hash", action="append", default=[], dest="hashes")
    p_plan.add_argument(
        "-i",
        "--hashes-file",
        default="",
        help="Optional override file containing one hash per line; otherwise qB torrents under --source-root are auto-selected",
    )
    p_plan.add_argument(
        "-f",
        "--fastresume-dir",
        default=str(DEFAULT_FASTRESUME_DIR),
        help="Directory containing qB .fastresume files",
    )
    p_plan.add_argument(
        "-t",
        "--torrent-dir",
        default="",
        help="Directory containing .torrent metadata files (defaults to fastresume dir)",
    )
    p_plan.add_argument(
        "--export-torrents-dir",
        default="",
        help="Fallback export directory for missing .torrent files",
    )

    p_copy = subparsers.add_parser("copy", help="Pause selected torrents and rsync payload data")
    add_common_manifest_argument(p_copy)
    add_mutation_flags(p_copy)

    p_verify = subparsers.add_parser("verify", help="Offline verify destination payloads")
    add_common_manifest_argument(p_verify)
    p_verify.add_argument("--timeout", type=float, default=1800.0)
    p_verify.add_argument("--quick-only", action="store_true")
    p_verify.add_argument("--recheck-source-on-fail", action="store_true")
    p_verify.add_argument("--recheck-timeout", type=float, default=1800.0)

    p_validate = subparsers.add_parser("validate", help="Run validation-only safety checks")
    add_common_manifest_argument(p_validate)
    p_validate.add_argument("--allow-partials", action="store_true")
    p_validate.add_argument("--for-patch", action="store_true")
    p_validate.add_argument("--journal", default="")
    p_validate.add_argument("--qb-container", default="")
    p_validate.add_argument("--qb-status-cmd", default="")
    p_validate.add_argument("--qb-stop-cmd", default="")
    p_validate.add_argument("--qb-start-cmd", default="")

    p_patch = subparsers.add_parser("patch", help="Patch validated fastresume files while qB is stopped")
    add_common_manifest_argument(p_patch)
    add_mutation_flags(p_patch)
    p_patch.add_argument("--journal", default="")
    p_patch.add_argument("--auto-stop-qb", action="store_true")
    p_patch.add_argument("--qb-container", default="")
    p_patch.add_argument("--qb-status-cmd", default="")
    p_patch.add_argument("--qb-stop-cmd", default="")
    p_patch.add_argument("--qb-start-cmd", default="")

    p_resume = subparsers.add_parser("resume", help="Restart qB and resume torrents in controlled batches")
    add_common_manifest_argument(p_resume)
    add_mutation_flags(p_resume)
    p_resume.add_argument("--pilot-size", type=int, default=DEFAULT_PILOT_SIZE)
    p_resume.add_argument("--pilot-observe-seconds", type=float, default=15.0)
    p_resume.add_argument("--resume-remaining", action="store_true")
    p_resume.add_argument("--recheck-on-failure", action="store_true")
    p_resume.add_argument("--qb-container", default="")
    p_resume.add_argument("--qb-status-cmd", default="")
    p_resume.add_argument("--qb-stop-cmd", default="")
    p_resume.add_argument("--qb-start-cmd", default="")

    p_cleanup = subparsers.add_parser("cleanup", help="Safely stage, observe, and remove old source payloads after successful resume")
    add_common_manifest_argument(p_cleanup)
    add_mutation_flags(p_cleanup)
    p_cleanup.add_argument("-y", "--confirm-cleanup", action="store_true")
    p_cleanup.add_argument("--cleanup-journal", default="")
    p_cleanup.add_argument("--cleanup-pilot-size", type=int, default=DEFAULT_CLEANUP_PILOT_SIZE)
    p_cleanup.add_argument("--cleanup-batch-size", type=int, default=0)
    p_cleanup.add_argument("--cleanup-observe-seconds", type=float, default=DEFAULT_CLEANUP_OBSERVE_SECONDS)
    p_cleanup.add_argument("--cleanup-min-depth", type=int, default=1)

    p_rollback = subparsers.add_parser("rollback", help="Restore fastresume backups from the patch journal")
    add_common_manifest_argument(p_rollback)
    add_mutation_flags(p_rollback)
    p_rollback.add_argument("--journal", default="")
    p_rollback.add_argument("--auto-stop-qb", action="store_true")
    p_rollback.add_argument("--qb-container", default="")
    p_rollback.add_argument("--qb-status-cmd", default="")
    p_rollback.add_argument("--qb-stop-cmd", default="")
    p_rollback.add_argument("--qb-start-cmd", default="")

    p_migrate = subparsers.add_parser(
        "migrate",
        help="Run plan, copy, verify, validate, patch, resume, and optional safe cleanup as one guarded batch",
    )
    add_common_manifest_argument(p_migrate)
    add_mutation_flags(p_migrate)
    p_migrate.add_argument("-s", "--source-root", required=True)
    p_migrate.add_argument("-d", "--dest-root", required=True)
    p_migrate.add_argument("-n", "--batch-size", type=int, default=0, help="Limit migration to the first N selected torrents")
    p_migrate.add_argument("-H", "--hash", action="append", default=[], dest="hashes")
    p_migrate.add_argument(
        "-i",
        "--hashes-file",
        default="",
        help="Optional override file containing one hash per line; otherwise qB torrents under --source-root are auto-selected",
    )
    p_migrate.add_argument(
        "-f",
        "--fastresume-dir",
        default=str(DEFAULT_FASTRESUME_DIR),
        help="Directory containing qB .fastresume files",
    )
    p_migrate.add_argument(
        "-t",
        "--torrent-dir",
        default="",
        help="Directory containing .torrent metadata files (defaults to fastresume dir)",
    )
    p_migrate.add_argument("--export-torrents-dir", default="")
    p_migrate.add_argument("--timeout", type=float, default=1800.0)
    p_migrate.add_argument("--quick-only", action="store_true")
    p_migrate.add_argument("--recheck-source-on-verify-fail", action="store_true")
    p_migrate.add_argument("--recheck-timeout", type=float, default=1800.0)
    p_migrate.add_argument("--allow-partials", action="store_true")
    p_migrate.add_argument("--journal", default="")
    p_migrate.add_argument("--auto-stop-qb", action="store_true")
    p_migrate.add_argument("--auto-cleanup", default=DEFAULT_AUTO_CLEANUP_MODE, choices=["off", "safe"])
    p_migrate.add_argument("--cleanup-journal", default="")
    p_migrate.add_argument("--cleanup-pilot-size", type=int, default=DEFAULT_CLEANUP_PILOT_SIZE)
    p_migrate.add_argument("--cleanup-batch-size", type=int, default=0)
    p_migrate.add_argument("--cleanup-observe-seconds", type=float, default=DEFAULT_CLEANUP_OBSERVE_SECONDS)
    p_migrate.add_argument("--cleanup-min-depth", type=int, default=1)
    p_migrate.add_argument("--pilot-size", type=int, default=DEFAULT_PILOT_SIZE)
    p_migrate.add_argument("--pilot-observe-seconds", type=float, default=15.0)
    p_migrate.add_argument("--resume-remaining", action="store_true")
    p_migrate.add_argument("--recheck-on-failure", action="store_true")
    p_migrate.add_argument("--qb-container", default="")
    p_migrate.add_argument("--qb-status-cmd", default="")
    p_migrate.add_argument("--qb-stop-cmd", default="")
    p_migrate.add_argument("--qb-start-cmd", default="")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    code = 0
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:
            return int(exc.code or 0)

        manifest_path = Path(args.manifest).expanduser() if getattr(args, "manifest", "") else None
        cli_argv = list(argv if argv is not None else sys.argv[1:])
        initialize_run_logging(
            phase=str(getattr(args, "phase", "run") or "run"),
            argv=cli_argv,
            manifest_path=manifest_path,
        )
        emit_run_boundary("start", phase=getattr(args, "phase", ""))
        log_only("run_args", args=dict(vars(args)))

        runner = SubprocessRunner()
        controller = build_process_controller(args, runner)
        tool = QBZFSRelocationTool(
            runner=runner,
            process_controller=controller,
        )
        assert manifest_path is not None

        if args.phase == "plan":
            hashes = list(args.hashes or [])
            if args.hashes_file:
                hashes.extend(load_hashes_file(Path(args.hashes_file).expanduser()))
            fastresume_dir = Path(args.fastresume_dir).expanduser()
            torrent_dir = Path(args.torrent_dir or args.fastresume_dir).expanduser()
            export_dir = Path(args.export_torrents_dir).expanduser() if args.export_torrents_dir else None
            code = tool.plan(
                manifest_path=manifest_path,
                hashes=hashes,
                source_root=args.source_root,
                dest_root=args.dest_root,
                batch_size=int(args.batch_size),
                fastresume_dir=fastresume_dir,
                torrent_dir=torrent_dir,
                export_torrents_dir=export_dir,
            )
        elif args.phase == "copy":
            code = tool.copy(manifest_path=manifest_path, apply=resolve_apply(args))
        elif args.phase == "verify":
            code = tool.verify(
                manifest_path=manifest_path,
                timeout_seconds=float(args.timeout),
                quick_only=bool(args.quick_only),
                recheck_source_on_fail=bool(args.recheck_source_on_fail),
                recheck_timeout_seconds=float(args.recheck_timeout),
            )
        elif args.phase == "validate":
            journal_path = Path(args.journal).expanduser() if args.journal else None
            code = tool.validate(
                manifest_path=manifest_path,
                allow_partials=bool(args.allow_partials),
                for_patch=bool(args.for_patch),
                journal_path=journal_path,
            )
        elif args.phase == "patch":
            journal_path = (
                Path(args.journal).expanduser()
                if args.journal
                else manifest_report_path(manifest_path, "patch-journal", ".jsonl")
            )
            code = tool.patch(
                manifest_path=manifest_path,
                journal_path=journal_path,
                apply=resolve_apply(args),
                auto_stop_qb=bool(args.auto_stop_qb),
            )
        elif args.phase == "resume":
            code = tool.resume(
                manifest_path=manifest_path,
                apply=resolve_apply(args),
                pilot_size=int(args.pilot_size),
                observe_seconds=float(args.pilot_observe_seconds),
                resume_remaining=bool(args.resume_remaining),
                recheck_on_failure=bool(args.recheck_on_failure),
            )
        elif args.phase == "cleanup":
            cleanup_journal_path = (
                Path(args.cleanup_journal).expanduser()
                if args.cleanup_journal
                else None
            )
            code = tool.cleanup(
                manifest_path=manifest_path,
                apply=resolve_apply(args),
                confirm_cleanup=bool(args.confirm_cleanup),
                journal_path=cleanup_journal_path,
                cleanup_pilot_size=int(args.cleanup_pilot_size),
                cleanup_batch_size=int(args.cleanup_batch_size),
                cleanup_observe_seconds=float(args.cleanup_observe_seconds),
                cleanup_min_depth=int(args.cleanup_min_depth),
            )
        elif args.phase == "rollback":
            journal_path = (
                Path(args.journal).expanduser()
                if args.journal
                else manifest_report_path(manifest_path, "patch-journal", ".jsonl")
            )
            code = tool.rollback(
                manifest_path=manifest_path,
                journal_path=journal_path,
                apply=resolve_apply(args),
                auto_stop_qb=bool(args.auto_stop_qb),
            )
        elif args.phase == "migrate":
            hashes = list(args.hashes or [])
            if args.hashes_file:
                hashes.extend(load_hashes_file(Path(args.hashes_file).expanduser()))
            fastresume_dir = Path(args.fastresume_dir).expanduser()
            torrent_dir = Path(args.torrent_dir or args.fastresume_dir).expanduser()
            export_dir = Path(args.export_torrents_dir).expanduser() if args.export_torrents_dir else None
            journal_path = (
                Path(args.journal).expanduser()
                if args.journal
                else manifest_report_path(manifest_path, "patch-journal", ".jsonl")
            )
            cleanup_journal_path = (
                Path(args.cleanup_journal).expanduser()
                if args.cleanup_journal
                else None
            )
            code = tool.migrate(
                manifest_path=manifest_path,
                hashes=hashes,
                source_root=args.source_root,
                dest_root=args.dest_root,
                batch_size=int(args.batch_size),
                fastresume_dir=fastresume_dir,
                torrent_dir=torrent_dir,
                export_torrents_dir=export_dir,
                apply=resolve_apply(args),
                timeout_seconds=float(args.timeout),
                quick_only=bool(args.quick_only),
                recheck_source_on_verify_fail=bool(args.recheck_source_on_verify_fail),
                recheck_timeout_seconds=float(args.recheck_timeout),
                allow_partials=bool(args.allow_partials),
                journal_path=journal_path,
                auto_stop_qb=bool(args.auto_stop_qb),
                auto_cleanup_mode=str(args.auto_cleanup or DEFAULT_AUTO_CLEANUP_MODE),
                cleanup_journal_path=cleanup_journal_path,
                pilot_size=int(args.pilot_size),
                observe_seconds=float(args.pilot_observe_seconds),
                resume_remaining=bool(args.resume_remaining),
                recheck_on_failure=bool(args.recheck_on_failure),
                cleanup_pilot_size=int(args.cleanup_pilot_size),
                cleanup_batch_size=int(args.cleanup_batch_size),
                cleanup_observe_seconds=float(args.cleanup_observe_seconds),
                cleanup_min_depth=int(args.cleanup_min_depth),
            )
        else:
            raise RelocationError(f"unsupported_phase {args.phase}")
    except RelocationError as exc:
        emit_log("error", reason=str(exc))
        code = 1
    emit_run_boundary("end", exit_code=code)
    close_run_logging()
    return code
