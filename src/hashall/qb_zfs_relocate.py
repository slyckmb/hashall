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
SCRIPT_VERSION = "0.1.0"
SCRIPT_LAST_UPDATED = "2026-03-08"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FASTRESUME_DIR = Path(
    "/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"
)
DEFAULT_VERIFIER = REPO_ROOT / "bin" / "qb-libtorrent-verify.py"
DEFAULT_PILOT_SIZE = 5
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


class RelocationError(RuntimeError):
    """Raised for fail-closed relocation workflow errors."""


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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


def path_kind(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_dir():
        return "dir"
    if path.is_file():
        return "file"
    return "other"


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def emit_log(event: str, **fields: Any) -> None:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", "\\n")
        if " " in text:
            text = json.dumps(text)
        parts.append(f"{key}={text}")
    print(" ".join(parts))


def emit_run_boundary(event: str, *, exit_code: Optional[int] = None) -> None:
    fields: Dict[str, Any] = {
        "script": SCRIPT_NAME,
        "version": SCRIPT_VERSION,
        "last_updated": SCRIPT_LAST_UPDATED,
        "timestamp": ts_iso(),
    }
    if exit_code is not None:
        fields["exit_code"] = int(exit_code)
    emit_log(event, **fields)


def emit_summary(summary: Dict[str, Any]) -> None:
    print("[📊 Summary]")
    for key in sorted(summary.keys()):
        print(f"{key}={summary[key]}")


def load_hashes_file(path: Path) -> List[str]:
    return normalize_hashes(path.read_text(encoding="utf-8").splitlines())


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


class SubprocessRunner:
    """Thin subprocess wrapper that is easy to stub in tests."""

    def run(
        self,
        cmd: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(cmd),
            check=check,
            text=True,
            capture_output=capture_output,
        )


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
        if quick_only:
            cmd.append("--quick-only")
        proc = self.runner.run(cmd)
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

    def _load_manifest(self, manifest_path: Path) -> Dict[str, Any]:
        manifest = load_json(manifest_path)
        if not isinstance(manifest, dict):
            raise RelocationError(f"invalid_manifest path={manifest_path}")
        manifest.setdefault("rows", [])
        manifest.setdefault("global_issues", [])
        return manifest

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

    def _pause_selected(self, rows: Sequence[Dict[str, Any]]) -> None:
        hashes = [row["hash"] for row in rows if row.get("selected")]
        if not hashes:
            return
        if not self.qb_client.pause_torrents(hashes):
            raise RelocationError("pause_selected_failed")
        for torrent_hash in hashes:
            self._wait_for_stopped(torrent_hash)

    def plan(
        self,
        *,
        manifest_path: Path,
        hashes: Sequence[str],
        source_root: str,
        dest_root: str,
        fastresume_dir: Path,
        torrent_dir: Path,
        export_torrents_dir: Optional[Path],
    ) -> int:
        source_root_n = normalize_save_path(source_root)
        dest_root_n = normalize_save_path(dest_root)
        if source_root_n == dest_root_n:
            raise RelocationError("source_and_destination_roots_must_differ")
        selected_hashes = normalize_hashes(hashes)
        if not selected_hashes:
            raise RelocationError("no_selected_hashes")
        info_by_hash = self.qb_client.get_torrents_by_hashes(selected_hashes)
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
                "patch_status": "pending",
                "resume_status": "pending",
                "cleanup_status": "pending",
                "cleanup_ready": False,
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
            "selection": {"hashes": selected_hashes},
            "global_issues": [],
            "phase_history": [],
            "rows": rows,
        }
        report_path = manifest_report_path(manifest_path, "plan")
        write_json(report_path, {"phase": "plan", "rows": rows, "generated_at": ts_iso()})
        self._save_manifest(manifest_path, manifest, phase="plan", mode="apply", report_path=report_path)
        emit_summary(
            {
                "selected": len(selected_hashes),
                "rows": len(rows),
                "ready": sum(1 for row in rows if not row["issues"]),
                "issues": sum(1 for row in rows if row["issues"]),
            }
        )
        return 0

    def copy(self, *, manifest_path: Path, apply: bool) -> int:
        manifest = self._load_manifest(manifest_path)
        rows = row_selection(manifest["rows"])
        if apply:
            self._pause_selected(rows)
        results: List[Dict[str, Any]] = []
        for row in rows:
            source_path = Path(str(row.get("content_path") or ""))
            dest_parent = Path(str(row.get("new_save_path") or ""))
            if not source_path.exists():
                row["copy_status"] = "source_missing"
                add_issue(row, "source_payload_missing")
                results.append({"hash": row["hash"], "status": row["copy_status"]})
                continue
            if not row.get("new_save_path"):
                row["copy_status"] = "missing_target"
                add_issue(row, "new_save_path_missing")
                results.append({"hash": row["hash"], "status": row["copy_status"]})
                continue
            cmd = [
                "rsync",
                "-aHAX",
                "--numeric-ids",
                "--itemize-changes",
            ]
            if not apply:
                cmd.append("--dry-run")
            if source_path.is_dir():
                cmd.extend([str(source_path), str(dest_parent)])
            else:
                cmd.extend([str(source_path), str(dest_parent)])
            if apply:
                dest_parent.mkdir(parents=True, exist_ok=True)
            proc = self.runner.run(cmd)
            row["copy_status"] = "copied" if apply and proc.returncode == 0 else "dryrun"
            if proc.returncode != 0:
                row["copy_status"] = "copy_failed"
                add_issue(row, "copy_failed")
            dest_content = Path(str(row.get("dest_content_path") or ""))
            row["dest_exists"] = bool(dest_content and dest_content.exists())
            row["dest_kind"] = path_kind(dest_content) if str(row.get("dest_content_path") or "") else "missing"
            results.append(
                {
                    "hash": row["hash"],
                    "status": row["copy_status"],
                    "rc": int(proc.returncode),
                    "cmd": cmd,
                }
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
    ) -> int:
        manifest = self._load_manifest(manifest_path)
        rows = row_selection(manifest["rows"])
        verify_dir = manifest_report_path(manifest_path, "verify", suffix="")
        results: List[Dict[str, Any]] = []
        for row in rows:
            torrent_path = Path(str(row.get("torrent_path") or ""))
            dest_content = Path(str(row.get("dest_content_path") or ""))
            if not torrent_path.exists():
                row["verify_status"] = "torrent_missing"
                row["verified"] = False
                add_issue(row, "torrent_metadata_missing")
                results.append({"hash": row["hash"], "status": row["verify_status"]})
                continue
            if not dest_content.exists():
                row["verify_status"] = "dest_missing"
                row["verified"] = False
                add_issue(row, "destination_payload_missing")
                results.append({"hash": row["hash"], "status": row["verify_status"]})
                continue
            report_path = verify_dir / f"{row['hash']}.json"
            payload = self.verifier.verify(
                torrent_path,
                dest_content,
                report_path,
                timeout_seconds=timeout_seconds,
                quick_only=quick_only,
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
            else:
                add_issue(row, "offline_verify_failed")
            results.append(
                {
                    "hash": row["hash"],
                    "status": row["verify_status"],
                    "classification": row.get("verify_classification"),
                    "report_path": str(report_path),
                }
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
    ) -> int:
        manifest = self._load_manifest(manifest_path)
        rows = row_selection(manifest["rows"])
        hashes = [str(row.get("hash") or "") for row in rows]
        duplicates = len(hashes) != len(set(hashes))
        global_issues: List[str] = []
        if duplicates:
            global_issues.append("duplicate_hashes_in_manifest")
        if for_patch:
            controller = self._ensure_controller()
            if not controller.is_stopped():
                global_issues.append("qbittorrent_must_be_stopped_before_patch")
            journal_target = journal_path or manifest_report_path(manifest_path, "patch-journal", ".jsonl")
            if not journal_target.parent.exists():
                global_issues.append("journal_parent_missing")
        for row in rows:
            issues = list(row.get("plan_issues") or [])
            torrent_path = Path(str(row.get("torrent_path") or ""))
            fastresume_path = Path(str(row.get("fastresume_path") or ""))
            dest_content = Path(str(row.get("dest_content_path") or ""))
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
                issues.append("source_and_destination_paths_identical")
            if not bool(row.get("path_shape_match")):
                issues.append("path_shape_mismatch")
            if not bool(row.get("verified")):
                issues.append("offline_verify_failed")
            info = self.qb_client.get_torrent_info(row["hash"])
            if info is None:
                issues.append("qb_torrent_not_found")
            else:
                row["state"] = str(info.state or "")
                row["progress"] = float(info.progress or 0.0)
                if not is_stopped_state(info.state):
                    issues.append("torrent_not_stopped")
                if not allow_partials and float(info.progress or 0.0) < 1.0:
                    issues.append("torrent_not_complete")
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
        observe_seconds: float,
        recheck_on_failure: bool,
    ) -> None:
        deadline = time.time() + observe_seconds
        problems: List[str] = []
        first_pass = True
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
            if not problems:
                return
            self.sleep_fn(1.0)
        if recheck_on_failure:
            for row in rows:
                info = self.qb_client.get_torrent_info(row["hash"])
                state = str(getattr(info, "state", "") or "").lower()
                if state in BAD_RESUME_STATES:
                    self.qb_client.recheck_torrent(row["hash"])
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
        rows = [
            row
            for row in row_selection(manifest["rows"])
            if row.get("actionable") and row.get("patch_status") in {"patched", "no_change"}
        ]
        if not rows:
            raise RelocationError("no_patch_ready_rows_for_resume")
        controller = self._ensure_controller()
        if apply and controller.is_stopped():
            controller.start()
        self._wait_for_qb_online()
        eligible: List[Dict[str, Any]] = []
        for row in rows:
            info = self.qb_client.get_torrent_info(row["hash"])
            if info is None:
                row["resume_status"] = "missing_info"
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

    def cleanup(self, *, manifest_path: Path, apply: bool, confirm_cleanup: bool) -> int:
        manifest = self._load_manifest(manifest_path)
        rows = [row for row in row_selection(manifest["rows"]) if row.get("cleanup_ready")]
        if apply and not confirm_cleanup:
            raise RelocationError("cleanup_requires_confirm_cleanup")
        results: List[Dict[str, Any]] = []
        for row in rows:
            source_path = Path(str(row.get("content_path") or ""))
            if not source_path.exists():
                row["cleanup_status"] = "source_missing"
                results.append({"hash": row["hash"], "status": row["cleanup_status"]})
                continue
            if not apply:
                row["cleanup_status"] = "dryrun"
                results.append({"hash": row["hash"], "status": row["cleanup_status"]})
                continue
            if source_path.is_dir():
                shutil.rmtree(source_path)
            else:
                source_path.unlink()
            row["cleanup_status"] = "cleaned"
            results.append({"hash": row["hash"], "status": row["cleanup_status"]})
        report_path = manifest_report_path(manifest_path, "cleanup")
        write_json(report_path, {"phase": "cleanup", "apply": bool(apply), "results": results, "generated_at": ts_iso()})
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
                "rows": len(rows),
            }
        )
        return 0

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
    p_plan.add_argument("-H", "--hash", action="append", default=[], dest="hashes")
    p_plan.add_argument("-i", "--hashes-file", default="", help="File containing one hash per line")
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

    p_cleanup = subparsers.add_parser("cleanup", help="Remove old source payloads after successful resume")
    add_common_manifest_argument(p_cleanup)
    add_mutation_flags(p_cleanup)
    p_cleanup.add_argument("-y", "--confirm-cleanup", action="store_true")

    p_rollback = subparsers.add_parser("rollback", help="Restore fastresume backups from the patch journal")
    add_common_manifest_argument(p_rollback)
    add_mutation_flags(p_rollback)
    p_rollback.add_argument("--journal", default="")
    p_rollback.add_argument("--auto-stop-qb", action="store_true")
    p_rollback.add_argument("--qb-container", default="")
    p_rollback.add_argument("--qb-status-cmd", default="")
    p_rollback.add_argument("--qb-stop-cmd", default="")
    p_rollback.add_argument("--qb-start-cmd", default="")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    emit_run_boundary("start")
    parser = build_parser()
    try:
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
            emit_run_boundary("end", exit_code=code)
            return code

        runner = SubprocessRunner()
        controller = build_process_controller(args, runner)
        tool = QBZFSRelocationTool(
            runner=runner,
            process_controller=controller,
        )
        manifest_path = Path(args.manifest).expanduser()

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
            code = tool.cleanup(
                manifest_path=manifest_path,
                apply=resolve_apply(args),
                confirm_cleanup=bool(args.confirm_cleanup),
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
        else:
            raise RelocationError(f"unsupported_phase {args.phase}")
    except RelocationError as exc:
        emit_log("error", reason=str(exc))
        code = 1
    emit_run_boundary("end", exit_code=code)
    return code
