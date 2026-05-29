from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import html
import shutil
import requests
import re
import time

from hashall.bencode import bencode_decode
from hashall.pathing import canonicalize_path


DEFAULT_RT_SESSION_DIR = Path("/dump/docker/gluetun_qbit/rtorrent_vpn/.session")
DEFAULT_RT_RPC_URL = "http://127.0.0.1:18000/"
RT_PATH_PREFIX_ALIASES: tuple[tuple[Path, Path], ...] = (
    (Path("/stash"), Path("/data")),
    (Path("/dump/docker/gluetun_qbit/rtorrent_vpn/.session"), Path("/config/.session")),
)


@dataclass(frozen=True)
class RTSessionEntry:
    torrent_hash: str
    directory: str
    path_exists: bool


@dataclass(frozen=True)
class RTTorrentMeta:
    torrent_hash: str
    info_name: str
    is_multi_file: bool
    file_count: int = 0
    total_bytes: int = 0


@dataclass(frozen=True)
class RTSessionFiles:
    torrent_hash: str
    torrent_file: Path
    rtorrent_file: Path
    libtorrent_resume_file: Path


@dataclass(frozen=True)
class RTTorrentInventoryRow:
    torrent_hash: str
    root_name: str
    save_path: str
    content_path: str
    expected_file_count: int = 0
    expected_total_bytes: int = 0


def rt_path_aligned(
    rt_directory: str | None,
    *,
    qb_save_path: str | None,
    qb_content_path: str | None,
) -> bool:
    raw_rt = str(rt_directory or "").strip()
    if not raw_rt:
        return False
    try:
        rt_dir = str(canonicalize_path(Path(raw_rt)))
    except Exception:
        rt_dir = raw_rt

    candidates: set[str] = set()
    for raw in (qb_save_path, qb_content_path):
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            path = canonicalize_path(Path(text))
            candidates.add(str(path))
            candidates.add(str(path.parent))
        except Exception:
            candidates.add(text)

    # For deeply-nested content (e.g. canonically triply-nested torrents),
    # add all ancestors between content_path and save_path so RT's directory
    # (which is save_path/info_name) is recognised as aligned.
    try:
        sp = str(canonicalize_path(Path(str(qb_save_path or "").strip())))
        cp_path = canonicalize_path(Path(str(qb_content_path or "").strip()))
        ancestor = cp_path.parent
        while True:
            a_str = str(ancestor)
            if a_str == sp or not a_str.startswith(sp + "/"):
                break
            candidates.add(a_str)
            ancestor = ancestor.parent
    except Exception:
        pass

    return rt_dir in candidates


def load_rt_session_directories(session_dir: Path = DEFAULT_RT_SESSION_DIR) -> dict[str, RTSessionEntry]:
    out: dict[str, RTSessionEntry] = {}
    if not session_dir.exists():
        return out
    for path in session_dir.glob("*.torrent.rtorrent"):
        stem = path.name.split(".", 1)[0].strip().lower()
        if not stem:
            continue
        try:
            payload = bencode_decode(path.read_bytes())
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        raw_dir = payload.get(b"directory")
        if not isinstance(raw_dir, bytes):
            continue
        try:
            directory = str(canonicalize_path(Path(raw_dir.decode("utf-8", "ignore"))))
        except Exception:
            directory = raw_dir.decode("utf-8", "ignore")
        out[stem] = RTSessionEntry(
            torrent_hash=stem,
            directory=directory,
            path_exists=bool(directory and Path(directory).exists()),
        )
    return out


def live_rt_root_paths(session_dir: Path = DEFAULT_RT_SESSION_DIR) -> frozenset[str]:
    return frozenset(
        entry.directory
        for entry in load_rt_session_directories(session_dir).values()
        if entry.directory
    )


