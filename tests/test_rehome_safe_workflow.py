from scripts.rehome_safe_workflow import _safe_candidates


def test_safe_candidates_filters_and_sorts():
    groups = [
        {
            "payload_hash": "skip-not-move",
            "recommendation": "SKIP",
            "movable_bytes": 100,
            "movable_pct_bytes": 1.0,
        },
        {
            "payload_hash": "skip-not-full",
            "recommendation": "MOVE",
            "movable_bytes": 500,
            "movable_pct_bytes": 0.95,
        },
        {
            "payload_hash": "move-small",
            "recommendation": "MOVE",
            "movable_bytes": 100,
            "movable_pct_bytes": 1.0,
        },
        {
            "payload_hash": "move-large",
            "recommendation": "MOVE",
            "movable_bytes": 1000,
            "movable_pct_bytes": 1.0,
        },
    ]

    picked = _safe_candidates(groups, limit=5)
    assert [item.payload_hash for item in picked] == ["move-large", "move-small"]


def test_safe_candidates_limit():
    groups = [
        {
            "payload_hash": f"hash-{i}",
            "recommendation": "MOVE",
            "movable_bytes": i,
            "movable_pct_bytes": 1.0,
        }
        for i in range(10)
    ]
    picked = _safe_candidates(groups, limit=3)
    assert len(picked) == 3
    assert picked[0].movable_bytes == 9
