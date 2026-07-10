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
