from pathlib import Path

import pytest

from hashall.bencode import (
    BencodeError,
    TrailingDataError,
    bencode_decode,
    bencode_dump,
    bencode_encode,
    bencode_load,
)


def test_bencode_round_trip_dict_sorting(tmp_path):
    payload = {
        b"save_path": b"/pool/data",
        b"qBt-savePath": b"/pool/data",
        b"files": [b"a", 1, {b"z": b"x"}],
    }
    path = tmp_path / "payload.bencode"

    bencode_dump(path, payload)

    encoded = path.read_bytes()
    assert encoded.startswith(b"d5:files")
    assert bencode_load(path) == payload


def test_bencode_decode_rejects_trailing_bytes():
    with pytest.raises(TrailingDataError):
        bencode_decode(b"i1ee")


def test_bencode_decode_rejects_malformed_integer():
    with pytest.raises(BencodeError):
        bencode_decode(b"i-0e")


def test_bencode_encode_rejects_unsupported_types():
    with pytest.raises(TypeError):
        bencode_encode(Path("/tmp"))
