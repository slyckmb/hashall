# Canonical Path Specification

**Version:** 1.0.0-draft
**Status:** APPROVED FOR IMPLEMENTATION (except §8 — marked HOLD)
**Date:** 2026-06-17

---

## 1. Overview

This specification defines the canonical save path for any torrent item managed
by the hashall system. It unifies two formerly independent decision axes:

| Axis | Former Tool | What It Decides |
|---|---|---|
| WHERE | `rehome/planner.py` | Which seeding root (stash vs pool) |
| WHAT PATH | `save_path_inference.py` | Category subdirectory formula |

The spec is the sole arbiter. Both qB and RT are independently diffed against
the canonical target. Neither client's current path is assumed correct.

**Migration moratorium:** No mutations from `rehome` or `save_path_inference`
until this spec is implemented AND 4-gate validated. The implementation replaces
both tools with one unified path resolver.

---

## 2. Input Data Sources

| Field | Source | Used For |
|---|---|---|
| qB category | qB API / silo-qb cache (`torrents-info.json`) | Item type classification, ATM category |
| qB save_path | qB API / silo-qb cache | Current save location, cross-seed tracker hint |
| qB tags | qB API / silo-qb cache | `~noHL` advisory, tracker tag, cross-seed detection |
| qB torrent name | qB API / silo-qb cache | Torrent display name (payload name) |
| RT path | RT XMLRPC / silo-rt cache (`torrents.json`) | Current save location for diff |
| Catalog payload DB | `~/.hashall/catalog.db` | Payload identity, device ID, fs_uuid, hardlink count |
| `seed-root-state.json` | `~/.hashall/seed-root-state.json` | Active seeding roots (`active.seeding_root`, `mirror_roots`) |
| `tracker-registry.yml` | traktor config (`$HASHALL_TRACKER_REGISTRY` or fallback) | Tracker key ↔ Prowlarr display name ↔ URL pattern |
| `qbit_manage config.yml` | qbm config directory | Tracker-key → category mapping for ATM items |
| Filesystem (on-demand) | `os.stat()`, `os.lstat()` | Hardlink external-consumer check (`--full-scan` mode) |

**Note on RT announce URL:** Not required as an input for path derivation.
qB category + tags are sufficient. RT announce URL may be consulted for
verification only.

---

## 3. Decision Tree

### Step 0: Pre-screen — Staging / Non-Canonical Paths

Check the current save_path (from RT or qB) for known staging directory
patterns. If matched, classify as NEEDS_REPAIR and do not attempt to infer
a canonical target from the current path alone.

| Pattern | Class | Action |
|---|---|---|
| `/seeding/_rehome-unique/<hash>/` | Class 4 | Run `save-path-repair` or manual rehome |
| `/seeding/_qb-finish/` | Class 5 | Per-item state investigation → repoint |
| `/seeding/_qb-unique-repair/` | Class 5 | Same as above |
| `/seeding/_qb-repair-v2/` | Class 5 | Same as above |
| `/seeding/cross-seed-link/` | Legacy | Apply `normalize_cross_seed_refactor_path()` → re-enter tree at Step 1 |
| `/seeding/cross-seed/<40-hex-hash>/` | Class 1 | Proceed to Step 1 — tag-based tracker resolution will resolve |

### Step 1: Classify Item Type

Primary classifier is **qB category**. This discriminates between the two
routing mechanisms: ATM-managed (Mechanism 1) vs explicit save_path
(Mechanism 2).

