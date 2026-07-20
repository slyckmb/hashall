import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "prowlarr-freeleech-proof.py"


def load_module():
    spec = importlib.util.spec_from_file_location("prowlarr_freeleech_proof", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_freeleech_from_download_volume_factor_zero():
    mod = load_module()

    result = mod.freeleech_evidence({"downloadVolumeFactor": 0})

    assert result["is_freeleech"] is True
    assert "downloadVolumeFactor=0" in result["reasons"]


def test_freeleech_from_indexer_flag():
    mod = load_module()

    result = mod.freeleech_evidence({"indexerFlags": ["FreeLeech"]})

    assert result["is_freeleech"] is True
    assert "indexerFlags=freeleech" in result["reasons"]


def test_no_freeleech_without_explicit_field():
    mod = load_module()

    result = mod.freeleech_evidence({"title": "Movie 2024", "seeders": 10})

    assert result["is_freeleech"] is False
    assert result["reasons"] == []


def test_proof_match_requires_expected_title_when_present():
    mod = load_module()

    result = mod.proof_match_reason(
        {"title": "Unrelated Show S01E01", "size": 1024},
        expected_title="Dexter S02 720p x265-ZMNT",
    )

    assert result["is_match"] is False


def test_proof_match_accepts_normalized_title_and_size_tolerance():
    mod = load_module()

    result = mod.proof_match_reason(
        {"title": "Dexter.S02.720p.x265-ZMNT", "size": 8339890688},
        expected_title="Dexter S02 720p x265 ZMNT",
        expected_size=8339890797,
        size_tolerance_bytes=2048,
    )

    assert result["is_match"] is True
    assert "title_exact_normalized" in result["reasons"]
