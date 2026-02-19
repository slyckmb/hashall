from scripts.rehome_safe_verify_cleanup import _expected_save_path, _is_qb_ready_state


def test_qb_ready_state_rules():
    assert _is_qb_ready_state("uploading") is True
    assert _is_qb_ready_state("stalledUP") is True
    assert _is_qb_ready_state("queuedUP") is True
    assert _is_qb_ready_state("checkingUP") is False
    assert _is_qb_ready_state("moving") is False
    assert _is_qb_ready_state("error") is False
    assert _is_qb_ready_state(None) is False


def test_expected_save_path_prefers_view_target():
    plan = {
        "target_path": "/pool/data/cross-seed/A/Title",
        "view_targets": [
            {"torrent_hash": "abc", "target_save_path": "/pool/data/cross-seed/A"},
            {"torrent_hash": "def", "target_save_path": "/pool/data/cross-seed/B"},
        ],
    }
    assert _expected_save_path(plan, "def") == "/pool/data/cross-seed/B"
    assert _expected_save_path(plan, "xyz") == "/pool/data/cross-seed/A"