```
qB category:
│
├─ cross-seed
│   → Type: CROSS_SEED
│   → Routing: Mechanism 2 (explicit save_path with cross-seed/ prefix)
│   → ATM: OFF
│
├─ sonarr / radarr / lidarr / readarr / speakarr
│   → Type: ARR_PRE_IMPORT
│   → Routing: Mechanism 1 (ATM-managed)
│   → Final category: use ARR_CATEGORY_FINAL_MAP:
│       sonarr → tv, radarr → movies, lidarr → music,
│       readarr → books, speakarr → audiobooks
│
├─ tv / movies / books / ebooks / audiobooks / music
│   → Type: ARR_POST_IMPORT
│   → Routing: Mechanism 1
│   → Category is final — do not map
│
├─ [tracker-name] (abtorrents, theempire, myanonamouse, thegeeks, etc.)
│   → Type: QBM_TRACKER_TAGGED
│   → Routing: Mechanism 1
│   → Tracking mechanism: qbit_manage assigned this category
│
├─ [other explicit category] (prowlarr, lazylibrarian, qigong, etc.)
│   → Type: OTHER_EXPLICIT
│   → Routing: Mechanism 1
│   → Use category name verbatim as subdirectory
│
└─ Uncategorized / empty
    → Type: UNCATEGORIZED
    → Fall back to Step 1b (tag-based classification)
```

#### Step 1b: Tag-Based Fallback (uncategorized only)

When qB category is `Uncategorized` or empty, use qB tags as the classifier.

1. Filter out system tags (SYSTEM_TAGS): `private`, `cross-seed`, `~noHL`,
   `~rt-mirrored`, `needs_rehome`, `other`, `public`, `_movie`, `aither-like`,
   `speed`, `stoppeddl_not_recoverable`, `rehome*`, and any tag starting with `~`
2. Among remaining tags:
   - If exactly one tag remains: use as tracker name (Type: QBM_TRACKER_TAGGED)
   - If multiple remain: prefer tags matching known qbit_manage categories;
     otherwise take first alphabetically
   - If zero remain: classify as UNKNOWN, flag for human review
3. If `cross-seed` tag is present but category is not `cross-seed`:
   treat as CROSS_SEED, resolve tracker from tags

### Step 2: Determine Seeding Root (WHERE)

Two scan modes are available (see §5). The description below describes the
authoritative check; the default mode uses tag + catalog data as a proxy.

```
Hardlink evidence: does any file in the item's payload have external
consumer hardlinks (files outside seeding roots sharing same inodes)?
│
├─ YES — external consumer found
│   → Seeding root: STASH  (/data/media/torrents/seeding)
│   → Rationale: moving would break media library hardlinks
│   → Scope: applies to the entire inode-sharing group, not single item
│
└─ NO — no external consumer found
    │
    ├─ ~noHL tag present (and no ARR category implying library link)
    │   → Seeding root: POOL  (/pool/media/torrents/seeding)
    │   → Note: ~noHL is advisory only — verify at plan time
    │
    ├─ CROSS_SEED type (category = cross-seed)
    │   → Seeding root: POOL  (default for seed-only content)
    │   → Exception: if filesystem scan reveals library hardlinks
    │
    └─ Default
        → Seeding root: STASH
```

**Two scan modes for hardlink detection:**

| Mode | Detection Method | Speed | Accuracy |
|---|---|---|---|
| Default | `~noHL` tag + catalog hardlink counts | Fast | May produce false positives (stale tag) |
| `--full-scan` | Live filesystem `stat()` across all sibling payload inodes | Slow | Authoritative |

### Step 3: Determine Category Subdirectory (WHAT PATH)

The WHAT PATH determines the seeding-root-relative portion of the canonical path.
This is the segment between the seeding root and the item payload name.

#### 3a: CROSS_SEED items

```
cat = "cross-seed" (determined in Step 1)
│
├─ Resolve tracker name:
│   1. Try to extract from current save_path path structure.
│      If path contains cross-seed/<tracker>/, use <tracker>.
│   2. Fall back to qB tags (filter out SYSTEM_TAGS, ~-prefixed).
│      If one tag remains, use it as tracker name.
│      If multiple remain, prefer qbit_manage-known categories,
│      then alphabetical.
│   3. If cross-seed/<hash>/ (Class 1): use qB tags to resolve.
│
├─ Canonical subdir: cross-seed/<resolved-tracker-name>/
│
└─ Examples:
     cross-seed/darkpeers/    (short key acceptable)
     cross-seed/Darkpeers (API)/  (Prowlarr display name acceptable)
```

