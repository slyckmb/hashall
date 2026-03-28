from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import requests
import re

from hashall.bencode import bencode_decode
from hashall.pathing import canonicalize_path


DEFAULT_RT_SESSION_DIR = Path("/dump/docker/gluetun_qbit/rtorrent_vpn/.session")
DEFAULT_RT_RPC_URL = "http://127.0.0.1:18000/"


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


def _xml_escape(value: str) -> str:
    text = str(value)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def rt_xmlrpc_call(method: str, *args: str, rpc_url: str = DEFAULT_RT_RPC_URL, timeout: int = 20) -> str:
    params = "".join(
        f"<param><value><string>{_xml_escape(arg)}</string></value></param>"
        for arg in args
    )
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
    return response.text


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
    return RTTorrentMeta(
        torrent_hash=str(torrent_hash).lower(),
        info_name=info_name,
        is_multi_file=isinstance(info.get(b"files"), list),
    )


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
        if path.name == torrent_meta.info_name and path.parent != path:
            path = path.parent
    try:
        return str(canonicalize_path(path))
    except Exception:
        return str(path)


def rt_apply_directory_repoint(
    torrent_hash: str,
    target_directory: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
) -> list[str]:
    calls = [
        ("d.stop", torrent_hash),
        ("d.close", torrent_hash),
        ("d.directory.set", torrent_hash, target_directory),
        ("d.save_full_session", torrent_hash),
        ("session.save",),
        ("d.open", torrent_hash),
        ("d.start", torrent_hash),
    ]
    completed: list[str] = []
    try:
        for method, *args in calls:
            rt_xmlrpc_call(method, *args, rpc_url=rpc_url)
            completed.append(method)
    except Exception:
        try:
            rt_xmlrpc_call("d.start", torrent_hash, rpc_url=rpc_url)
        except Exception:
            pass
        raise
    return completed


def rt_recheck_torrent(
    torrent_hash: str,
    *,
    rpc_url: str = DEFAULT_RT_RPC_URL,
) -> list[str]:
    calls = [
        ("d.stop", torrent_hash),
        ("d.close", torrent_hash),
        ("d.check_hash", torrent_hash),
        ("d.open", torrent_hash),
        ("d.start", torrent_hash),
    ]
    completed: list[str] = []
    try:
        for method, *args in calls:
            rt_xmlrpc_call(method, *args, rpc_url=rpc_url)
            completed.append(method)
    except Exception:
        try:
            rt_xmlrpc_call("d.start", torrent_hash, rpc_url=rpc_url)
        except Exception:
            pass
        raise
    return completed


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