def _resolve_rt_session_file(session_dir: Path, torrent_hash: str, suffix: str) -> Path:
    key = str(torrent_hash).strip()
    candidates = (
        session_dir / f"{key.upper()}{suffix}",
        session_dir / f"{key.lower()}{suffix}",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_rt_session_files(session_dir: Path, torrent_hash: str) -> RTSessionFiles:
    torrent_key = str(torrent_hash).strip().lower()
    return RTSessionFiles(
        torrent_hash=torrent_key,
        torrent_file=_resolve_rt_session_file(session_dir, torrent_key, ".torrent"),
        rtorrent_file=_resolve_rt_session_file(session_dir, torrent_key, ".torrent.rtorrent"),
        libtorrent_resume_file=_resolve_rt_session_file(session_dir, torrent_key, ".torrent.libtorrent_resume"),
    )


def map_rt_runtime_path(path: Path | str) -> str:
    candidate = Path(path)
    for src_prefix, dest_prefix in RT_PATH_PREFIX_ALIASES:
        try:
            rel = candidate.relative_to(src_prefix)
        except ValueError:
            continue
        return str(dest_prefix / rel)
    return str(candidate)


def backup_rt_session_files(
    session_files: RTSessionFiles,
    *,
    backup_root: Path,
    stamp: str | None = None,
) -> Path:
    ts = str(stamp or time.strftime("%Y%m%d-%H%M%S"))
    target_dir = backup_root / ts / session_files.torrent_hash
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in (
        session_files.torrent_file,
        session_files.rtorrent_file,
        session_files.libtorrent_resume_file,
    ):
        if path.exists():
            shutil.copy2(path, target_dir / path.name)
    return target_dir


def restore_rt_session_files(session_files: RTSessionFiles, *, backup_dir: Path) -> list[str]:
    completed: list[str] = []
    for label, path in (
        ("session.torrent", session_files.torrent_file),
        ("session.rtorrent", session_files.rtorrent_file),
        ("session.libtorrent_resume", session_files.libtorrent_resume_file),
    ):
        backup_path = backup_dir / path.name
        if backup_path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, path)
            completed.append(f"{label}.restore")
        elif path.exists():
            path.unlink()
            completed.append(f"{label}.unlink_unbacked")
    return completed


def _xml_escape(value: str) -> str:
    text = str(value)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def rt_script_quote(value: str) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def rt_build_load_cmd(method: str, value: str) -> str:
    return f"{method}={rt_script_quote(value)}"


def _xmlrpc_value_xml(arg: object) -> str:
    """Serialize one argument as an XMLRPC <value> element (no <param> wrapper)."""
    if isinstance(arg, bytes):
        return f"<value><base64>{base64.b64encode(arg).decode()}</base64></value>"
    if isinstance(arg, int):
        return f"<value><i8>{arg}</i8></value>"
    return f"<value><string>{_xml_escape(str(arg))}</string></value>"


def rt_xmlrpc_call(method: str, *args: str, rpc_url: str = DEFAULT_RT_RPC_URL, timeout: int = 20) -> str:
    params_parts: list[str] = []
    for arg in args:
        if isinstance(arg, bytes):
            params_parts.append(
                f"<param><value><base64>{base64.b64encode(arg).decode()}</base64></value></param>"
            )
        elif isinstance(arg, int):
            params_parts.append(f"<param><value><i8>{arg}</i8></value></param>")
        else:
            params_parts.append(
                f"<param><value><string>{_xml_escape(str(arg))}</string></value></param>"
            )
    params = "".join(params_parts)
    body = (
        '<?xml version="1.0"?>'
        f"<methodCall><methodName>{method}</methodName><params>{params}</params></methodCall>"
    )
    response = requests.post(
        rpc_url,
        data=body,
        headers={"Content-Type": "text/xml"},
        timeout=timeout,
    )
    response.raise_for_status()
    if "<fault>" in response.text:
        match = re.search(r"<name>faultString</name><value><string>(.*?)</string>", response.text, re.DOTALL)
        detail = match.group(1) if match else response.text
        raise RuntimeError(f"rt_xmlrpc_fault method={method} detail={detail}")
    return response.text