**Rule:** Both the short registry key (`darkpeers`) and the Prowlarr display
name (`Darkpeers (API)`) are canonical. Do NOT rename existing items from one
form to the other — cross-seed re-creates the display-name path on the next
injection cycle.

#### 3b: ARR items

```
cat starts with sonarr/radarr/lidarr/readarr/speakarr:
  → Use ARR_CATEGORY_FINAL_MAP to derive final category
  → Canonical subdir: <final-category>/
  → Use current save_path as evidence of pre-vs-post-import state.
    If current path uses final category, item is post-import.

cat is tv/movies/books/ebooks/audiobooks/music:
  → Canonical subdir: <category>/
  → This is the final ATM-managed form.
```

#### 3c: QBM_TRACKER_TAGGED items

```
cat matches a known tracker-name category:
  → Canonical subdir: <category>/
  → If category has an alias in CATEGORY_DIR_ALIASES, both the
    canonical name and alias are valid. Prefer the canonical name
    for new placements. Do not rename existing items.
```

#### 3d: OTHER_EXPLICIT items

```
cat is any explicit category not matching above:
  → Canonical subdir: <category>/
  → Examples: prowlarr, lazylibrarian, qigong
```

#### 3e: UNCATEGORIZED / UNKNOWN items

```
cat is Uncategorized or empty:
  → If tag-based resolution (Step 1b) succeeded: use resolved subdir
  → If cross-seed tag present (but category mismatch): treat as cross-seed
  → If no resolution: flag UNKNOWN for human review
```

### Step 4: Assemble Full Canonical Path

```
<seeding-root>/<category-subdir>/<item-payload-name>/
```

**Seeding root:** From Step 2.

| Device | Canonical Path |
|---|---|
| STASH | `/data/media/torrents/seeding/` (container) / `/stash/media/torrents/seeding/` (host) |
| POOL | `/pool/media/torrents/seeding/` |

**Category subdir:** From Step 3. Includes `cross-seed/` prefix for cross-seed items.

**Item payload name:** From qB torrent `name` field (or RT `d.name`).

**Single-file torrent rule:**
- If the torrent defines a folder internally (multi-file torrent in qB API)
  → Include release-name subdirectory: `<seeding-root>/<cat>/<release-dir>/<files>`
- If the torrent is a bare file (single file, no internal folder)
  → No subdirectory: `<seeding-root>/<cat>/<filename>`
- A spurious directory wrapping a single file is an RT artifact/bug
  → Classify as NEEDS_REPAIR

**Path preservation on rehome:** The seeding-root-relative portion
(`<category-subdir>/<item-payload-name>/`) is preserved verbatim when
moving between stash and pool. Only the root prefix changes.

### Step 5: Diff vs Actual (Both Clients)

Compute canonical target from Steps 1–4. Then independently diff RT's current
save_path and qB's current save_path against the canonical target.

```
For each client (RT, qB):
│
├─ save_path == canonical target
│   → Status: CANONICAL for this client
│
├─ seeding root differs (same relative path, different root)
│   → Mismatch: ROOT_DRIFT
│
├─ category subdir differs (relative path doesn't match)
│   → Mismatch: CATEGORY_DRIFT
│   → Sub-categories:
│     ├─ cross-seed/ prefix missing (bare <tracker/>)
│     ├─ wrong tracker name
│     ├─ legacy path (cross-seed-link)
│     └─ other
│
├─ item payload name differs
│   → Mismatch: NAME_DRIFT
│
├─ path is staging/non-canonical (Class 4/5)
│   → Mismatch: STAGING_NEEDS_REPAIR
│
└─ path doesn't exist on disk
    → Mismatch: PATH_MISSING
```

**Output:** For each item, produce a pair of diff results — one per client.

