"""
Torrent piece-hash verification using .torrent bencode metadata.

Reads piece hashes directly from the .torrent file and verifies each piece
against bytes on disk — independently of qBittorrent or rTorrent rechecks.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

from .bencode import bencode_decode


@dataclass
class TorrentFileEntry:
    rel_path: Path      # path relative to base_dir (includes info_name for multi-file)
    length: int


@dataclass
class PieceFileSpan:
    rel_path: str
    abs_path: str
    file_offset_start: int
    file_offset_end: int
    piece_offset_start: int
    piece_offset_end: int
    exists: bool
    size: int | None
    kind: str


@dataclass
class SpanComparison:
    rel_path: str
    kind: str
    file_offset_start: int
    file_offset_end: int
    primary_path: str
    compare_path: str
    primary_exists: bool
    compare_exists: bool
    primary_size: int | None
    compare_size: int | None
    primary_sha256: str | None
    compare_sha256: str | None
    verdict: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class PieceDiagnostic:
    piece_index: int
    status: str
    classification: str
    byte_start: int
    byte_end: int
    spans: list[PieceFileSpan] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    span_comparisons: list[SpanComparison] = field(default_factory=list)
    comparison_classification: str | None = None

    def to_dict(self) -> dict:
        return {
            "piece_index": self.piece_index,
            "status": self.status,
            "classification": self.classification,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "spans": [span.__dict__ for span in self.spans],
            "missing_files": list(self.missing_files),
            "span_comparisons": [span.to_dict() for span in self.span_comparisons],
            "comparison_classification": self.comparison_classification,
        }


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
    failed_pieces: list[PieceDiagnostic] = field(default_factory=list)
    compare_root: str | None = None

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


MEDIA_EXTENSIONS = {
    ".avi",
    ".m2ts",
    ".m4v",
    ".mka",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
}

SIDECAR_EXTENSIONS = {
    ".ass",
    ".cue",
    ".idx",
    ".jpg",
    ".jpeg",
    ".log",
    ".nfo",
    ".png",
    ".srt",
    ".sub",
    ".txt",
}


def _file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MEDIA_EXTENSIONS:
        return "media"
    if suffix in SIDECAR_EXTENSIONS:
        return "sidecar"
    return "other"


def _path_for_entry(base_dir: Path, entry: TorrentFileEntry, *, content_root: Path | None) -> Path:
    if content_root is None:
        return base_dir / entry.rel_path
    parts = entry.rel_path.parts
    if len(parts) > 1:
        return content_root.joinpath(*parts[1:])
    return content_root


def _path_for_rel_path(base_dir: Path, rel_path: str, *, content_root: Path | None) -> Path:
    rel = Path(rel_path)
    if content_root is None:
        return base_dir / rel
    parts = rel.parts
    if len(parts) > 1:
        return content_root.joinpath(*parts[1:])
    return content_root


def _hash_file_range(path: Path, start: int, end: int) -> tuple[str | None, bool, int | None, str | None]:
    try:
        size = path.stat().st_size
    except OSError:
        return None, False, None, "missing"
    if size < end:
        return None, True, size, "truncated"
    h = hashlib.sha256()
    remaining = end - start
    try:
        with path.open("rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(1024 * 1024, remaining))
                if not chunk:
                    return None, True, size, "truncated"
                h.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return None, True, size, "unreadable"
    return h.hexdigest(), True, size, None


def _compare_span(
    span: PieceFileSpan,
    base_dir: Path,
    content_root: Path | None,
    compare_root: Path,
) -> SpanComparison:
    primary_path = Path(span.abs_path)
    compare_path = _path_for_rel_path(base_dir, span.rel_path, content_root=compare_root)
    primary_sha, primary_exists, primary_size, primary_err = _hash_file_range(
        primary_path, span.file_offset_start, span.file_offset_end
    )
    compare_sha, compare_exists, compare_size, compare_err = _hash_file_range(
        compare_path, span.file_offset_start, span.file_offset_end
    )
    if primary_err and compare_err:
        verdict = f"primary-{primary_err}_compare-{compare_err}"
    elif primary_err:
        verdict = f"primary-{primary_err}"
    elif compare_err:
        verdict = f"compare-{compare_err}"
    elif primary_sha == compare_sha:
        verdict = "same"
    else:
        verdict = "different"
    return SpanComparison(
        rel_path=span.rel_path,
        kind=span.kind,
        file_offset_start=span.file_offset_start,
        file_offset_end=span.file_offset_end,
        primary_path=str(primary_path),
        compare_path=str(compare_path),
        primary_exists=primary_exists,
        compare_exists=compare_exists,
        primary_size=primary_size,
        compare_size=compare_size,
        primary_sha256=primary_sha,
        compare_sha256=compare_sha,
        verdict=verdict,
    )


def _classify_comparisons(comparisons: list[SpanComparison]) -> str:
    if not comparisons:
        return "unresolved"
    missing = [c for c in comparisons if c.verdict != "same" and "missing" in c.verdict]
    truncated = [c for c in comparisons if c.verdict != "same" and "truncated" in c.verdict]
    unreadable = [c for c in comparisons if c.verdict != "same" and "unreadable" in c.verdict]
    diffs = [c for c in comparisons if c.verdict == "different"]
    if not diffs and not missing and not truncated and not unreadable:
        return "no_span_diff"
    if missing and not diffs and not truncated and not unreadable:
        return "missing_only"
    if truncated and not diffs:
        return "truncated_only"
    if unreadable and not diffs:
        return "unreadable_only"
    diff_kinds = {c.kind for c in diffs}
    if diff_kinds == {"sidecar"}:
        return "sidecar_only_diff"
    if diff_kinds == {"media"}:
        return "media_only_diff"
    if "sidecar" in diff_kinds and "media" in diff_kinds:
        return "sidecar_and_media_diff"
    if "media" in diff_kinds:
        return "media_and_other_diff"
    if "sidecar" in diff_kinds:
        return "sidecar_and_other_diff"
    return "non_media_diff"


def _classify_piece(status: str, spans: list[PieceFileSpan]) -> str:
    kinds = {span.kind for span in spans}
    if "media" in kinds and ("sidecar" in kinds or "other" in kinds):
        return "sidecar_media_boundary_piece"
    if "media" in kinds:
        return "media_piece_missing_or_truncated" if status == "missing" else "media_piece_mismatch"
    if kinds == {"sidecar"}:
        return "sidecar_only_missing" if status == "missing" else "sidecar_piece_mismatch"
    if status == "missing":
        return "layout_missing"
    return "non_media_piece_mismatch"


def _piece_stream(
    entries: list[TorrentFileEntry],
    base_dir: Path,
    piece_length: int,
    *,
    content_root: Path | None = None,
) -> Iterator[tuple[bytes, list[str], list[PieceFileSpan]]]:
    """
    Yield (piece_bytes, missing_files) for each piece.

    Reads the virtual concatenated file stream in piece_length chunks.
    If a file is missing or unreadable, its bytes are zeros and its path
    is added to missing_files for that piece.
    """
    buf = bytearray()
    missing_this_piece: list[str] = []
    spans_this_piece: list[PieceFileSpan] = []

    def flush_piece() -> tuple[bytes, list[str], list[PieceFileSpan]]:
        data = bytes(buf[:piece_length])
        m = list(missing_this_piece)
        spans = list(spans_this_piece)
        return data, m, spans

    for entry in entries:
        fpath = _path_for_entry(base_dir, entry, content_root=content_root)
        remaining = entry.length
        file_offset = 0
        try:
            fh = open(fpath, "rb")
        except OSError:
            missing_this_piece.append(str(fpath))
            # Fill with zeros for missing file
            while remaining > 0:
                space = piece_length - len(buf)
                chunk = min(space, remaining)
                size = fpath.stat().st_size if fpath.exists() else None
                spans_this_piece.append(
                    PieceFileSpan(
                        rel_path=str(entry.rel_path),
                        abs_path=str(fpath),
                        file_offset_start=file_offset,
                        file_offset_end=file_offset + chunk,
                        piece_offset_start=len(buf),
                        piece_offset_end=len(buf) + chunk,
                        exists=fpath.exists(),
                        size=size,
                        kind=_file_kind(entry.rel_path),
                    )
                )
                buf.extend(b"\x00" * chunk)
                file_offset += chunk
                remaining -= chunk
                if len(buf) >= piece_length:
                    yield flush_piece()
                    buf = bytearray()
                    spans_this_piece = []
                    missing_this_piece = [str(fpath)] if remaining > 0 else []
            continue

        with fh:
            while remaining > 0:
                space = piece_length - len(buf)
                want = min(space, remaining)
                size = fpath.stat().st_size if fpath.exists() else None
                spans_this_piece.append(
                    PieceFileSpan(
                        rel_path=str(entry.rel_path),
                        abs_path=str(fpath),
                        file_offset_start=file_offset,
                        file_offset_end=file_offset + want,
                        piece_offset_start=len(buf),
                        piece_offset_end=len(buf) + want,
                        exists=fpath.exists(),
                        size=size,
                        kind=_file_kind(entry.rel_path),
                    )
                )
                chunk = fh.read(want)
                if not chunk:
                    # Truncated file — fill remainder with zeros
                    missing_this_piece.append(str(fpath))
                    buf.extend(b"\x00" * want)
                    remaining -= want
                    file_offset += want
                else:
                    buf.extend(chunk)
                    remaining -= len(chunk)
                    file_offset += len(chunk)
                if len(buf) >= piece_length:
                    yield flush_piece()
                    buf = bytearray()
                    spans_this_piece = []
                    missing_this_piece = []

    # Last (possibly short) piece
    if buf:
        yield bytes(buf), list(missing_this_piece), list(spans_this_piece)


def verify_torrent_pieces(
    torrent_path: Path,
    base_dir: Path,
    *,
    content_root: Path | None = None,
    compare_root: Path | None = None,
    collect_piece_details: bool = False,
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
    result.compare_root = str(compare_root) if compare_root is not None else None

    all_missing: set[str] = set()

    total_size = sum(entry.length for entry in entries)

    for idx, (piece_bytes, missing_files, spans) in enumerate(
        _piece_stream(entries, base_dir, piece_length, content_root=content_root)
    ):
        expected = piece_hashes[idx]
        byte_start = idx * piece_length
        byte_end = min(byte_start + len(piece_bytes), total_size)
        if missing_files:
            result.pieces_missing += 1
            for f in missing_files:
                if f not in all_missing:
                    all_missing.add(f)
                    result.files_missing.append(f)
            if collect_piece_details:
                diagnostic = PieceDiagnostic(
                    piece_index=idx,
                    status="missing",
                    classification=_classify_piece("missing", spans),
                    byte_start=byte_start,
                    byte_end=byte_end,
                    spans=spans,
                    missing_files=list(dict.fromkeys(missing_files)),
                )
                if compare_root is not None:
                    diagnostic.span_comparisons = [
                        _compare_span(span, base_dir, content_root, compare_root)
                        for span in spans
                    ]
                    diagnostic.comparison_classification = _classify_comparisons(
                        diagnostic.span_comparisons
                    )
                result.failed_pieces.append(diagnostic)
        else:
            actual = hashlib.sha1(piece_bytes).digest()
            if actual == expected:
                result.pieces_ok += 1
            else:
                result.pieces_fail += 1
                if collect_piece_details:
                    diagnostic = PieceDiagnostic(
                        piece_index=idx,
                        status="mismatch",
                        classification=_classify_piece("mismatch", spans),
                        byte_start=byte_start,
                        byte_end=byte_end,
                        spans=spans,
                    )
                    if compare_root is not None:
                        diagnostic.span_comparisons = [
                            _compare_span(span, base_dir, content_root, compare_root)
                            for span in spans
                        ]
                        diagnostic.comparison_classification = _classify_comparisons(
                            diagnostic.span_comparisons
                        )
                    result.failed_pieces.append(diagnostic)

        if progress_cb:
            progress_cb(idx + 1, piece_count)

    return result


def result_to_dict(result: TorrentVerifyResult) -> dict:
    return {
        "success": result.success,
        "torrent_path": result.torrent_path,
        "base_dir": result.base_dir,
        "info_name": result.info_name,
        "is_multi_file": result.is_multi_file,
        "piece_length": result.piece_length,
        "piece_count": result.piece_count,
        "pieces_ok": result.pieces_ok,
        "pieces_fail": result.pieces_fail,
        "pieces_missing": result.pieces_missing,
        "files_missing": list(result.files_missing),
        "failed_pieces": [piece.to_dict() for piece in result.failed_pieces],
        "compare_root": result.compare_root,
    }


def result_to_json(result: TorrentVerifyResult) -> str:
    return json.dumps(result_to_dict(result), indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Folder-depth / layout verification
# ---------------------------------------------------------------------------

@dataclass
class LayoutFileStatus:
    expected: str           # path torrent expects (relative to base_dir)
    length: int
    found: bool             # file exists at expected path
    actual: Optional[str]   # actual path on disk if found elsewhere (wrong depth)


@dataclass
class LayoutVerifyResult:
    torrent_path: str
    base_dir: str
    info_name: str
    is_multi_file: bool
    files_expected: int = 0
    files_ok: int = 0           # present at expected path
    files_missing: int = 0      # not found anywhere
    files_wrong_depth: int = 0  # found but at a different path
    entries: list[LayoutFileStatus] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.files_missing == 0 and self.files_wrong_depth == 0


def _search_for_file(filename: str, search_root: Path, max_depth: int = 6) -> Optional[Path]:
    """Search for a file by name under search_root up to max_depth levels."""
    try:
        for p in search_root.rglob(filename):
            if p.is_file():
                # Check depth from search_root
                try:
                    rel = p.relative_to(search_root)
                    if len(rel.parts) <= max_depth:
                        return p
                except ValueError:
                    pass
    except (PermissionError, OSError):
        pass
    return None


def verify_layout(
    torrent_path: Path,
    base_dir: Path,
) -> LayoutVerifyResult:
    """
    Verify that files on disk are at the exact paths the .torrent defines.

    Parses info_name and info.files[].path from the bencode to compute each
    file's expected location relative to base_dir, then checks existence.
    If a file is missing from its expected path, searches nearby for it to
    detect wrong-depth placement.
    """
    info, _ = _parse_torrent(torrent_path)
    info_name = (info.get(b"name") or b"").decode("utf-8", errors="replace")
    is_multi_file = b"files" in info
    entries = _file_entries(info, info_name, is_multi_file)

    result = LayoutVerifyResult(
        torrent_path=str(torrent_path),
        base_dir=str(base_dir),
        info_name=info_name,
        is_multi_file=is_multi_file,
        files_expected=len(entries),
    )

    for entry in entries:
        expected_abs = base_dir / entry.rel_path
        status = LayoutFileStatus(
            expected=str(entry.rel_path),
            length=entry.length,
            found=False,
            actual=None,
        )

        if expected_abs.is_file():
            status.found = True
            result.files_ok += 1
        else:
            # Search for the file near base_dir to detect wrong-depth placement
            filename = expected_abs.name
            found_at = _search_for_file(filename, base_dir)
            if found_at is not None:
                try:
                    status.actual = str(found_at.relative_to(base_dir))
                except ValueError:
                    status.actual = str(found_at)
                result.files_wrong_depth += 1
            else:
                result.files_missing += 1

        result.entries.append(status)

    return result


def format_layout_result(result: LayoutVerifyResult) -> str:
    verdict = "PASS" if result.success else "FAIL"
    lines = [
        f"Layout Verify: {verdict}",
        f"  torrent:   {result.torrent_path}",
        f"  base_dir:  {result.base_dir}",
        f"  info_name: {result.info_name}",
        f"  type:      {'multi-file' if result.is_multi_file else 'single-file'}",
        f"  files:     {result.files_expected} expected  "
        f"{result.files_ok} ok  "
        f"{result.files_wrong_depth} wrong-depth  "
        f"{result.files_missing} missing",
    ]
    for s in result.entries:
        if s.found:
            lines.append(f"  ✓  {s.expected}")
        elif s.actual is not None:
            lines.append(f"  ✗  {s.expected}  [wrong depth — found at: {s.actual}]")
        else:
            lines.append(f"  ✗  {s.expected}  [not found]")
    return "\n".join(lines)


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
    if result.failed_pieces:
        lines.append("  failed pieces:")
        for piece in result.failed_pieces:
            lines.append(
                f"    piece={piece.piece_index} status={piece.status} "
                f"class={piece.classification} bytes={piece.byte_start}-{piece.byte_end}"
            )
            if piece.comparison_classification:
                lines.append(f"      comparison={piece.comparison_classification}")
            for span in piece.spans:
                lines.append(
                    f"      {span.kind} {span.rel_path} "
                    f"file_bytes={span.file_offset_start}-{span.file_offset_end} "
                    f"exists={span.exists} size={span.size}"
                )
            for comp in piece.span_comparisons:
                lines.append(
                    f"      compare {comp.kind} {comp.rel_path} "
                    f"file_bytes={comp.file_offset_start}-{comp.file_offset_end} "
                    f"verdict={comp.verdict} "
                    f"primary_sha256={comp.primary_sha256} compare_sha256={comp.compare_sha256}"
                )
    return "\n".join(lines)
