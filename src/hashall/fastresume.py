"""Helpers for reading and patching qBittorrent .fastresume files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


class Bencode:
    def __init__(self, blob: bytes):
        self.blob = blob
        self.i = 0

    def parse(self) -> Any:
        c = self.blob[self.i : self.i + 1]
        if c == b"i":
            self.i += 1
            j = self.blob.index(b"e", self.i)
            n = int(self.blob[self.i : j])
            self.i = j + 1
            return n
        if c == b"l":
            self.i += 1
            out: List[Any] = []
            while self.blob[self.i : self.i + 1] != b"e":
                out.append(self.parse())
            self.i += 1
            return out
        if c == b"d":
            self.i += 1
            out: Dict[bytes, Any] = {}
            while self.blob[self.i : self.i + 1] != b"e":
                k = self.parse()
                v = self.parse()
                out[k] = v
            self.i += 1
            return out
        j = self.blob.index(b":", self.i)
        n = int(self.blob[self.i : j])
        self.i = j + 1
        s = self.blob[self.i : self.i + n]
        self.i += n
        return s


def bencode(value: Any) -> bytes:
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, str):
        data = value.encode("utf-8")
        return str(len(data)).encode("ascii") + b":" + data
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items: List[bytes] = []
        for k in sorted(
            value.keys(), key=lambda x: x if isinstance(x, bytes) else str(x).encode("utf-8")
        ):
            kb = k if isinstance(k, bytes) else str(k).encode("utf-8")
            items.append(bencode(kb))
            items.append(bencode(value[k]))
        return b"d" + b"".join(items) + b"e"
    raise TypeError(f"Unsupported type for bencode: {type(value)!r}")


def as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    return str(value)


@dataclass(frozen=True)
class FastresumePatchResult:
    changed: bool
    save_path: str
    qbt_save_path: str
    qbt_download_path: str


def patch_fastresume_file(path: Path, target_save_path: str, backup_suffix: str) -> FastresumePatchResult:
    raw = path.read_bytes()
    doc = Bencode(raw).parse()
    if not isinstance(doc, dict):
        raise ValueError("invalid_fastresume_dict")

    old_save_path = as_text(doc.get(b"save_path", b"")).strip()
    old_qbt_save = as_text(doc.get(b"qBt-savePath", b"")).strip()
    old_download_path = as_text(doc.get(b"qBt-downloadPath", b"")).strip()

    changed = False
    target_b = str(target_save_path).rstrip("/").encode("utf-8")
    if doc.get(b"save_path") != target_b:
        doc[b"save_path"] = target_b
        changed = True
    if doc.get(b"qBt-savePath") != target_b:
        doc[b"qBt-savePath"] = target_b
        changed = True
    if doc.get(b"qBt-downloadPath", b"") != b"":
        doc[b"qBt-downloadPath"] = b""
        changed = True

    if changed:
        backup = path.with_name(path.name + backup_suffix)
        if not backup.exists():
            backup.write_bytes(raw)
        path.write_bytes(bencode(doc))

    return FastresumePatchResult(
        changed=changed,
        save_path=old_save_path,
        qbt_save_path=old_qbt_save,
        qbt_download_path=old_download_path,
    )