---

## 4. Action Table (RT × qB Combinations)

| RT Status | qB Status | Action |
|---|---|---|
| CANONICAL | CANONICAL | None. Item is correctly placed. |
| CANONICAL | ROOT_DRIFT | Repoint qB to canonical (RT's current path). |
| CANONICAL | CATEGORY_DRIFT | Repoint qB to canonical (RT's current path). |
| CANONICAL | MISSING | Add qB mirror at RT path. |
| ROOT_DRIFT | ROOT_DRIFT | Rehome both to canonical root. |
| ROOT_DRIFT | CANONICAL | Rare: qB at canonical, RT not. Rehome RT to canonical. |
| ROOT_DRIFT | CATEGORY_DRIFT | Rehome RT to canonical root; repoint qB to canonical path. |
| CATEGORY_DRIFT | CATEGORY_DRIFT | Rename directory and/or repoint both to canonical path. |
| CATEGORY_DRIFT | CANONICAL | Rename RT directory (or repoint RT) to match canonical. |
| NEEDS_REPAIR | *any* | Run repair tool (save-path-repair, qb-fastresume-patch, etc.) before re-evaluating. |
| PATH_MISSING | *any* | Investigate: data missing on disk. Escalate. |
| UNKNOWN | *any* | Escalate for human review. |

**Key principle:** When both clients are in different states, the decision tree
output is authoritative — not either client's current path. "RT wins" only
applies after the tree confirms RT is already at the canonical path.

---

## 5. Scan Modes

Two modes for hardlink/external-consumer detection (Step 2 WHERE decision):

### Default Mode (fast)

- Uses `~noHL` tag as a proxy for "no external consumers"
- Checks catalog DB for hardlink counts per payload (from last refresh)
- No live filesystem scan
- May produce false positives if:
  - `~noHL` tag is stale (new ARR import created a hardlink after tagging)
  - Catalog is stale since last refresh cycle

### `--full-scan` Mode (authoritative)

- For each item's payload, queries the filesystem for all inodes
- Checks if any file paths in those inodes fall outside all seeding roots
- If external consumer found → must stay on STASH
- Results saved to disk for offline review and reuse in subsequent runs
  without rescanning
- Required before authorizing any pool rehome operation

---

## 6. Implementation Notes

### 6.1 Hitchhiker Groups

Group membership is NOT part of the decision tree. The tree computes the
canonical target per-item. A separate execution/planning tool must check
the full inode-sharing group before authorizing any move.

- If two torrents share inodes (hitchhiker group), they must move together
- If any member of the group has an external consumer hardlink, the entire
  group stays on STASH
- The execution tool must enforce this, not the tree

### 6.2 Single-File Torrent Rule

The qB API's file listing determines the torrent's internal structure:

- `get_torrent_files(hash)` returns `QBitFile(name, size)` list
- If `name` for all files contains a path separator (`/`) → multi-file torrent
  → canonical path includes a release-name subdirectory
- If `name` for the single file has no path separator → bare-file torrent
  → canonical path is `<root>/<cat>/<filename>` directly

### 6.3 `~noHL` Verification

`~noHL` is advisory only, never authoritative. It can be stale.

- Use it as a pre-filter for pool candidates (default scan mode)
- Always re-verify with a `--full-scan` before authorizing a pool move
- The tag applies to the qB item only, not sibling payloads
- qB and RT may have different save_paths for the same item — verify both

### 6.4 ARR Pre-Import vs Post-Import

Use current save_path as evidence:
- If save_path uses pre-import category (`sonarr/`, `radarr/`, etc.) → pre-import
- If save_path uses post-import category (`tv/`, `movies/`, etc.) → post-import
- Post-import category is the final form
- Pre-import categories mapped via ARR_CATEGORY_FINAL_MAP

### 6.5 Path Translation

| Coordinate System | Path |
|---|---|
| Container (RT, qB) | `/data/media/torrents/seeding/...` |
| Host (stash) | `/stash/media/torrents/seeding/...` |
| Host (pool) | `/pool/media/torrents/seeding/...` |

The spec uses container-relative paths (`/data/media/...`) for STASH and
host paths (`/pool/media/...`) for POOL. Translation between `/data/media/`
and `/stash/media/` is a bind mount (same device, same filesystem).

---

## 7. Scope Estimates

From qB cache (4898 items, 2026-06-17):

| Branch | Count | % | Classification |
|---|---|---|---|
| CROSS_SEED — at canonical path | 8 | 0.2% | CANONICAL |
| CROSS_SEED — bare `<tracker>/` (cross-seed/ prefix missing) | 2393 | 48.9% | NEEDS REPAIR |
| CROSS_SEED — `<hash>/` unresolved (Class 1) | 3 | 0.1% | NEEDS REPAIR |
| CROSS_SEED — staging dirs (_rehome-unique, etc.) | ~42 | 0.9% | NEEDS REPAIR |
| ARR (tv, movies, books, music, ebooks, audiobooks) | ~786 | 16.0% | VERIFY (assumed canonical) |
| ARR pre-import (sonarr, radarr, readarr, speakarr) | ~14 | 0.3% | VERIFY (transient) |
| QBM_TRACKER_TAGGED (abtorrents, theempire, thegeeks, etc.) | ~1295 | 26.4% | VERIFY (assumed canonical) |
| OTHER EXPLICIT (prowlarr, lazylibrarian, qigong) | ~25 | 0.5% | VERIFY (assumed canonical) |
| UNCATEGORIZED or ambiguous | ~332 | 6.8% | NEEDS CLASSIFICATION |
| **Total** | **4898** | **100%** | |

**`~noHL` distribution:** 1702 items (34.8%) have `~noHL` tag → pool candidates
(pending hardlink re-verify). 3196 items (65.2%) no `~noHL`.

---

## 8. Known Damage Requiring Repair

### Damaged: cross-seed/ prefix missing (OP-17)

- **Count:** 2393 items
- **Cause:** `save_path_inference.py` line 223 returned bare `<tracker>/`
  instead of `cross-seed/<tracker>/`
- **Fix:** Rename directory to add `cross-seed/` prefix, repoint both clients
- **Status:** HOLD — big-picture migration strategy must be decided first.
  Goal is one move per item combining rehome + path fix. Do not repair
  independently of the rehome strategy.

### Damaged: Class 1 (cross-seed/<hash>/)

- **Count:** 3 items
- **Cause:** Tracker name not resolved at cross-seed injection time
- **Fix:** Resolve tracker name via qB tags, rename directory, repoint both clients
- **Status:** Ready for implementation. Depends on unified tool.

### Damaged: Class 4 (_rehome-unique/)

- **Count:** ~42 items (cross-seed category found in staging)
- **Fix:** Run save-path-repair to move data to canonical path
- **Status:** Ready for implementation. Depends on unified tool.

### Damaged: Class 5 (_qb-finish, _qb-unique-repair, _qb-repair-v2)

- **Count:** ~3 items
- **Fix:** Per-item state investigation, then repoint
- **Status:** Needs investigation before repair.

---

## 9. Out of Scope

The following are NOT decided by this specification:

1. **When to run the unified tool.** Sequencing, batching, and migration
   strategy are implementation concerns, not spec concerns.

2. **How to execute the move.** Fastresume patching vs set_location vs
   delete-and-re-add is an execution detail. The spec only defines the
   canonical target.

3. **Cross-seed injection behavior.** The spec accepts the paths that
   cross-seed creates. It does not control cross-seed's naming.

4. **qB ↔ RT synchronization order.** Whether to fix qB first or RT first
   is determined by the execution tool's repair protocol, not the spec.

5. **Hitchhiker group detection and splitting.** The spec computes per-item
   targets. Group-level constraints are enforced by the execution tool.