def rt_xmlrpc_multicall(
    calls: list[tuple],
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    timeout: int = 60,
) -> list[str]:
    """Send multiple XMLRPC calls in one HTTP request via system.multicall.

    Each element of *calls* is a tuple of (method_name, *args).
    Returns a list of the method names that were sent (all of them on success).
    Raises RuntimeError if the response contains any fault.
    """
    call_items: list[str] = []
    method_names: list[str] = []
    for call in calls:
        method = call[0]
        method_names.append(method)
        args_xml = "".join(_xmlrpc_value_xml(a) for a in call[1:])
        call_items.append(
            "<value><struct>"
            f"<member><name>methodName</name><value><string>{_xml_escape(method)}</string></value></member>"
            f"<member><name>params</name><value><array><data>{args_xml}</data></array></value></member>"
            "</struct></value>"
        )
    body = (
        '<?xml version="1.0"?>'
        "<methodCall><methodName>system.multicall</methodName>"
        "<params><param><value><array><data>"
        + "".join(call_items)
        + "</data></array></value></param></params></methodCall>"
    )
    response = requests.post(
        rpc_url,
        data=body,
        headers={"Content-Type": "text/xml"},
        timeout=timeout,
    )
    response.raise_for_status()
    xml = response.text
    if "<fault>" in xml:
        fault_strings = re.findall(
            r"<name>faultString</name><value><string>(.*?)</string>", xml, re.DOTALL
        )
        fault_codes = re.findall(
            r"<name>faultCode</name><value><i4>(\d+)</i4>", xml, re.DOTALL
        )
        faults = []
        for i, fs in enumerate(fault_strings):
            code = fault_codes[i] if i < len(fault_codes) else "?"
            idx = i + 1
            faults.append(f"[{idx}] code={code} {fs}")
        if not faults:
            faults.append(f"raw={xml[:500]}")
        raise RuntimeError(
            f"rt_xmlrpc_multicall {len(faults)} fault(s) in {len(calls)} calls: "
            + "; ".join(faults[:5])
        )
    return method_names


def _xmlrpc_scalar_text(xml: str) -> str:
    match = re.search(r"<string>(.*?)</string>", xml, re.DOTALL)
    if match:
        return html.unescape(match.group(1))
    match = re.search(r"<(?:i4|i8|int)>(\d+)</(?:i4|i8|int)>", xml)
    if match:
        return match.group(1)
    match = re.search(r"<value>\s*([^<]+?)\s*</value>", xml, re.DOTALL)
    if match:
        return html.unescape(match.group(1))
    return ""


def rt_xmlrpc_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, requests.Timeout)):
        return True
    text = str(exc).lower()
    return "timed out" in text or "read timeout" in text or "timeout" in text


def rt_get_torrent_directory(
    torrent_hash: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    timeout: int = 20,
) -> str | None:
    try:
        xml = rt_xmlrpc_call("d.directory", str(torrent_hash).strip().lower(), rpc_url=rpc_url, timeout=timeout)
    except Exception:
        return None
    directory = _xmlrpc_scalar_text(xml).strip()
    return directory or None


