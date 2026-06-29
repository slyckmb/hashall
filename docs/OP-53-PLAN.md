# OP-53 Implementation Plan — SHA256 Library Content Anchor

## Problem

`canonical_path_resolver.classify_seeding_device()` relies on `catalog_nlinks > 1`
(hardlink count via inode matching) as the sole signal for "external library consumer."
This only detects hardlinked content — same inode, same filesystem. When a torrent's
content is a separate copy on a different filesystem (e.g. pool seeding copy vs.
stash library copy), the signal is invisible and the resolver defaults to POOL,
missing the opportunity to place on STASH with a hardlink to the library copy.

## Solution — Four Phases

### Phase 1: Backfill SHA256 on Pool Seeding Roots

**Status:** Operational scan, no code changes.

Run `--hash-mode upgrade` on `/pool/media/torrents/seeding` to populate the `sha256`
column on pool seeding files. Currently only 25.8% of pool-media files have SHA256.
The upgrade mode is incremental — files with SHA256 already populated are skipped.

```bash
python -m hashall scan /pool/media/torrents/seeding \
  --hash-mode upgrade --drift-policy metadata --low-priority
```

**Why needed:** Cross-device SHA256 matching in Phase 2 requires SHA256 populated
on both the seeding file (pool) and the library file (stash). Stash already has 82%
coverage (153,688 of 186,899). Pool needs backfill.

### Phase 2: SHA256 Content Matcher in client_drift anchor scan

**Files:** `src/hashall/client_drift.py`

Add a `_Sha256ContentMatcher` class that:

1. For each file in a torrent's payload path, looks up its SHA256 in the local
   device's `files_fs_*` table
2. Queries all other device `files_fs_*` tables for the same SHA256 under ARR
   library roots (`/data/media/movies/`, `/data/media/shows/`, etc.)
3. Returns matches as `ExternalConsumer` entries with `source="sha256_dupe"`

SQL pattern (reuses cross-device logic from `link_analysis.analyze_cross_device()`):

```sql
WITH seeding_files AS (
    SELECT sha256, size FROM files_fs_<device_table>
    WHERE path LIKE '<payload_path>/%' AND status='active' AND sha256 IS NOT NULL
)
SELECT f.path, f.sha256, f.size FROM files_fs_<stash_table> f
JOIN seeding_files s ON f.sha256 = s.sha256 AND f.size = s.size
WHERE f.path LIKE '/data/media/movies/%'
   OR f.path LIKE '/data/media/shows/%'
   OR f.path LIKE '/data/media/books/%'
   OR f.path LIKE '/data/media/music/%'
```

**Integration point:** After the existing inode-based anchor scan in
`_PlacementAnchorScanner._collect_anchor_evidence()`, if no hardlink was found,
run SHA256 content match. Report as anchor evidence.

### Phase 3: library_dupe signal in canonical_path_resolver

**Files:** `src/hashall/canonical_path_resolver.py`

Add a `library_dupe: bool` parameter to `classify_seeding_device()`:

```python
def classify_seeding_device(
    item_type, tags, *,
    catalog_nlinks=None,
    library_dupe=False,     # NEW
    full_scan=False,
):
    if item_type == ItemType.CROSS_SEED:
        if has_nohl:          return POOL
        if catalog_nlinks > 1: return STASH
        if library_dupe:      return STASH   # NEW
        return POOL
```

Wire through `resolve_canonical_path()` → `canonical_path` CLI. When a hash has
SHA256 matches from Phase 2 but no hardlinks, `library_dupe=True`.

### Phase 4: Extend client-drift rank + apply

**Files:** `src/hashall/client_drift.py`, `src/hashall/cli.py`

1. **`client-drift rank`**: Add a `library_dupe` field to path-drift rows so the
   report shows SHA256-based library matches alongside hardlink counts.

2. **`client-drift apply`**: Add a new action `repoint_both_to_stash` that:
   a. Creates hardlinks from library file to stash seeding path
   b. Removes pool copy (all hardlinks)
   c. Repoints RT via `rt_apply_directory_repoint()`
   d. Repoints qB via `setLocation()` + fastresume patch

## Task Breakdown (j48)

| Task | Phase | Scope | Code Change |
|------|-------|-------|-------------|
| t01 | Phase 1 | Pool SHA256 backfill scan | None (operational) |
| t02 | Phase 2 | Add `_Sha256ContentMatcher` to client_drift anchor scan | client_drift.py |
| t03 | Phase 3 | Wire `library_dupe` into canonical_path_resolver | canonical_path_resolver.py, cli.py |
| t04 | Phase 4 | Extend client-drift rank/apply for SHA256-dupe + hardlink apply | client_drift.py, cli.py |

## Pre-requisites

- Catalog DB must have seeding roots and library roots scanned (both are)
- SHA256 backfill must complete before Phase 2-4 can be tested with real data
- `link_analysis.analyze_cross_device()` exists as reference for cross-device SHA256 SQL

## Existing Infrastructure (reuse, don't duplicate)

| Component | File | Purpose |
|-----------|------|---------|
| `link_analysis.analyze_cross_device()` | `link_analysis.py` | Cross-device SHA256 JOIN SQL |
| `get_payload_file_rows()` | `payload.py` | Queries files with SHA256 + inode |
| `payload_hash` | `payload.py` | Content-based payload identity |
| `_PlacementAnchorScanner` | `client_drift.py` | Existing anchor scan (inode-only) |
| `load_qbm_config()` | `save_path_inference.py` | Config loader for tracker lookup |
