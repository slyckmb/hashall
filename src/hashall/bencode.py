"""Canonical bencode parser/encoder for hashall tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


class BencodeError(ValueError):
    """Base error for malformed bencode payloads."""


class TrailingDataError(BencodeError):
    """Raised when bytes remain after a full decode."""


class UnexpectedEOFError(BencodeError):
    """Raised when the payload ends before the value does."""


class InvalidTokenError(BencodeError):
    """Raised when the payload contains an invalid token."""


class BencodeDecoder:
    """Stateful bencode decoder with strict full-consumption checks."""

    def __init__(self, blob: bytes):
        self._blob = blob
        self._index = 0

    def decode(self) -> Any:
        value = self._parse()
        if self._index != len(self._blob):
            raise TrailingDataError(
                f"trailing_data offset={self._index} total={len(self._blob)}"
            )
        return value

    def _parse(self) -> Any:
        token = self._peek()
        if token == b"i":
            return self._parse_int()
        if token == b"l":
            return self._parse_list()
        if token == b"d":
            return self._parse_dict()
        if token and token.isdigit():
            return self._parse_bytes()
        raise InvalidTokenError(f"invalid_token offset={self._index} token={token!r}")

    def _peek(self) -> bytes:
        if self._index >= len(self._blob):
            raise UnexpectedEOFError(f"unexpected_eof offset={self._index}")
        return self._blob[self._index : self._index + 1]

    def _parse_int(self) -> int:
        self._index += 1
        end = self._blob.find(b"e", self._index)
        if end < 0:
            raise UnexpectedEOFError(f"unterminated_integer offset={self._index}")
        raw = self._blob[self._index : end]
        if not raw:
            raise InvalidTokenError(f"empty_integer offset={self._index}")
        if raw == b"-0" or (raw.startswith(b"0") and raw != b"0") or raw.startswith(b"-0"):
            raise InvalidTokenError(f"invalid_integer offset={self._index} value={raw!r}")
        try:
            value = int(raw)
        except ValueError as exc:
            raise InvalidTokenError(
                f"invalid_integer offset={self._index} value={raw!r}"
            ) from exc
        self._index = end + 1
        return value

    def _parse_list(self) -> List[Any]:
        self._index += 1
        out: List[Any] = []
        while True:
            token = self._peek()
            if token == b"e":
                self._index += 1
                return out
            out.append(self._parse())

    def _parse_dict(self) -> Dict[bytes, Any]:
        self._index += 1
        out: Dict[bytes, Any] = {}
        while True:
            token = self._peek()
            if token == b"e":
                self._index += 1
                return out
            key = self._parse()
            if not isinstance(key, bytes):
                raise InvalidTokenError(
                    f"invalid_dict_key offset={self._index} type={type(key)!r}"
                )
            out[key] = self._parse()

    def _parse_bytes(self) -> bytes:
        colon = self._blob.find(b":", self._index)
        if colon < 0:
            raise UnexpectedEOFError(f"unterminated_string_length offset={self._index}")
        raw_len = self._blob[self._index : colon]
        try:
            size = int(raw_len)
        except ValueError as exc:
            raise InvalidTokenError(
                f"invalid_string_length offset={self._index} value={raw_len!r}"
            ) from exc
        if size < 0:
            raise InvalidTokenError(
                f"negative_string_length offset={self._index} value={raw_len!r}"
            )
        start = colon + 1
        end = start + size
        if end > len(self._blob):
            raise UnexpectedEOFError(
                f"unterminated_string offset={self._index} length={size}"
            )
        self._index = end
        return self._blob[start:end]


def bencode_decode(blob: bytes) -> Any:
    """Decode *blob* and require full input consumption."""

    return BencodeDecoder(blob).decode()


def bencode_encode(value: Any) -> bytes:
    """Encode Python values into canonical bencode bytes."""

    if isinstance(value, bool):
        return b"i1e" if value else b"i0e"
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, str):
        data = value.encode("utf-8")
        return str(len(data)).encode("ascii") + b":" + data
    if isinstance(value, list):
        return b"l" + b"".join(bencode_encode(item) for item in value) + b"e"
    if isinstance(value, tuple):
        return b"l" + b"".join(bencode_encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        items: List[bytes] = []
        for key in sorted(
            value.keys(),
            key=lambda raw: raw if isinstance(raw, bytes) else str(raw).encode("utf-8"),
        ):
            key_bytes = key if isinstance(key, bytes) else str(key).encode("utf-8")
            items.append(bencode_encode(key_bytes))
            items.append(bencode_encode(value[key]))
        return b"d" + b"".join(items) + b"e"
    raise TypeError(f"unsupported_bencode_type type={type(value)!r}")


def bencode_load(path: Path) -> Any:
    """Decode bencode from a file."""

    return bencode_decode(Path(path).read_bytes())


def bencode_dump(path: Path, value: Any) -> None:
    """Encode *value* to a file."""

    Path(path).write_bytes(bencode_encode(value))


def as_text(value: Any) -> str:
    """Decode bytes to text, tolerating non-UTF8 input."""

    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    return str(value)
