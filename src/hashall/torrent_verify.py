"""
Torrent piece-hash verification using .torrent bencode metadata.

Reads piece hashes directly from the .torrent file and verifies each piece
against bytes on disk — independently of qBittorrent or rTorrent rechecks.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

from .bencode import bencode_decode


@dataclass
class TorrentFileEntry:
    rel_path: Path      # path relative to base_dir (includes info_name for multi-file)
    length: int


@dataclass
class TorrentVerifyResult:
    torrent_path: str
    base_dir: str
    info_name: str
    is_multi_file: bool
    piece_length: int
    piece_count: int
    pieces_ok: int = 0
    pieces_fail: int = 0
    pieces_missing: int = 0   # piece spans a file that couldn't be opened
    files_missing: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.pieces_fail == 0 and self.pieces_missing == 0

    @property
    def summary(self) -> str:
        pct = f"{self.pieces_ok / self.piece_count * 100:.1f}%" if self.piece_count else "n/a"
        return (
            f"pieces={self.piece_count} ok={self.pieces_ok} "
            f"fail={self.pieces_fail} missing={self.pieces_missing} ({pct})"
        )


def _parse_torrent(torrent_path: Path) -> tuple[dict, bytes]:
    raw = torrent_path.read_bytes()
    doc = bencode_decode(raw)
    if not isinstance(doc, dict):
        raise ValueError(f"not a bencoded dict: {torrent_path}")
    info = doc.get(b"info")
    if not isinstance(info, dict):
        raise ValueError(f"missing info dict: {torrent_path}")
    return info, raw


def _file_entries(info: dict, info_name: str, is_multi_file: bool) -> list[TorrentFileEntry]:
    if is_multi_file:
        entries = []
        for f in info.get(b"files", []):
            path_parts = [
                p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p)
                for p in (f.get(b"path") or [])
            ]
            length = int(f.get(b"length") or 0)
            rel = Path(info_name).joinpath(*path_parts)
            entries.append(TorrentFileEntry(rel_path=rel, length=length))
        return entries
    else:
        length = int(info.get(b"length") or 0)
        return [TorrentFileEntry(rel_path=Path(info_name), length=length)]


def _piece_stream(
    entries: list[TorrentFileEntry],
    base_dir: Path,
    piece_length: int,
) -> Iterator[tuple[bytes, list[str]]]:
    """
    Yield (piece_bytes, missing_files) for each piece.

    Reads the virtual concatenated file stream in piece_length chunks.
    If a file is missing or unreadable, its bytes are zeros and its path
    is added to missing_files for that piece.
    """
    buf = bytearray()
    missing: list[str] = []
    missing_this_piece: list[str] = []

    def flush_piece() -> tuple[bytes, list[str]]:
        data = bytes(buf[:piece_length])
        m = list(missing_this_piece)
        return data, m

    for entry in entries:
        fpath = base_dir / entry.rel_path
        remaining = entry.length
        try:
            fh = open(fpath, "rb")
        except OSError:
            missing_this_piece.append(str(fpath))
            # Fill with zeros for missing file
            while remaining > 0:
                space = piece_length - len(buf)
                chunk = min(space, remaining)
                buf.extend(b"\x00" * chunk)
                remaining -= chunk
                if len(buf) >= piece_length:
                    yield flush_piece()
                    buf = bytearray()
                    missing_this_piece = []
                    if str(fpath) not in missing_this_piece:
                        pass  # already recorded above
            continue

        with fh:
            while remaining > 0:
                space = piece_length - len(buf)
                want = min(space, remaining)
                chunk = fh.read(want)
                if not chunk:
                    # Truncated file — fill remainder with zeros
                    missing_this_piece.append(str(fpath))
                    buf.extend(b"\x00" * want)
                    remaining -= want
                else:
                    buf.extend(chunk)
                    remaining -= len(chunk)
                if len(buf) >= piece_length:
                    yield flush_piece()
                    buf = bytearray()
                    missing_this_piece = []

    # Last (possibly short) piece
    if buf:
        yield bytes(buf), list(missing_this_piece)


def verify_torrent_pieces(
    torrent_path: Path,
    base_dir: Path,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> TorrentVerifyResult:
    """
    Verify torrent piece hashes against files in base_dir.

    base_dir is the directory ABOVE the torrent root (= save_path):
      - multi-file: files at base_dir / info_name / file_paths
      - single-file: file at base_dir / info_name

    progress_cb(piece_idx, piece_count) called after each piece if provided.
    """
    info, _ = _parse_torrent(torrent_path)

    info_name = (info.get(b"name") or b"").decode("utf-8", errors="replace")
    is_multi_file = b"files" in info

    raw_pieces = info.get(b"pieces", b"")
    if not isinstance(raw_pieces, bytes) or len(raw_pieces) % 20:
        raise ValueError(f"malformed pieces field: {torrent_path}")

    piece_length = int(info.get(b"piece length") or 0)
    if not piece_length:
        raise ValueError(f"missing piece length: {torrent_path}")

    piece_hashes = [raw_pieces[i : i + 20] for i in range(0, len(raw_pieces), 20)]
    piece_count = len(piece_hashes)

    entries = _file_entries(info, info_name, is_multi_file)

    result = TorrentVerifyResult(
        torrent_path=str(torrent_path),
        base_dir=str(base_dir),
        info_name=info_name,
        is_multi_file=is_multi_file,
        piece_length=piece_length,
        piece_count=piece_count,
    )

    all_missing: set[str] = set()

    for idx, (piece_bytes, missing_files) in enumerate(_piece_stream(entries, base_dir, piece_length)):
        expected = piece_hashes[idx]
        if missing_files:
            result.pieces_missing += 1
            for f in missing_files:
                if f not in all_missing:
                    all_missing.add(f)
                    result.files_missing.append(f)
        else:
            actual = hashlib.sha1(piece_bytes).digest()
            if actual == expected:
                result.pieces_ok += 1
            else:
                result.pieces_fail += 1

        if progress_cb:
            progress_cb(idx + 1, piece_count)

    return result


def format_verify_result(result: TorrentVerifyResult) -> str:
    lines = [
        f"Torrent Verify: {'PASS' if result.success else 'FAIL'}",
        f"  torrent:     {result.torrent_path}",
        f"  base_dir:    {result.base_dir}",
        f"  info_name:   {result.info_name}",
        f"  type:        {'multi-file' if result.is_multi_file else 'single-file'}",
        f"  piece_length:{result.piece_length // 1024 // 1024} MiB",
        f"  {result.summary}",
    ]
    if result.files_missing:
        lines.append("  missing files:")
        for f in result.files_missing:
            lines.append(f"    {f}")
    return "\n".join(lines)
