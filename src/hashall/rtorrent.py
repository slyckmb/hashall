from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hashall.bencode import bencode_decode
from hashall.pathing import canonicalize_path


DEFAULT_RT_SESSION_DIR = Path("/dump/docker/gluetun_qbit/rtorrent_vpn/.session")


@dataclass(frozen=True)
class RTSessionEntry:
    torrent_hash: str
    directory: str


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
        out[stem] = RTSessionEntry(torrent_hash=stem, directory=directory)
    return out


def live_rt_root_paths(session_dir: Path = DEFAULT_RT_SESSION_DIR) -> frozenset[str]:
    return frozenset(
        entry.directory
        for entry in load_rt_session_directories(session_dir).values()
        if entry.directory
    )
