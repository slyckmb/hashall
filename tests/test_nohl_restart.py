from rehome.nohl_restart import (
    filter_nohl_candidates,
    is_pool_seeds_path,
    is_stash_alias_path,
    sort_payload_groups,
    split_tags,
)


def test_split_tags_strips_and_dedupes() -> None:
    assert split_tags("a, b,~noHL, b") == {"a", "b", "~noHL"}


def test_path_scope_helpers() -> None:
    assert is_stash_alias_path("/stash/media/torrents/seeding/x")
    assert is_stash_alias_path("/data/media/torrents/seeding/x")
    assert not is_stash_alias_path("/pool/data/seeds/x")
    assert is_pool_seeds_path("/pool/data/seeds/tv/x")
    assert not is_pool_seeds_path("/data/media/torrents/seeding/x")


def test_filter_nohl_candidates_respects_scope_and_tag() -> None:
    rows = [
        {"hash": "a" * 40, "save_path": "/data/media/torrents/seeding/a", "tags": "x,~noHL"},
        {"hash": "b" * 40, "save_path": "/pool/data/seeds/a", "tags": "~noHL"},
        {"hash": "c" * 40, "save_path": "/data/media/torrents/seeding/c", "tags": "x"},
        {"hash": "d" * 40, "save_path": "/stash/media/torrents/seeding/d", "tags": "~noHL"},
    ]
    selected = filter_nohl_candidates(rows)
    assert [item.torrent_hash for item in selected] == ["a" * 40, "d" * 40]


def test_sort_payload_groups_orders_items_then_size_then_hash() -> None:
    rows = [
        {"payload_hash": "ccc", "group_items": 3, "payload_bytes": 100},
        {"payload_hash": "bbb", "group_items": 3, "payload_bytes": 200},
        {"payload_hash": "aaa", "group_items": 5, "payload_bytes": 1},
        {"payload_hash": "ddd", "group_items": 3, "payload_bytes": 200},
    ]
    ranked = sort_payload_groups(rows)
    assert [r["payload_hash"] for r in ranked] == ["aaa", "bbb", "ddd", "ccc"]