def _canonical_path_text(value: str | Path | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(canonicalize_path(Path(text)))
    except Exception:
        return text


def rt_directories_match(actual: str | None, expected: str | None) -> bool:
    return bool(actual and expected and _canonical_path_text(actual) == _canonical_path_text(expected))


def rt_expected_loaded_directory(target_directory: str, torrent_meta: RTTorrentMeta | None) -> str:
    normalized = normalize_rt_target_directory(target_directory, torrent_meta)
    if torrent_meta and torrent_meta.is_multi_file and torrent_meta.info_name:
        try:
            return str(canonicalize_path(Path(normalized) / torrent_meta.info_name))
        except Exception:
            return str(Path(normalized) / torrent_meta.info_name)
    return normalized


def load_rt_torrent_meta(session_dir: Path, torrent_hash: str) -> RTTorrentMeta | None:
    torrent_file = session_dir / f"{str(torrent_hash).upper()}.torrent"
    if not torrent_file.exists():
        torrent_file = session_dir / f"{str(torrent_hash).lower()}.torrent"
    if not torrent_file.exists():
        return None
    try:
        payload = bencode_decode(torrent_file.read_bytes())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    info = payload.get(b"info")
    if not isinstance(info, dict):
        return None
    raw_name = info.get(b"name")
    if isinstance(raw_name, bytes):
        info_name = raw_name.decode("utf-8", "ignore")
    else:
        info_name = ""
    files = info.get(b"files")
    if isinstance(files, list):
        total_bytes = 0
        file_count = 0
        for item in files:
            if not isinstance(item, dict):
                continue
            try:
                length = int(item.get(b"length", 0) or 0)
            except Exception:
                length = 0
            total_bytes += max(0, length)
            file_count += 1
    else:
        try:
            total_bytes = int(info.get(b"length", 0) or 0)
        except Exception:
            total_bytes = 0
        file_count = 1 if total_bytes >= 0 else 0
    return RTTorrentMeta(
        torrent_hash=str(torrent_hash).lower(),
        info_name=info_name,
        is_multi_file=isinstance(info.get(b"files"), list),
        file_count=file_count,
        total_bytes=total_bytes,
    )


def load_rt_inventory_rows(
    session_dir: Path = DEFAULT_RT_SESSION_DIR,
) -> list[RTTorrentInventoryRow]:
    rows: list[RTTorrentInventoryRow] = []
    session_rows = load_rt_session_directories(session_dir)
    for torrent_hash, session_entry in session_rows.items():
        meta = load_rt_torrent_meta(session_dir, torrent_hash)
        root_name = (meta.info_name if meta and meta.info_name else "").strip()
        if not root_name:
            continue
        save_path = str(session_entry.directory or "").strip()
        if not save_path:
            continue
        try:
            save_path = str(canonicalize_path(Path(save_path)))
        except Exception:
            pass
        if meta and meta.is_multi_file:
            # rTorrent's d.directory is already the payload root for multi-file torrents.
            content_path = save_path
        else:
            content_path = str(Path(save_path) / root_name)
        try:
            content_path = str(canonicalize_path(Path(content_path)))
        except Exception:
            pass
        rows.append(
            RTTorrentInventoryRow(
                torrent_hash=torrent_hash,
                root_name=root_name,
                save_path=save_path,
                content_path=content_path,
                expected_file_count=int(meta.file_count if meta else 0),
                expected_total_bytes=int(meta.total_bytes if meta else 0),
            )
        )
    rows.sort(key=lambda row: row.torrent_hash)
    return rows


def derive_rt_target_directory(
    *,
    qb_save_path: str | None,
    qb_content_path: str | None,
    torrent_meta: RTTorrentMeta | None,
) -> str:
    save_path = str(qb_save_path or "").strip()
    content_path = str(qb_content_path or "").strip()
    if not save_path and not content_path:
        return ""
    if torrent_meta and torrent_meta.is_multi_file:
        if content_path:
            content = Path(content_path)
            if content.exists() and content.is_dir():
                try:
                    return str(canonicalize_path(content))
                except Exception:
                    return str(content)
        return save_path or str(Path(content_path).parent)
    if content_path:
        try:
            return str(canonicalize_path(Path(content_path).parent))
        except Exception:
            return str(Path(content_path).parent)
    return save_path


def normalize_rt_target_directory(
    target_directory: str | None,
    torrent_meta: RTTorrentMeta | None,
) -> str:
    text = str(target_directory or "").strip()
    if not text:
        return ""
    path = Path(text)
    if torrent_meta and not torrent_meta.is_multi_file:
        # rTorrent expects d.directory to point at the containing directory for
        # single-file torrents, not the file path itself.
        if path.suffix or path.exists() and path.is_file():
            path = path.parent
    if torrent_meta and torrent_meta.is_multi_file and torrent_meta.info_name:
        # load.raw_start expects the containing directory for multi-file
        # torrents; rTorrent then materializes d.directory as parent/info.name.
        if (path.suffix or path.exists() and path.is_file()) and path.parent.name == torrent_meta.info_name:
            path = path.parent.parent
        if path.name == torrent_meta.info_name and path.parent != path:
            path = path.parent
    for src_prefix, dest_prefix in RT_PATH_PREFIX_ALIASES:
        try:
            rel = path.relative_to(src_prefix)
        except ValueError:
            continue
        mapped = dest_prefix / rel
        if mapped.exists():
            path = mapped
            break
    try:
        return str(canonicalize_path(path))
    except Exception:
        return str(path)


def rt_apply_directory_repoint(
    torrent_hash: str,
    target_directory: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    restart: bool = True,
    timeout: int = 60,
) -> list[str]:
    calls: list[tuple] = [
        ("d.stop", torrent_hash),
        ("d.close", torrent_hash),
        ("d.directory.set", torrent_hash, target_directory),
        ("d.save_full_session", torrent_hash),
        ("session.save",),
        ("d.open", torrent_hash),
    ]
    if restart:
        calls.append(("d.start", torrent_hash))
    try:
        return rt_xmlrpc_multicall(calls, rpc_url=rpc_url, timeout=timeout)
    except Exception:
        if restart:
            try:
                current_dir = rt_xmlrpc_call(
                    "d.directory", torrent_hash, rpc_url=rpc_url, timeout=20
                )
                if _xmlrpc_scalar_text(current_dir).rstrip("/") == target_directory.rstrip("/"):
                    rt_xmlrpc_call(
                        "d.start", torrent_hash, rpc_url=rpc_url, timeout=20
                    )
            except Exception:
                pass
        raise


def rt_recheck_torrent(
    torrent_hash: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    timeout: int = 60,
) -> list[str]:
    calls: list[tuple] = [
        ("d.stop", torrent_hash),
        ("d.close", torrent_hash),
        ("d.check_hash", torrent_hash),
        ("d.open", torrent_hash),
        ("d.start", torrent_hash),
    ]
    try:
        return rt_xmlrpc_multicall(calls, rpc_url=rpc_url, timeout=timeout)
    except Exception:
        try:
            rt_xmlrpc_call("d.check_hash", torrent_hash, rpc_url=rpc_url, timeout=20)
            rt_xmlrpc_call("d.start", torrent_hash, rpc_url=rpc_url, timeout=20)
        except Exception:
            pass
        raise


def rt_wait_for_hash_present(
    torrent_hash: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    timeout_s: float = 10.0,
    poll_s: float = 0.25,
) -> bool:
    deadline = time.monotonic() + timeout_s
    target = str(torrent_hash).strip().lower()
    while time.monotonic() < deadline:
        for row in fetch_rt_status_rows(rpc_url=rpc_url):
            if row["hash"] == target:
                return True
        time.sleep(poll_s)
    return False


def rt_wait_for_hash_directory(
    torrent_hash: str,
    expected_directory: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    timeout_s: float = 20.0,
    poll_s: float = 0.5,
    rpc_timeout: int = 20,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        directory = rt_get_torrent_directory(torrent_hash, rpc_url=rpc_url, timeout=rpc_timeout)
        if rt_directories_match(directory, expected_directory):
            return True
        time.sleep(poll_s)
    return False


def rt_reset_torrent_session(
    torrent_hash: str,
    *,
    target_directory: str,
    session_dir: Path = DEFAULT_RT_SESSION_DIR,
    backup_root: Path,
    rpc_url: str = DEFAULT_RT_RPC_URL,
    rpc_timeout: int = 20,
    verify_timeout_s: float = 20.0,
    poll_s: float = 0.5,
) -> dict:
    session_path = Path(session_dir).expanduser()
    session_files = resolve_rt_session_files(session_path, torrent_hash)
    if not session_files.torrent_file.exists():
        raise FileNotFoundError(f"missing_torrent_file path={session_files.torrent_file}")

    backup_dir = backup_rt_session_files(session_files, backup_root=backup_root)
    torrent_meta = load_rt_torrent_meta(session_path, torrent_hash)
    normalized_target = normalize_rt_target_directory(target_directory, torrent_meta)
    if not normalized_target:
        raise ValueError(f"missing_target_directory hash={torrent_hash}")
    expected_loaded_directory = rt_expected_loaded_directory(target_directory, torrent_meta)
    completed: list[str] = []
    recovery_completed: list[str] = []
    session_mutated = False
    reload_verified = False
    status = "unknown"
    phase = "stop_close_erase"
    for method in ("d.stop", "d.close", "d.erase"):
        try:
            rt_xmlrpc_call(method, torrent_hash, rpc_url=rpc_url, timeout=rpc_timeout)
            completed.append(method)
            if method == "d.erase":
                session_mutated = True
        except Exception:
            # If the torrent is not currently active in-memory, continue with
            # the on-disk session reset anyway.
            completed.append(f"{method}:skip")
    try:
        rt_xmlrpc_call("session.save", rpc_url=rpc_url, timeout=rpc_timeout)
        completed.append("session.save")
    except Exception:
        completed.append("session.save:skip")

    runtime_torrent_path = map_rt_runtime_path(session_files.torrent_file)
    error = ""
    try:
        phase = "unlink_session_sidecars"
        if session_files.rtorrent_file.exists():
            session_files.rtorrent_file.unlink()
            session_mutated = True
            completed.append("session.rtorrent.unlink")
        if session_files.libtorrent_resume_file.exists():
            session_files.libtorrent_resume_file.unlink()
            session_mutated = True
            completed.append("session.libtorrent_resume.unlink")
        if not session_files.torrent_file.exists():
            backup_torrent = backup_dir / session_files.torrent_file.name
            if not backup_torrent.exists():
                raise FileNotFoundError(f"missing_backup_torrent path={backup_torrent}")
            shutil.copy2(backup_torrent, session_files.torrent_file)
            completed.append("session.torrent.restore")

        phase = "load.raw_start"
        torrent_bytes = session_files.torrent_file.read_bytes()
        inline_dir_cmd = rt_build_load_cmd("d.directory.set", normalized_target)
        load_timed_out = False
        try:
            rt_xmlrpc_call(
                "load.raw_start",
                "",
                torrent_bytes,
                inline_dir_cmd,
                rpc_url=rpc_url,
                timeout=rpc_timeout,
            )
            completed.append("load.raw_start")
        except Exception as exc:
            if not rt_xmlrpc_timeout_error(exc):
                raise
            load_timed_out = True
            completed.append("load.raw_start:timeout")

        phase = "verify_reload"
        reload_verified = rt_wait_for_hash_directory(
            torrent_hash,
            expected_loaded_directory,
            rpc_url=rpc_url,
            timeout_s=verify_timeout_s,
            poll_s=poll_s,
            rpc_timeout=rpc_timeout,
        )
        if not reload_verified:
            raise RuntimeError(f"torrent_not_reloaded hash={torrent_hash} expected_directory={expected_loaded_directory}")
        if load_timed_out:
            completed.append("load.raw_start:verified_after_timeout")

        phase = "persist_reloaded_session"
        rt_xmlrpc_call("d.save_full_session", torrent_hash, rpc_url=rpc_url, timeout=rpc_timeout)
        completed.append("d.save_full_session")
        rt_xmlrpc_call("session.save", rpc_url=rpc_url, timeout=rpc_timeout)
        completed.append("session.save")

        phase = "recheck"
        completed.extend(rt_recheck_torrent(torrent_hash, rpc_url=rpc_url, timeout=rpc_timeout))
        status = "verified_after_timeout" if load_timed_out else "verified"
    except Exception as exc:
        error = str(exc)
        if session_mutated and not reload_verified:
            phase = f"{phase}:restore"
            try:
                rt_xmlrpc_call("d.erase", torrent_hash, rpc_url=rpc_url, timeout=rpc_timeout)
                recovery_completed.append("d.erase")
            except Exception:
                recovery_completed.append("d.erase:skip")
            try:
                rt_xmlrpc_call("session.save", rpc_url=rpc_url, timeout=rpc_timeout)
                recovery_completed.append("session.save")
            except Exception:
                recovery_completed.append("session.save:skip")
            recovery_completed.extend(restore_rt_session_files(session_files, backup_dir=backup_dir))
            status = "blocked_restored"
        else:
            status = "blocked_after_reload" if reload_verified else "blocked"
    return {
        "hash": str(torrent_hash).strip().lower(),
        "status": status,
        "phase": phase,
        "error": error,
        "backup_dir": str(backup_dir),
        "runtime_torrent_path": runtime_torrent_path,
        "target_directory": target_directory,
        "normalized_target_directory": normalized_target,
        "expected_loaded_directory": expected_loaded_directory,
        "completed": completed,
        "recovery_completed": recovery_completed,
    }


def fetch_rt_status_rows(rpc_url: str = DEFAULT_RT_RPC_URL) -> list[dict]:
    xml = rt_xmlrpc_call(
        "d.multicall2",
        "",
        "main",
        "d.hash=",
        "d.name=",
        "d.directory=",
        "d.state=",
        "d.hashing=",
        "d.complete=",
        "d.down.rate=",
        "d.up.rate=",
        "d.message=",
        rpc_url=rpc_url,
        timeout=20,
    )
    rows: list[dict] = []
    for torrent_block in re.findall(r"<array>\s*<data>(.*?)</data>\s*</array>", xml, re.DOTALL):
        values = []
        for value in re.findall(r"<value>(.*?)</value>", torrent_block, re.DOTALL):
            match = re.search(r"<(?:i4|i8|int)>(\d+)</(?:i4|i8|int)>", value)
            if match:
                values.append(int(match.group(1)))
                continue
            match = re.search(r"<string>(.*?)</string>", value, re.DOTALL)
            values.append(match.group(1) if match else re.sub(r"<[^>]+>", "", value).strip())
        if len(values) < 8:
            continue
        hash_, name, directory, state, hashing, complete, down_rate, up_rate, message = values[:9]
        if hashing > 0:
            derived = "checking"
        elif str(message).strip():
            derived = "error"
        elif state == 0:
            derived = "stoppedUP" if complete == 1 else "stoppedDL"
        elif complete == 0:
            derived = "downloading" if down_rate > 0 else "stalledDL"
        else:
            derived = "uploading" if up_rate > 0 else "stalledUP"
        rows.append(
            {
                "hash": str(hash_).lower(),
                "name": str(name),
                "directory": str(directory),
                "state": derived,
                "message": str(message),
            }
        )
    return rows
