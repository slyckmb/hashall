"""Helpers for reading and patching qBittorrent .fastresume files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable

from hashall.bencode import BencodeDecoder, as_text, bencode_decode, bencode_encode


class Bencode(BencodeDecoder):
    """Backward-compatible shim for older fastresume callers."""

    def parse(self) -> Any:
        return self.decode()


def bencode(value: Any) -> bytes:
    """Backward-compatible alias for the canonical encoder."""

    return bencode_encode(value)


@dataclass(frozen=True)
class FastresumePatchResult:
    changed: bool
    fastresume_path: str
    backup_path: str
    save_path: str
    qbt_save_path: str
    qbt_download_path: str
    old_save_path: str
    old_qbt_save_path: str
    old_qbt_download_path: str
    new_save_path: str
    new_qbt_save_path: str
    new_qbt_download_path: str


def normalize_save_path(path: str) -> str:
    """Normalize qB save_path values before writing them back."""

    raw = str(path or "").strip()
    if not raw:
        raise ValueError("save_path_required")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise ValueError(f"save_path_must_be_absolute path={raw!r}")
    normalized = candidate.as_posix()
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized


def _path_is_same_or_child(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def validate_qb_target_save_path(
    target_save_path: str,
    *,
    approved_roots: Iterable[str],
) -> str:
    """Validate a qB target save path before setLocation or fastresume patching."""

    normalized = normalize_save_path(target_save_path)
    if normalized == "/tmp" or normalized.startswith("/tmp/"):
        raise ValueError(f"qb_target_save_path_disallowed path={normalized}")
    if normalized == "/var/tmp" or normalized.startswith("/var/tmp/"):
        raise ValueError(f"qb_target_save_path_disallowed path={normalized}")

    roots = []
    seen = set()
    for raw_root in approved_roots:
        root = str(raw_root or "").strip()
        if not root:
            continue
        normalized_root = normalize_save_path(root)
        if normalized_root in seen:
            continue
        seen.add(normalized_root)
        roots.append(normalized_root)
    if not roots:
        raise ValueError("qb_target_save_path_no_approved_roots")
    if not any(_path_is_same_or_child(normalized, root) for root in roots):
        raise ValueError(
            "qb_target_save_path_outside_approved_roots "
            f"path={normalized} approved_roots={','.join(roots)}"
        )
    return normalized


def read_fastresume(path: Path) -> Dict[bytes, Any]:
    """Read and decode a fastresume payload."""

    raw = path.read_bytes()
    doc = bencode_decode(raw)
    if not isinstance(doc, dict):
        raise ValueError("invalid_fastresume_dict")
    return doc


_DEFAULT_APPROVED_ROOTS = (
    "/data/media/torrents/seeding",
    "/pool/media/torrents/seeding",
)


def patch_fastresume_file(
    path: Path,
    target_save_path: str,
    backup_suffix: str,
    *,
    approved_roots: Iterable[str] = _DEFAULT_APPROVED_ROOTS,
) -> FastresumePatchResult:
    raw = path.read_bytes()
    doc = bencode_decode(raw)
    if not isinstance(doc, dict):
        raise ValueError("invalid_fastresume_dict")

    old_save_path = as_text(doc.get(b"save_path", b"")).strip()
    old_qbt_save = as_text(doc.get(b"qBt-savePath", b"")).strip()
    old_download_path = as_text(doc.get(b"qBt-downloadPath", b"")).strip()

    changed = False
    target_text = validate_qb_target_save_path(target_save_path, approved_roots=approved_roots)
    target_b = target_text.encode("utf-8")
    if doc.get(b"save_path") != target_b:
        doc[b"save_path"] = target_b
        changed = True
    if doc.get(b"qBt-savePath") != target_b:
        doc[b"qBt-savePath"] = target_b
        changed = True
    if b"qBt-downloadPath" in doc:
        del doc[b"qBt-downloadPath"]
        changed = True

    if changed:
        backup = path.with_name(path.name + backup_suffix)
        if not backup.exists():
            backup.write_bytes(raw)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(bencode_encode(doc))
        import os
        os.replace(tmp, path)
    else:
        backup = path.with_name(path.name + backup_suffix)

    return FastresumePatchResult(
        changed=changed,
        fastresume_path=str(path),
        backup_path=str(backup) if changed else "",
        save_path=old_save_path,
        qbt_save_path=old_qbt_save,
        qbt_download_path=old_download_path,
        old_save_path=old_save_path,
        old_qbt_save_path=old_qbt_save,
        old_qbt_download_path=old_download_path,
        new_save_path=target_text,
        new_qbt_save_path=target_text,
        new_qbt_download_path="",
    )
