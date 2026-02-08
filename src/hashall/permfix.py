"""
Permission remediation helpers for link preflight.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
import grp
import pwd
import shutil


@dataclass
class PermFixSummary:
    changed: int = 0
    failed: int = 0
    skipped: int = 0
    checked: int = 0


def _stat_info(path: Path) -> dict:
    st = path.stat()
    return {
        "uid": st.st_uid,
        "gid": st.st_gid,
        "mode": oct(st.st_mode & 0o7777),
    }


def _run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _apply_with_sudo(cmd: list[str], use_sudo: bool) -> subprocess.CompletedProcess:
    if not use_sudo:
        return _run_cmd(cmd)
    return _run_cmd(["sudo"] + cmd)

def resolve_plan_paths_for_permfix(
    rows: Iterable[tuple[str, str]],
    mount_point: Path | None,
) -> set[Path]:
    """
    Expand (canonical_path, duplicate_path) DB rows into concrete filesystem paths to remediate.

    Link plans store paths relative to the plan mount point. For permfix we need absolute paths
    that exist on disk. We include both the file paths and their parent directories because
    hardlinking requires directory write permission (rename/unlink in target dir).
    """
    out: set[Path] = set()
    for canonical, duplicate in rows:
        for raw in (canonical, duplicate):
            p = Path(raw)
            if not p.is_absolute() and mount_point is not None:
                p = mount_point / p
            out.add(p)
            out.add(p.parent)
    return out


def fix_permissions(
    paths: Iterable[Path],
    target_gid: int,
    target_uid: int,
    *,
    fix_owner_root: bool = True,
    fix_acl: bool = False,
    use_sudo: bool = True,
    log_path: Path | None = None,
    root_label: str | None = None,
) -> tuple[PermFixSummary, Path | None]:
    """
    Fix ownership/group/perms on a set of paths. Returns summary + log path.
    """
    summary = PermFixSummary()
    changes: list[dict] = []
    errors: list[dict] = []

    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    gid_name = None
    uid_name = None
    try:
        gid_name = grp.getgrgid(target_gid).gr_name
    except KeyError:
        gid_name = str(target_gid)
    try:
        uid_name = pwd.getpwuid(target_uid).pw_name
    except KeyError:
        uid_name = str(target_uid)

    for path in paths:
        summary.checked += 1
        try:
            if not path.exists() or path.is_symlink():
                summary.skipped += 1
                continue
            is_dir = path.is_dir()
            before = _stat_info(path)
            actions: list[str] = []
            used_sudo = False

            desired_mode = int(before["mode"], 8)
            desired_mode |= stat.S_IWGRP
            if is_dir:
                desired_mode |= stat.S_IXGRP

            if before["gid"] != target_gid:
                actions.append("chgrp")
            if fix_owner_root and before["uid"] == 0 and target_uid != 0:
                actions.append("chown")
            if desired_mode != int(before["mode"], 8):
                actions.append("chmod")
            if fix_acl and is_dir:
                actions.append("setfacl")

            if not actions:
                summary.skipped += 1
                continue

            # Apply changes
            if "chown" in actions or "chgrp" in actions:
                owner = str(before["uid"])
                group = str(before["gid"])
                if "chown" in actions:
                    owner = str(target_uid)
                if "chgrp" in actions:
                    group = str(target_gid)
                try:
                    os.chown(path, int(owner), int(group))
                except PermissionError:
                    used_sudo = True
                    result = _apply_with_sudo(["chown", f"{owner}:{group}", str(path)], use_sudo)
                    if result.returncode != 0:
                        raise PermissionError(result.stderr.strip() or result.stdout.strip())

            if "chmod" in actions:
                try:
                    os.chmod(path, desired_mode)
                except PermissionError:
                    used_sudo = True
                    result = _apply_with_sudo(["chmod", oct(desired_mode)[2:], str(path)], use_sudo)
                    if result.returncode != 0:
                        raise PermissionError(result.stderr.strip() or result.stdout.strip())

            if "setfacl" in actions:
                setfacl = shutil.which("setfacl")
                if not setfacl:
                    raise PermissionError("setfacl not found")
                acl_spec = f"g:{gid_name}:rwx"
                result = _apply_with_sudo(
                    [setfacl, "-m", acl_spec, "-d", acl_spec, str(path)], use_sudo
                )
                if result.returncode != 0:
                    raise PermissionError(result.stderr.strip() or result.stdout.strip())

            after = _stat_info(path)
            summary.changed += 1
            changes.append({
                "path": str(path),
                "is_dir": is_dir,
                "before": before,
                "after": after,
                "actions": actions,
                "used_sudo": used_sudo,
            })

        except Exception as exc:
            summary.failed += 1
            errors.append({
                "path": str(path),
                "error": str(exc),
            })

    log_written = None
    if log_path:
        payload = {
            "run_at": datetime.now().astimezone().isoformat(),
            "root": root_label,
            "target_group": {"gid": target_gid, "name": gid_name},
            "target_owner": {"uid": target_uid, "name": uid_name},
            "fix_acl": fix_acl,
            "summary": summary.__dict__,
            "changes": changes,
            "errors": errors,
        }
        log_path.write_text(json.dumps(payload, indent=2))
        log_written = log_path

    return summary, log_written
