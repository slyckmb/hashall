"""Helpers for completion-aware payload filtering using qBittorrent state."""

from __future__ import annotations

from typing import Optional

QBIT_COMPLETE_PROGRESS = 0.999999


def load_completed_torrent_hashes(
    qbit_url: Optional[str] = None,
    qbit_user: Optional[str] = None,
    qbit_pass: Optional[str] = None,
) -> tuple[set[str], bool, str | None]:
    """Return completed torrent hashes from qB; disable filtering if unavailable."""
    try:
        from hashall.qbittorrent import get_qbittorrent_client
    except Exception as exc:
        return set(), False, f"qB client import failed: {exc}"

    qbit = get_qbittorrent_client(qbit_url, qbit_user, qbit_pass)
    if not qbit.test_connection():
        return set(), False, f"qB unreachable: {qbit.last_error or 'connection failed'}"
    if not qbit.login():
        return set(), False, f"qB login failed: {qbit.last_error or 'authentication failed'}"

    torrents = qbit.get_torrents()
    completed = {
        str(t.hash).lower()
        for t in torrents
        if t.hash and float(t.progress or 0.0) >= QBIT_COMPLETE_PROGRESS
    }
    return completed, True, None
