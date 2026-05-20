# Seed Data Management System - Requirements & Implementation

**Version:** 1.6 (Living Document)
**Last Updated:** 2026-05-19
**Status:** Active Development - Core features implemented, canonical torrent-tree normalization planning active

---

## Document Purpose

This document serves as the single source of truth for:
- **Requirements**: What the system must do (user-derived needs)
- **Architecture**: How the system is structured
- **Implementation Status**: What's completed, in-progress, and planned
- **Operational Guidelines**: How components work together

**Target Audience:** CLI agents, future developers, system maintainers

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Storage Architecture](#2-storage-architecture) — §2.1 topology, §2.5 seeding domain, §2.6 seed-root contract
3. [Application Stack](#3-application-stack)
4. [Core Requirements](#4-core-requirements) — §4.1 residency rules (incl. `~noHL` advisory), §4.3 external consumer detection, §4.4 canonical path spec
5. [Data Movement (Rehoming)](#5-data-movement-rehoming) — §5.1 demotion (staged cleanup, preexisting target), §5.3 payload groups (partial reconcile, ATM)
6. [Deduplication](#6-deduplication) — §6.3 view building (hitchhiker invariant, cross-device donor prohibition)
7. [Catalog System (hashall)](#7-catalog-system-hashall) — §7.3 scanning (drift policy modes)
8. [Orchestration System (rehome)](#8-orchestration-system-rehome) — §8.2 planning, §8.3 apply, §8.4 qB integration (fastresume, cache), §8.5 safety, §8.6 recovery lane, §8.7 reality snapshots
9. [Operational Requirements](#9-operational-requirements) — §9.2 safety guarantees, §9.3 idempotency
10. [Terminology](#10-terminology)
11. [Implementation Status](#11-implementation-status)
12. [Success Criteria](#12-success-criteria)

> **Note for agents:** Always check `docs/operations/RUN-STATE.md` for current live system state before planning. REQUIREMENTS.md describes intended behavior; RUN-STATE.md captures the operational truth at any point in time, including known gaps and carve-outs.

---

## 1. System Overview

### 1.1 Problem Statement

The user operates a Linux-based media and torrenting system using:
- qBittorrent with Automatic Torrent Management (ATM)
- cross-seed for cross-seeding automation
- \*arr applications (Radarr, Sonarr, Lidarr, Readarr, Speakarr)
- qbit_manage for torrent lifecycle management
- ZFS-backed storage pools

### 1.2 Core Challenge

The system must intelligently manage torrent seed data across two ZFS pools in a way that:
- Preserves hardlink-based space savings (critical for media libraries)
- Supports long-term seeding of non-library content
- Allows data to move fluidly between pools as usage changes
- Avoids duplication across filesystems
- "Just works" with minimal manual intervention
- Remains safe and auditable

**Primary Objective:** Enable safe, deterministic **rehoming** of payloads (stash ↔ pool) without breaking hardlinks or seeding. Hashall exists to provide the catalog, payload identity, and safety checks that make rehome possible.

### 1.3 Key Constraint

**Hardlinks only work within the same filesystem/device.** Data that must be hardlinked to media libraries must remain on the same ZFS pool as those libraries.

### 1.4 qB Payload-Tree Invariant

For qBittorrent operations, the required uniqueness is a **torrent-specific payload tree / file-structure instantiation**, not a unique physical byte copy per torrent.

That means:
- each qB item needs its own save-path-correct on-disk payload tree
- that tree should normally be instantiated from a verified donor payload using **hardlinks**
- the system should avoid making redundant physical file copies just to satisfy per-item path semantics

In short: **unique per-item payload tree, shared physical bytes via hardlinks when possible**

---

## 2. Storage Architecture

### 2.1 ZFS Pool Topology

**Top-Level Pools:**
- **`/stash`** - ZFS pool (warm/active storage)
  - Hosts active media libraries
  - Hardlink source for \*arr-managed content
  - Canonical location for data actively consumed by media applications
  - Hardware: RAID array of HDDs in USB enclosures

- **`/pool`** - ZFS pool (cold storage)
  - Hosts seed-only or cold data
  - Long-term seeding, orphaned, or staging content
  - No \*arr consumers
  - Hardware: RAID array of HDDs in USB enclosures

**Pool ZFS Datasets (Sub-pools):**

The `/pool` pool contains multiple ZFS datasets that are distinct filesystems (distinct `fs_uuid`, distinct `device_id`). Hardlinks do not cross dataset boundaries. The two primary seeding datasets are:

| Dataset alias | Mount point | Role |
|---|---|---|
| `pool-data` | `/pool/data/` | Legacy seeding root (source of current migration) |
| `pool-media` | `/pool/media/` | Active seeding target (destination of current migration) |

**Active Dataset Migration (2026):**
The system is actively migrating seeding content from `pool-data` (`/pool/data/media/torrents/seeding`) to `pool-media` (`/pool/media/torrents/seeding`). During this transition:
- Both datasets are valid seeding roots
- `pool-data` participates as a `mirror_root` (source) until migration is complete
- `pool-media` is the canonical target for new placements
- The published seeding-root contract (`~/.hashall/seed-root-state.json`) reflects which datasets are active/legacy at any point in time
- All planning and apply tooling must be dataset-aware; "pool" is not a single target

**`/pool/data/seeds` — cross-seed scan source, not a rehome destination:**
`/pool/data/seeds` is a cross-seed `dataDir` path (where cross-seed scans for matchable content — see §3.2). It is **not** a seeding root and **not** a valid rehome MOVE target. The canonical rehome destination is always the active pool seeding root from `seed-root-state.json` (currently `/pool/media/torrents/seeding`). Any tooling that defaults to `/pool/data/seeds` as a `dest_root` is using a stale default and must be corrected to read from `seed-root-state.json` at runtime.

**Stable Device Identity:**
ZFS filesystem UUIDs (`fs_uuid`) are stable across reboots; Linux `device_id` values are not. All long-term catalog identity uses `fs_uuid`. Device aliases (e.g., `stash`, `pool-data`, `pool-media`) are registered in the `devices` table and used in CLI parameters instead of raw device IDs.

### 2.2 Bind Mounts & Path Mapping

**Purpose:** Container applications (qBittorrent, cross-seed, \*arr apps) use `/data/media` paths while the underlying storage is at `/stash/media`.

**Active Bind Mount:**
```
/data/media → stash/media (ZFS dataset)
```

**Why This Matters:**
- Both `/data/media` and `/stash/media` reference the **same filesystem** (same device_id)
- Hardlinks work across both path references (they're the same location)
- hashall must resolve symlinks/bind mounts to canonical paths to prevent duplicate scanning
- Device ID detection must be consistent regardless of path used

**Path Equivalencies:**
```
Container View          Real ZFS Path
─────────────────────   ─────────────────────────
/data/media/*       →   /stash/media/*
/pool/data/*        →   /pool/data/* (direct mount)
```

### 2.3 Directory Structure

**Seeding Domain (Active - Stash):**
```
/stash/media/torrents/seeding/          (canonical path)
/data/media/torrents/seeding/           (bind mount, same location)
  ├── cross-seed/                       (cross-seed links on stash)
  ├── myanonamouse/                     (tracker-specific categories)
  ├── aither/
  ├── digitalcore/
  └── [other tracker categories]/
```

**Seeding Domain (Cold - Pool, legacy dataset):**
```
/pool/data/media/torrents/seeding/      (pool-data seeding root, migration source)
/pool/data/cross-seed/                  (cross-seed links on pool-data)
/pool/data/RecycleBin/                  (qbit_manage recycle bin)
/pool/data/orphaned_data/               (orphaned files)
```

**Seeding Domain (Cold - Pool, active dataset):**
```
/pool/media/torrents/seeding/           (pool-media seeding root, migration target)
  ├── cross-seed/                       (cross-seed links on pool-media)
  ├── _rehome-unique/<hash>/            (unique per-item payload trees for shared-root groups)
  └── [tracker categories]/
```

**Target Canonical Torrent Trees (Policy):**
```
/stash/media/torrents/
  ├── seeding/
  │   ├── cross-seed/
  │   └── [tracker categories]/
  └── orphans/

/pool/media/torrents/
  ├── seeding/
  │   ├── cross-seed/
  │   ├── _rehome-unique/<hash>/
  │   └── [tracker categories]/
  └── orphans/
```

Steady-state policy:
- `cross-seed-link` is a legacy name; `cross-seed` is canonical
- `orphaned_data` is a legacy name; `orphans` is canonical
- `orphans` live under `*/media/torrents/orphans`, not under `*/media/torrents/seeding/orphans`
- `/pool/data` is a migration source and residue lane, not a final torrent-payload home

**Media Libraries (External Consumers - Stash):**
```
/stash/media/books/                     (Readarr, Speakarr libraries)
/stash/media/movies/                    (Radarr library)
/stash/media/shows/                     (Sonarr library)
/stash/media/downloads/                 (Active downloads)
  ├── audiobookshelf_library/
  ├── calibre_settings/
  └── [other media dirs]/
```

**Configuration Note:** Paths may be referenced as `/data/media/*` in container configs but resolve to `/stash/media/*` on the host.

### 2.4 Future Expansion Planning

The system is designed to accommodate additional paths as the media library grows:
- Additional subdirectories under `/stash/media/books/`
- New \*arr application libraries
- Additional cross-seed dataDirs for matching

**Design Principle:** Path expansion should not require architectural changes, only configuration updates.

### 2.5 Seeding Domain Definition

The **seeding domain** is the set of filesystem paths where torrent payload data lives for seeding. It is:
- **Configurable**, not hard-coded — defined at planning time via `--seeding-root` flags or the seed-root-state contract
- **Multi-root** — multiple paths may be active simultaneously (e.g., during dataset migration both `pool-data` and `pool-media` seeding roots are valid)
- **Device-scoped** — each root carries its dataset alias to preserve hardlink boundary awareness

External consumer detection, BLOCK decisions, and cleanup logic must all use the current seeding domain definition at execution time, not a stale cached version.

### 2.6 Seed-Root State Contract

**File:** `~/.hashall/seed-root-state.json`

This file is the **authoritative published seeding-root contract** consumed by external orchestration tools (`hashall refresh`, `rehome apply`, `qb-zfs-relocate`, triage scripts, etc.). It declares which roots are:
- `active` — canonical targets for new placements
- `mirror_roots` / legacy — still valid seeding sources, included in seeding domain during migration

**Requirement:** Any tool that needs to know valid seeding roots at runtime must read this file rather than hard-coding paths. The file must be updated when dataset migration adds, removes, or changes the role of a seeding root.

---

## 3. Application Stack

### 3.1 qBittorrent & ATM Behavior

**Automatic Torrent Management (ATM):**
- When ATM is **enabled** on a torrent:
  - qBittorrent automatically moves torrent data to the category's configured save path
  - If category has no explicit path, uses: `[default_save_path]/[category_name]/`
  - Category changes trigger automatic relocation
- When ATM is **disabled** on a torrent:
  - Data stays at injection location (does not auto-relocate)
  - Category changes do NOT trigger moves
  - Manual relocation via API still possible

**Category Configuration:**
- Each category maps to a save path in `/data/media/torrents/seeding/[category]/`
- Categories defined in qbit_manage config (lines 47-108)
- ~40+ tracker-specific categories plus generic ones (books, movies, music, tv, public)

**ATM in This System:**
- Most torrents use ATM for automatic organization
- cross-seed explicitly disables ATM (see Section 3.2)

### 3.2 cross-seed Integration

**Purpose:** Automatically finds and injects cross-seeds for existing content

**Configuration:**
```javascript
// /home/michael/dev/work/glider/glider-docker/cross-seed/config.js
linkDirs: [
  "/pool/data/cross-seed",                          // Pool filesystem
  "/data/media/torrents/seeding/cross-seed",        // Stash filesystem (via bind mount)
]
linkType: "hardlink"
linkCategory: "cross-seed"
```

**Injection Behavior:**
- Assigns category: `cross-seed`
- **Disables ATM** on injected torrents
- Sets explicit save paths based on tracker
- Creates hardlinks in one of the linkDirs (filesystem-aware)

**Key Insight:** cross-seed torrents do NOT use ATM, so category changes won't relocate them. They stay where injected until manually rehomed.

**Data Scanning:**
- `dataDirs`: cross-seed scans these paths to find matchable content
  - `/pool/data/seeds`
  - `/data/media/books/audiobookshelf_library`
  - `/data/media/downloads/DownTVunsorted`
  - (Other paths as configured)

### 3.3 \*arr Applications

**Radarr (Movies), Sonarr (TV), Readarr (Books), Speakarr (Audiobooks), Lidarr (Music):**
- Import media from `/data/media/torrents/seeding/[category]/`
- Create hardlinks to libraries: `/data/media/{movies,shows,books}/`
- Use hardlink import mode (copy is disabled to save space)

**Result:** A single movie file might have:
- Original: `/stash/media/torrents/seeding/radarr/Movie.2024/movie.mkv`
- Hardlink: `/stash/media/movies/Movie (2024)/movie.mkv`
- Both paths reference same inode (zero additional disk usage)

### 3.4 qbit_manage

**Purpose:** Automated torrent lifecycle management

**Configuration:** `/home/michael/dev/work/glider/glider-docker/qbit_manage/config.yml`

**Key Features Used:**
1. **Tag Management:**
   - `tag_nohardlinks: true` - Scans for hardlinks and tags accordingly
   - `nohardlinks_tag: ~noHL` - Tag applied to torrents with no hardlinks

2. **Hardlink Detection Logic:**
   - Scans `root_dir: /data/media/torrents/seeding` for torrent files
   - Checks if files have hardlinks (link count > 1)
   - If torrent category is in `nohardlinks:` list AND no hardlinks detected → apply `~noHL` tag
   - Categories checked: books, movies, music, tv, lidarr, prowlarr, radarr, readarr, sonarr, speakarr, cross-seed, public, Uncategorized, and ALL private tracker categories

3. **Share Limits:**
   - `private_noHL` rule: torrents with `private` + `~noHL` tags
     - `max_seeding_time: 180d`
     - `cleanup: true` - eligible for removal after 180 days
   - These torrents are seed-only, not consumed by media apps

**Significance for Rehoming:**
- Torrents tagged `~noHL` are prime candidates for demotion to pool
- The tag indicates no external consumers (no \*arr hardlinks)
- Provides automated classification without manual inspection

---

## 4. Core Requirements

### 4.1 Data Classification Rules

#### 4.1.1 Hardlink-Based Residency

**Seeding Domain Paths (configurable — see §2.5 and §2.6):**
- Stash primary: `/stash/media/torrents/seeding/` (or `/data/media/torrents/seeding/` via bind mount)
- Pool legacy: `/pool/data/media/torrents/seeding/`, `/pool/data/cross-seed/`
- Pool active: `/pool/media/torrents/seeding/`
- (All active seeding roots from `~/.hashall/seed-root-state.json`)

**External Consumer Paths (Media Libraries):**
- `/stash/media/books/`
- `/stash/media/movies/`
- `/stash/media/shows/`
- `/stash/media/downloads/`
- (Any path outside the seeding domain)

**Rule: Must Stay on Stash**

A sibling payload group **must remain on `/stash`** if:
- Any file in any member payload has hardlink children in external consumer paths
- Example:
  ```
  Torrent file: /stash/media/torrents/seeding/radarr/Movie.2024/video.mkv (inode 1234)
  Hardlink:     /stash/media/movies/Movie (2024)/video.mkv (inode 1234)

  Result: the whole sibling payload group MUST stay on stash (external consumer exists)
  ```

**Rule: Eligible for Pool Migration**

A sibling payload group is **eligible to move to `/pool`** if:
- All hardlinks are siblings within the seeding domain only
- No hardlinks exist in external consumer paths
- Typically identified by `~noHL` tag from qbit_manage

**Threshold:** A single hardlink from any payload file to any media library path is sufficient to mandate stash placement for the entire sibling group. There is no majority threshold. The human rationale: if any content is in the media library (Plex/Jellyfin/Audiobookshelf), all cross-seed copies of that content cost zero additional space via hardlinks and should stay on stash. Once the media library copy is deleted, all seeding copies lose their consumer justification and become candidates for pool migration or deletion.

**qbit_manage `~noHL` alignment:** The `~noHL` logic in qbit_manage works the same way — it tags an item when it finds no hardlinks at all from the torrent's files into media library paths. The hashall external consumer check mirrors this logic. Use `~noHL` as a pre-filter for pool candidates, but always re-verify at plan time with a current filesystem scan.

**Important: `~noHL` is advisory only.** The tag reflects qbit_manage's scan at a specific point in time. A `*arr` import between the qbit_manage scan and a rehome plan execution can create a new external hardlink. The authoritative external consumer check is always the plan-time scan of current catalog/filesystem state. The `~noHL` tag is a pre-filter that narrows candidates; it does not bypass the external consumer check.

#### 4.1.2 Manual-Review Stop Conditions

The system must stop for manual review instead of auto-deciding when:
- the same path/name exists with different file hashes
- stash and pool both have fully verified copies but placement signals disagree
- hardlink-anchor evidence is mixed or unclear
- a sibling payload group is incomplete or only partially verified
- any other unexpected state appears during execution

### 4.2 Payload Identity

**Definition:** A payload is the on-disk content tree a torrent points to:
- Single-file torrent → that file
- Multi-file torrent → directory tree

**Scope note:** `payloads` are qB/torrent-root inventory, not the complete set of scanned folder trees on a filesystem.
- `hashall scan` records filesystem truth in `files_*`
- `hashall payload sync` maps qB torrents onto that scanned truth and materializes `payloads`
- therefore a fully scanned managed tree can still contain large non-qB areas that are not represented in `payloads`

**Payload Hash:** SHA256 of sorted `(path, size, sha256)` tuples
- Uniquely identifies content independent of torrent metadata
- Multiple torrents can share the same payload_hash (siblings)

**Payload Siblings:** Different torrents pointing to identical content:
- Same content, different torrent versions (v1 vs v2)
- Same content, different piece sizes
- Same content, different tracker sources
- Cross-seeds are payload siblings

**Why Payload-Based?**
- Traditional tools work per-torrent
- This system works per-payload (all siblings rehomed together)
- More efficient than moving siblings individually
- Prevents partial moves (some siblings on stash, others on pool)

### 4.2.1 Sibling Payload Group

**Two overlapping concepts — used for different decisions:**

| Concept | Definition | Used for |
|---|---|---|
| **Exact-hash siblings** | Torrents sharing the same `payload_hash` (same `payload_id` in catalog) | Catalog identity, REUSE planning, payload-group moves (§5.3) |
| **Broader inode-sharing group** | Different `payload_id` entries whose files share inodes on the same filesystem (e.g., seedpool cross-seed + darkpeers cross-seed of the same movie) | Stash-vs-pool residency decisions, external consumer detection, hardlink-construction optimization on rehome |

**Key rule:** Exact-hash siblings move together as a unit (§5.3). Members of the broader inode-sharing group that have *different* `payload_hash` values are handled independently — each goes through its own drift audit and rehome plan. The hardlink-construction optimization (§5.1.2) connects them: after the first member is byte-copied to pool, subsequent members can be hardlinked rather than copied.

**Placement unit for residency:** The broader inode-sharing group is the placement unit for stash-vs-pool decisions. If *any* file in *any* member of the inode-sharing group has an external consumer hardlink (§4.3), the entire group must remain on stash — even members that individually show no external consumer. The external consumer check is applied per-file across all inode-sharing paths, not just per-torrent.

For placement and stash-vs-pool residency decisions, hashall uses the broader **sibling payload group** concept:
- non-duplicate payloads that mostly share inodes on the same filesystem
- or would share inodes if rehomed onto the same filesystem

This broader sibling-group concept is the placement unit for:
- keeping hardlink-anchored groups on stash
- rehoming non-anchored groups to pool
- surfacing manual-review conflicts when sibling-group evidence is mixed

### 4.2.2 Broader Content Inventory Requirement

**Intent:** The system should also be able to reason over scanned non-qB folder trees so operators can:
- find duplicate folder trees
- discover donor content for qB repair/remediation
- compare archived/orphaned trees against live qB payloads
- make reclaim decisions with real content identity instead of only path names

**Important distinction:**
- `payloads` remain the qB/torrent-root model
- broader scanned content should be represented by a separate inventory/content-roots layer rather than silently redefining `payloads`

**Minimum capability expected from that broader layer:**
1. Group scanned files into canonical folder-tree identities under managed non-qB roots
2. Compute deterministic tree identity from the same underlying file hash inputs used by payload identity
3. Detect exact duplicate folder trees across:
   - qB seeding roots
   - orphan/archive trees
   - recovery / staging areas
4. Support donor lookup for a known qB payload or broken torrent root
5. Support operator reporting for reclaim candidates and duplicate-byte opportunities

**Current gap:** The existing implementation has the raw `files_*` scan data needed for this, but it does not yet materialize non-qB folder-tree inventory as a first-class concept.

**First implementation shape:**
- Add a durable `content_roots` inventory layer with records such as:
  - `content_root_id`
  - `fs_uuid`
  - `root_path`
  - `root_kind` (`qb_payload`, `orphan`, `archive`, `recovery`, `staging`, `other`)
  - `tree_hash`
  - `file_count`
  - `total_bytes`
  - `status` (`complete`, `incomplete`)
  - `last_built_at`
- Add `content_root_files` or equivalent mapping for stable file membership as needed for explainability and diff/report output.
- Keep `payloads` and `torrent_instances` unchanged as the qB-facing model.

**First CLI surface expected:**
- `hashall content inventory build`
  - materialize/update non-qB content roots from selected managed scan roots
- `hashall content duplicates`
  - list exact duplicate folder trees by `tree_hash`
- `hashall content donors --torrent <hash>`
  - list non-qB and qB donor candidates for a live/broken torrent payload
- `hashall content show --path <root>`
  - inspect one scanned folder tree and its identity/completeness

**Ranking / safety expectations for donor lookup:**
1. Exact `tree_hash` match first
2. Complete-hash matches before incomplete/quick-hash-only candidates
3. qB payload donors and non-qB donors may both be surfaced
4. Path names alone must never be treated as proof of donor equivalence

### 4.3 External Consumer Detection

**Definition:** A file has an **external consumer** if any hardlink points to a path outside the seeding domain.

**Detection Method:**
1. For each file in torrent payload:
   - Get inode + device_id
   - Find all paths with matching inode + device_id
   - **Canonicalize all paths** (resolve bind mounts and symlinks) before comparing against seeding domain roots
   - Check if any canonical path is outside seeding domain roots
2. If ANY file has external consumer → BLOCK demotion

**Canonicalization Requirement:**
Both the candidate hardlink paths and the seeding domain root definitions must be canonicalized before comparison. `/data/media/movies/...` and `/stash/media/movies/...` are the same inode via bind mount; without canonicalization a path under `/data/media/movies/` might falsely appear "inside" a stash-based seeding domain definition. The device registry's `preferred_mount_point` provides the canonical form for each filesystem.

**Example:**
```
Seeding domain: /stash/media/torrents/seeding/

File: /stash/media/torrents/seeding/radarr/Movie.2024/video.mkv (inode 5678)
Hardlinks (canonical paths):
  ✅ /stash/media/torrents/seeding/radarr/Movie.2024/video.mkv (inside domain)
  ❌ /stash/media/movies/Movie (2024)/video.mkv (outside domain - EXTERNAL CONSUMER)

Result: BLOCKED (cannot demote because external consumer exists)
```

**Automated Detection:** qbit_manage's `~noHL` tag is an advisory pre-filter. See §4.1.1 for the authoritative check requirement.

---

### 4.4 Canonical Seeding Path Specification

#### 4.4.1 Payload Uniqueness

**Definition:** A payload is the folder/path/filename tree structure required to support one torrent item. Each item must have its own unique path tree. This enables safe deletion of any item's data without affecting any other item.

**Hardlink sharing:** When two payloads consist of files that are bit-for-bit identical on the same filesystem, those files SHOULD share an inode (hardlink) to save space. The path trees remain distinct — uniqueness is at the directory/path level, not at the inode level.

**Implication for cross-seeds:** A cross-seeded item is a distinct torrent instance with its own canonical path tree. Its files will normally be hardlinked to the original-torrent payload files (same inode, different paths). This is correct and expected. The path tree uniqueness is what permits safe per-item deletion.

#### 4.4.2 Canonical Path Formula

Every seeding item has one and only one canonical path, derived from how it was added to the system:

```
<seeding-root>/<category>/<item-payload-name>
```

Where `<seeding-root>` is the stash or pool seeding root (see §2.5), and `<category>` is determined by item origin (see §4.4.3).

**Single-file torrents:** `<seeding-root>/<category>/<filename>`  
**Multi-file torrents:** `<seeding-root>/<category>/<release-dir>/`

**Seeding root selection rule:**
The seeding root in the canonical path is determined by the item's residency class (§4.1.1):
- Items with a stash hardlink anchor (external consumer exists) → stash seeding root (`/stash/media/torrents/seeding`)
- Pool-eligible items (no external consumer, confirmed by plan-time scan) → active pool seeding root from `seed-root-state.json` (currently `/pool/media/torrents/seeding`)

**Path preservation on rehome:**
The seeding-root-relative path (`<category>/<item-payload-name>`) is identical on stash and pool — only the root prefix changes. When demoting stash→pool or promoting pool→stash, the relative path is preserved verbatim:
```
stash: /stash/media/torrents/seeding/cross-seed/seedpool/Movie.2024/
pool:  /pool/media/torrents/seeding/cross-seed/seedpool/Movie.2024/
```
Any tool computing a rehome target path must derive it by substituting the seeding root, not by using the payload name alone.

#### 4.4.3 Category Rules (by origin)

The category encodes how an item entered the system. Category assignment is permanent and identifies the item's origin path. The rules, in priority order:

| Origin | Canonical category | Example |
|---|---|---|
| ARR pre-import (awaiting import) | `<arr-app>/` | `sonarr/`, `radarr/` |
| ARR post-import (moved by ATM) | `<media-type>/` | `tv/`, `movies/`, `books/`, `music/` |
| cross-seed injection | `cross-seed/<prowlarr-tracker-name>/` | `cross-seed/darkpeers/`, `cross-seed/Darkpeers (API)/` |
| qbit_manage tracker assignment | `<tracker-name>/` | `FearNoPeer/`, `myanonamouse/` |

**Prowlarr display name is acceptable for cross-seed items.** cross-seed uses the Prowlarr indexer display name as the save-path subdirectory and continues to do so for new injections. Both the short registry key (`darkpeers`) and the Prowlarr display name (`Darkpeers (API)`) are canonical for cross-seed items. Do not rename existing items to the short-key form — cross-seed would re-create the display-name path on the next injection cycle. The registry key remains the authoritative identity for URL-to-tracker resolution and reporting; it is not required as the on-disk directory name.

**Historical note:** This category system grew organically:
1. ARR apps used their own app name as the qB category (sonarr, radarr, etc.) to trigger import
2. After import, ARRs changed the category to the media type (tv, movies, etc.) — ATM moved the payload
3. qbit_manage was added and assigned tracker-key categories to uncategorized items, causing a move from `<seeding-root>/<item>` → `<seeding-root>/<tracker-name>/<item>`
4. cross-seed was integrated and assigned `cross-seed` as the category with explicit per-tracker save paths, resulting in `<seeding-root>/cross-seed/<prowlarr-tracker-name>/<item>`

Many items currently have non-canonical paths due to early hashall/rehome code bugs that damaged path structure across thousands of items. Normalization to canonical paths is the long-term goal.

#### 4.4.4 Tracker Key as Category Key

The authoritative source for tracker identity and canonical category key is the **traktor tracker registry** (`tracker-registry.yml`). This YAML file is the single source of truth that ties together:
- The tracker key (YAML top-level key, e.g. `darkpeers`) — used as the category subdirectory
- The tracker URL pattern — for announce URL → key resolution
- The Prowlarr display name and indexer ID
- The qBittorrent save path (`<seeding-root>/<tracker-key>/`)
- The qbit_manage category and tags
- The rTorrent label and save path

**Rule:** The tracker key from the registry is the canonical category for tracker-specific items. For cross-seed items, the category path is `cross-seed/<tracker-key>/`.

When a torrent's announce URL and the path's tracker subdirectory disagree, resolve via the registry: match the announce URL against `tracker_url_pattern` to find the authoritative key. The mismatched path is a legacy accident requiring repair.

**Registry locations (searched in order):**
1. `$HASHALL_TRACKER_REGISTRY` env var
2. `$TRACKER_REGISTRY` env var
3. `/home/michael/dev/tools/traktor/config/tracker-registry.yml`
4. `/home/michael/dev/work/glider/glider-docker/tracker-ctl/config/tracker-registry.yml`

#### 4.4.5 Path Uniqueness Requirement

No two distinct torrent items may share the same canonical path root. When a path collision exists:
- Two items have been incorrectly merged or one has been displaced
- The system must create a unique path for each (e.g., using `_rehome-unique/<hash>/` as a temporary holder)
- `_rehome-unique/<hash>/` is a staging state, not a permanent canonical path

---

## 5. Data Movement (Rehoming)

### 5.1 Demotion (stash → pool)

**Purpose:** Move seed-only payloads from warm storage (stash) to cold storage (pool)

**Trigger Conditions:**
- Payload has no external consumers (all hardlinks are siblings)
- Torrent tagged with `~noHL` (no hardlinks to media libraries)
- User explicitly requests demotion (manual or automated policy)

**Decision Logic:**
```
Payload on stash, want to demote
    ↓
Does it have external consumers?
    │
    ├─ YES → BLOCK (cannot demote, breaks media library links)
    │
    └─ NO → Check if identical payload exists on pool
            │
            ├─ YES → REUSE (point torrents to existing pool payload)
            │
            └─ NO → MOVE (relocate payload from stash to pool)
```

**REUSE Flow:**
1. Verify existing payload on pool (file count, bytes, optional hash spot-check)
2. For each sibling torrent:
   - Build torrent view on pool (hardlinks to payload)
   - Pause torrent in qBittorrent
   - Relocate torrent to pool path via API
   - Resume torrent
   - Verify torrent can access files
3. Remove stash-side torrent views (payload stays on pool)

**MOVE Flow:**
1. Verify source exists and matches expected file count/bytes
2. **Check for preexisting content at target** — if target path already has files with a different file count or different total bytes, ABORT before any data movement. Do not silently overwrite unexpected content.
3. Copy/move payload root directory (stash → pool)
4. Verify target matches expected file count/bytes after copy
5. For each sibling torrent:
   - Build torrent view on pool (hardlinks to payload)
   - Stop torrent in qBittorrent
   - Patch fastresume offline (preferred) or set location via API
   - Restart torrent
   - Verify torrent reaches a seeding-safe state (not `stoppedDL` / `missingFiles`)
6. Verify stash source is cleanly removable before removing it

**Staged Cleanup:**
Source cleanup after a successful MOVE is **deferred by default** and runs as a separate step via `hashall rehome followup --cleanup`. Cleanup stages the source root into `.rehome-cleanup-stage/<payload_hash>/...` rather than deleting immediately, observes qB state on the target paths, and only performs final deletion after the target is confirmed healthy. Any qB regression during the observation window automatically restores the staged source.

**Safety:** Demotion is BLOCKED if external consumers exist. No silent breakage of media library links.

#### 5.1.1 Cross-Filesystem Copy Requirement

Stash (`/stash/media`) and pool (`/pool/media`) are **separate ZFS pools with different `fs_uuid` and `device_id` values**. Hardlinks cannot span ZFS pool boundaries.

**Consequence:** Every stash→pool MOVE is a full byte-level copy (rsync), not a hardlink or rename. This is true even when the content already has hardlinks to other stash paths — those hardlinks remain on stash; the pool copy creates new independent inodes. The stash source is removed only after:
1. The pool copy is verified (file count + total bytes match)
2. All affected torrent clients have been confirmed seeding from the pool path

Until both conditions are met, the stash copy is the active seeding source and must not be deleted.

**Tools:** `rehome` uses `rsync -a --no-whole-file --inplace` (or equivalent) for the copy step. Any tool computing rehome targets must account for this cross-filesystem constraint and must never attempt `os.link()` or `os.rename()` across pool boundaries.

#### 5.1.2 Payload Group Rehome — Primary Mover and Hardlink Construction

When rehoming a broader inode-sharing group (§4.2.1) to pool, only **one member** needs to be byte-copied. After that copy is on pool, its inodes are available for hardlink construction — all remaining members of the group get their own canonical pool path trees built via hardlinks to the first mover's pool inodes. This reduces the byte transfer cost to O(1) per inode-sharing group regardless of how many torrent instances share that content.

**Primary mover selection rule** (evaluated in priority order — first match wins):

| Priority | Condition | Rationale |
|---|---|---|
| 1 | A member already has verified content on the target device | Zero bytes to copy — hardlink all others from it immediately |
| 2 | `status = complete` (all files SHA256-verified in catalog) | Unverified content must not serve as the authoritative pool copy |
| 3 | ARR media-type category (`movies/`, `tv/`, `books/`, `music/`) | Post-ARR-import path is the content origin; cross-seeds were derived from it |
| 4 | Cross-seed at canonical tracker path (`cross-seed/<tracker-key>/<name>/`) | Canonical path beats hash-named or legacy path |
| 5 | Largest `torrent_instances` count for that `payload_id` | Most-used payload is the most established donor |
| 6 | Smallest `payload_id` (oldest in catalog) | Final tie-break: earliest record is the most stable |

**Disqualifiers** (must not be selected as primary mover unless it is the only candidate):
- `status = incomplete` — partial hash coverage; content may not be fully verified
- Path is not under any registered seeding domain root — not a known-good location
- Path is at a `_rehome-unique/<hash>/` staging location on the source device

**Hardlink construction phase:**
After the primary mover's content exists on pool, each remaining member of the inode-sharing group receives its own canonical pool path tree (per §4.4.2 formula). Every file in that tree is hardlinked to the corresponding file in the primary mover's pool path. No additional byte transfer occurs. The pool then has one physical copy of the data, with multiple canonical path trees hardlinked to it — matching the same inode-sharing structure that existed on stash.

**Pool path model (target state):**
Each torrent in the inode-sharing group has its own unique canonical pool path tree. Files are shared via hardlinks across those trees (same inode, different directory entries). The legacy "REUSE" model (multiple torrents pointing to the same directory path) is an artifact of earlier rehome runs and is not the target state. `_rehome-unique/<hash>/` is a temporary staging path used during construction, not a permanent canonical path.

### 5.2 Promotion (pool → stash, reuse-only)

**Purpose:** Move payloads back from pool to stash when needed

**Trigger Conditions:**
- \*arr application imports content that exists on pool
- Payload needs hardlink to library (external consumer added)
- Payload already exists on stash (reuse scenario)

**Critical Rule: No Blind Copy**

Promotion **only occurs if the payload already exists on stash**. The system will NOT copy payloads from pool to stash speculatively.

**Decision Logic:**
```
Payload on pool, want to promote
    ↓
Does identical payload exist on stash?
    │
    ├─ YES → REUSE (point torrents to existing stash payload)
    │
    └─ NO → BLOCK (do not blind copy from pool to stash)
```

**REUSE Flow:**
1. Verify existing payload on stash (file count, bytes)
2. For each sibling torrent:
   - Build torrent view on stash (hardlinks to payload)
   - Pause torrent in qBittorrent
   - Relocate torrent to stash path via API
   - Resume torrent
   - Verify torrent can access files
3. Optional: Cleanup pool-side torrent views (payload stays on stash)

**Why Reuse-Only?**
- Prevents unnecessary duplication across filesystems
- Promotes only when stash already has the content
- If content doesn't exist on stash, it should stay on pool (seed-only)

### 5.3 Payload-Group Management

**Definition:** A payload-group is the set of sibling torrents that share a `payload_hash` (same `payload_id` in the catalog). This is the **exact-hash sibling** concept from §4.2.1 — not the broader inode-sharing group.

**Rehoming Principle:** All exact-hash siblings in a payload-group are rehomed together as a unit. Members of the broader inode-sharing group that have *different* `payload_hash` values are separate payload-groups and are planned and executed independently (though the hardlink-construction optimization in §5.1.2 connects their execution).

**Why move exact-hash siblings together?**
- Prevents split scenarios where some exact siblings are on stash and others on pool at the same logical path
- Single source of truth for payload location
- Simplifies reasoning about system state

**Partial Reconcile Exception:**
When a plan is re-applied after a partial failure, or when siblings have already been relocated by a prior run, the system must handle mixed-state groups without aborting. Siblings already on the target device and path are reconciled into the catalog (`rehome_reconcile_subset`); remaining siblings are processed normally. This preserves the "no re-doing already-done work" idempotency requirement while avoiding silent skips.

**ATM Interaction:**
qBittorrent's Automatic Torrent Management (ATM) automatically moves torrent data when its category changes. For a torrent with ATM enabled that is rehomed to pool, the ATM category save path must point to the target pool path — otherwise qB may auto-relocate it back to stash on the next category update. Rehome must either: (a) disable ATM on rehomed torrents, or (b) verify that the torrent's category save path resolves to the target device before considering the operation complete. cross-seed torrents already have ATM disabled; this requirement primarily applies to ATM-enabled stash-to-pool demotions.

---

## 6. Deduplication

### 6.1 Same-Device Hardlinking

**Purpose:** Eliminate duplicate files on the same filesystem by creating hardlinks

**Scope:** Only within a single device/filesystem
- Deduplication on `/stash` (device_id 50)
- Deduplication on `/pool` (device_id 49)
- Never across devices (hardlinks cannot span filesystems)

**Detection:**
- hashall scans files, computes SHA256
- Groups files by hash within same device_id
- Identifies files with same hash but different inodes (duplicates)

**Workflow:**
1. Analyze: `hashall link analyze --device /stash`
2. Plan: `hashall link plan "Monthly dedupe" --device /stash`
3. Review: `hashall link show-plan <plan_id>`
4. Execute: `hashall link execute <plan_id> --dry-run` (preview)
5. Execute: `hashall link execute <plan_id>` (for real)

**Safety:**
- Dry-run mode for previewing changes
- Backup files before hardlink creation
- Verify inode matches after linking
- Rollback on failure

### 6.2 Cross-Device Duplicate Detection

**Purpose:** Identify when the same payload exists on both stash and pool

**Goal:** Informational awareness, eventual elimination

**Detection:**
- hashall queries for files with same SHA256 across different device_ids
- Reports duplicates but does NOT automatically deduplicate (cannot hardlink across devices)

**Long-Term Goal:**
- Identical payloads should not exist on both filesystems simultaneously
- Use rehoming to consolidate:
  - If payload has external consumers → keep on stash only
  - If payload is seed-only → keep on pool only
  - Prevent new duplicates through rehoming logic (REUSE vs MOVE decisions)

**Short-Term Reality:**
- During transition, duplicates may exist
- Rehoming REUSE logic prevents creating NEW duplicates

### 6.3 Sibling Torrent Deduplication

**Challenge:** Multiple torrents (siblings) pointing to same content still need their own qB-compatible payload trees, but should not consume extra disk space through unnecessary physical copies.

**Solution:** Payload-based hardlink-instantiated views

**Approach:**
1. Identify payload siblings (same payload_hash)
2. Keep one canonical payload location
3. Build hardlink-instantiated "views" for each torrent:
   - Each torrent gets its own expected on-disk directory/file layout
   - Files are hardlinks to canonical donor content
   - Each torrent sees the save-path semantics it expects
   - Zero additional disk usage when hardlinking is possible

**Example:**
```
Canonical payload: /pool/media/Movie.2024/
Torrent A view:    /pool/media/torrents/seeding/cross-seed/Aither (API)/Movie.2024/
                   └── (hardlinks to canonical payload)
Torrent B view:    /pool/media/torrents/seeding/cross-seed/Darkpeers (API)/Movie.2024/
                   └── (hardlinks to canonical payload)

Result: Distinct per-torrent payload trees on disk, with shared physical bytes when hardlinks are possible
```

**Hitchhiker Invariant (anti-pattern prohibition):**

A **hitchhiker** is when two or more torrents with different payload content share a single target directory (N→1 mapping). This produces incorrect save-path semantics and is prohibited for new operations.

**Requirement:** Newly constructed migrations, rehome plans, and view builds must always produce **per-hash unique target roots** — one directory tree per `payload_hash`. For cases where a natural target path would collide (e.g., two different payloads that would both want the same directory name), the system must route into `_rehome-unique/<payload_hash>/` subdirectories to preserve uniqueness.

Existing legacy hitchhiker groups may persist until explicitly de-hitchhiked. Do not create new hitchhiker targets even as a workaround.

**Two hitchhiker types — different root causes, different remediation:**

| Type | Description | Detection | Remediation |
|---|---|---|---|
| **Type A — content-level** | Multiple distinct `payload_hash` values share one physical directory; files from different torrents are co-mingled on disk | Inode-overlap analysis across different `payload_id` values | Split into unique per-hash trees using hardlinks; highest risk, requires content verification |
| **Type B — path-level** | Multiple `torrent_instances` share one `payload_id` but their `save_path` values point to a non-canonical parent (correct content, wrong path) | `hitchhiker.py` audit (2+ `torrent_instances` per `payload_id`) | Path normalization only — no data movement, just client repoint to canonical path |

Type B is the common case from early rehome sessions. Type A is rarer and higher risk. The current `hitchhiker.py` detects Type B only.

**Legacy Hitchhiker Remediation Requirement:**

Hashall must provide a dedicated hitchhiker audit and de-hitchhike lane for existing N→1 payload trees. That lane must:
- identify when two or more hashes share one physical payload tree or share files in a way that violates the unique per-item payload-tree invariant
- classify safe shared-byte reuse separately from incorrect shared payload-tree layout
- construct per-hash unique payload trees using hardlinks where possible, rather than duplicate byte copies
- repoint affected qB/RT items to those unique payload roots

Mandatory stop conditions for de-hitchhike apply:
- partial or inconsistent inode overlap between candidate hashes
- conflicting file hashes at the same relative path
- cross-filesystem cases where hardlink-backed unique trees cannot be built safely
- incomplete or partially verified torrents in the candidate group
- any ambiguous owner/donor relationship

**Cross-Filesystem Donor Prohibition:**

When building a view via hardlinks, the donor payload must be on the **same filesystem** as the target. Selecting a stash donor to build a pool view — or vice versa — is not allowed because hardlinks cannot span filesystems. This check must be enforced before any view-building mutation. Cross-filesystem donor selection requires explicit operator override and produces physical copies, not hardlinks.

---

## 7. Catalog System (hashall)

### 7.1 Unified Catalog Model

**Architecture:** One database catalogs all files across all storage devices

**Database:** `~/.hashall/catalog.db` (SQLite)

**Structure:**
```
catalog.db
├── devices                    (registry: fs_uuid, device_id, alias, mount_point, preferred_mount_point)
├── scan_roots                 (tracks which paths have been scanned)
├── scan_sessions              (audit trail with incremental metrics)
├── files_fs_<normalized-fs_uuid>   (physical files table bound to a stable filesystem UUID)
├── files_<device_id>               (compatibility view over the physical files table)
├── payloads                   (torrent content fingerprints)
├── torrent_instances          (qBittorrent torrent → payload mapping)
└── link_plans                 (deduplication plans)
```

**Why Filesystem-Bound Tables?**
- Hardlinks only work within a device (natural boundary)
- Physical files-table identity must survive reboot/remount `device_id` churn
- Clear data isolation
- Scalable (add new devices without schema changes)
- Compatibility views preserve legacy `files_<device_id>` tooling during migration

**Key Concepts:**
- **Filesystem UUID tracking:** Persistent device identity across reboots
- **Canonical paths:** Symlinks/bind mounts resolved to real paths
- **Preferred mount point:** Stable mount root used to mitigate mount-point drift
- **Incremental updates:** Rescans skip unchanged files (10-100x faster)
- **Scoped deletion:** Only marks files deleted under scanned roots (prevents false deletions)

### 7.2 Hash Algorithm Standard

**Decision: SHA256 for file hashing (cutover complete)**

**Rationale:**
- SHA1 is cryptographically deprecated (collision attacks exist)
- SHA256 provides stronger collision resistance
- fast-hash optimization makes SHA256 performance acceptable
- Future-proof security posture
- Better collision detection for large file sets

**Implementation:**
- **File hashes:** SHA256 (primary)
  - fast-hash: Quick initial scan using partial file content (sample hash)
  - Full SHA256 computed for changed/new files (or upgrade mode)
- **Payload hashes:** SHA256 of sorted `(path, size, sha256)` tuples
- **Incremental optimization:** Skip rehashing if file unchanged (mtime + size check)

**Migration Note (current):**
- SHA1 retained only for legacy compatibility (optional)
- CLI includes `sha256-backfill` and `sha256-verify` for migration + spot-checks

### 7.3 Incremental Scanning

**Purpose:** Fast rescans that only process changed files

**How It Works:**

**Initial Scan:**
1. Walk filesystem tree
2. Compute SHA256 for every file (or upgrade later)
3. Store: path, inode, device_id, size, mtime, sha256 (sha1 optional legacy)
4. Detect filesystem UUID for persistent device identity
5. Performance: ~20-30 files/sec (sequential), ~100-150 files/sec (parallel 8 workers)

**Incremental Rescan:**
1. Walk filesystem tree
2. For each file:
   - Check if exists in catalog (by path + device_id)
   - Compare size + mtime
   - Apply drift policy (see below)
   - If changed or new → recompute SHA256, update catalog
3. Detect deletions (files in catalog but not on filesystem, scoped to scan root)
4. Performance: ~500-1000 files/sec (sequential), ~2000-5000 files/sec (parallel)

**Result: 10-100x speedup on rescans**

**Drift Policy Modes (`--drift-policy`):**

| Mode | Behavior | Use Case |
|---|---|---|
| `metadata` | Trust unchanged size+mtime; skip rehashing | Routine confidence pass (cheapest) |
| `quick` | Recompute quick hash even for metadata-unchanged files; escalate to full hash if drift detected | Balance between speed and drift detection |
| `full` | Fully rehash all files in scope regardless of metadata | Drift audit; highest confidence |

**Hash Mode (`--hash-mode`):**

| Mode | Behavior |
|---|---|
| `fast` | Compute and store only quick hashes (partial content sample) |
| `full` | Compute full SHA256 for all scanned files |
| `upgrade` | Normal incremental behavior but backfill missing full hashes on existing records |

Choose `--scan-hash-mode fast --drift-policy metadata` for routine rescans. Choose `--scan-hash-mode full --drift-policy full` for pre-migration integrity audits.

**Scoped Deletion Detection:**
- Only marks files as deleted if they're under a scanned root
- Prevents false deletions when scanning subdirectories
- Scan root tracked in `scan_roots` table

**Parallel Scanning:**
- Multi-threaded hashing for 4-5x speedup
- WAL mode for concurrent access without lock contention
- Configurable worker count: `--parallel --workers 12` (optimized for fast-hash)
- Unified catalog supports cross-device features (rehoming, payload tracking, link dedup)

### 7.4 Payload Tracking

**Purpose:** Map qBittorrent torrents to on-disk content (payloads)

**Tables:**
- `payloads`: Unique content fingerprints
  - `payload_id`: Integer primary key
  - `payload_hash`: SHA256 of sorted `(path, size, sha256)` tuples
  - `root_path`: Primary location on disk
  - `file_count`: Number of files in payload
  - `total_bytes`: Total size of payload

- `torrent_instances`: qBittorrent torrents
  - `torrent_hash`: qBittorrent infohash
  - `payload_id`: Foreign key to payloads
  - `save_path`: qBittorrent save path
  - `category`: qBittorrent category
  - `tags`: qBittorrent tags (JSON)

**Sync Process:** Connects to qBittorrent, maps torrents to payloads, and updates the catalog.

**CLI usage:** See `docs/RUNBOOK.md` (payload commands).

---

## 8. Orchestration System (rehome)

### 8.1 Overview

**Tool:** `rehome` (orchestration subsystem within hashall)

**Purpose:** Safely orchestrate payload movement between stash and pool datasets

**Why it matters:** Rehome is the core workflow this system is built to support. Hashall’s catalog + payload identity are required inputs to rehome’s plan/apply logic.

**Capabilities:**
- Demotion planning and execution (stash → pool)
- Promotion planning and execution (pool → stash, reuse-only)
- Root-to-root relocation planning (`rehome relocate-plan`) for dataset migration within a pool
- External consumer detection (blocks unsafe demotions)
- qBittorrent integration (stop/offline fastresume patch/start)
- Batch operations (by payload-hash or qBittorrent tag)
- REUSE/MOVE/BLOCK decision logic
- Dry-run mode for safety
- Live drift snapshots (`reality-pre/post/failure.json`) per apply run
- Staged cleanup with automatic rollback on qB regression

**Operational Lanes:**
1. **Scan lane** — maintain filesystem truth via `hashall scan` / `hashall refresh`
2. **Payload sync lane** — map qB torrents to payload state via `hashall payload sync`
3. **Content inventory lane** — build/query broader non-qB folder-tree identity for archive, orphan, donor, and staging trees
4. **Link lane** — same-device hardlink dedup planning + execution
5. **Rehome lane** — guarded stash/pool relocation with verification and per-item payload-tree instantiation
6. **Recovery lane** — classify and prune recovered non-seeding data; triage `stoppedDL`/`missingFiles` cohorts; repair fastresume/location drift

**Architecture:** Plan → Review → Apply workflow with mandatory dry-run before force-apply.

**Detailed Usage:** See `docs/RUNBOOK.md`

### 8.2 Planning Phase

**Command:** `rehome plan` (details in `docs/RUNBOOK.md`)

**Modes:** single-torrent, batch by payload hash, batch by tag.

**Directions:** demote (stash → pool), promote (pool → stash, reuse-only).

**Inputs:**
- Torrent hash, payload hash, or tag (mutually exclusive)
- `--seeding-root`: Path(s) defining seeding domain (can specify multiple; should match `seed-root-state.json`)
- `--stash-device`, `--pool-device`: Device aliases (e.g., `stash`, `pool-media`) — use stable aliases from the devices table, not raw `device_id` values (which are not stable across reboots)
- `--catalog`: Path to hashall database (default: `~/.hashall/catalog.db`)

**Process:**
1. Query hashall catalog:
   - Resolve torrent → payload
   - Get payload_hash, location, size, file count
   - Find sibling torrents
2. Check for external consumers:
   - Find all hardlinks for each file in payload
   - Check if any hardlink is outside seeding domain
   - If found → decision: BLOCK
3. Check if payload exists on target device:
   - Query catalog by payload_hash + target device_id
   - If exists → decision: REUSE
   - If not exists → decision: MOVE
4. Generate plan JSON file:
   - Decision (BLOCK/REUSE/MOVE)
   - Reasons (human-readable)
   - Source and target paths
   - All affected torrents (siblings)
   - Verification checksums (file count, total bytes)

**NULL Payload Hash:**
Payloads with `payload_hash = NULL` (full SHA256 not yet computed for all files) are **not eligible for REUSE planning** — sibling matching requires a complete hash. These payloads must have `hashall sha256-backfill` run first. MOVE planning for NULL-hash payloads is allowed only when relying on file-count and byte-count verification alone (lower confidence).

**Catalog Freshness Requirement:**
Plans must be generated from a current catalog state. **Always run `hashall refresh` (or `hashall scan` + `hashall payload sync`) immediately before generating a plan.** A stale catalog may show payloads at incorrect locations, miss recently-created external consumers, or produce incorrect sibling lists. The RUNBOOK makes this a hard operational requirement.

**Output:** Plan JSON file — written to `~/.logs/hashall/reports/rehome-runs/plans/<plan>.json`

### 8.3 Application Phase

**Command:** `rehome apply <plan_file>` (details in `docs/RUNBOOK.md`)

**Modes:**
- `--dryrun`: Preview actions without making changes
- `--force`: Execute the plan (mutually exclusive with --dryrun)

**Optional Cleanup Flags (opt-in, disabled by default):**
- `--cleanup-source-views`: Remove source-side torrent views after relocation
- `--cleanup-empty-dirs`: Remove empty directories under seeding roots

**REUSE Execution:**
1. Preflight existing target views — compare any preexisting destination files read-only against the donor before building new hardlinks. Abort the entire plan if any target-view path contains different bytes.
2. Verify existing payload on target device (file count, bytes, optional hash spot-check)
3. For each sibling torrent:
   - Build torrent view on target (hardlinks to payload)
   - Libtorrent-verify donor before any qB mutation
   - Stop torrent in qBittorrent
   - Patch fastresume offline (preferred) or set location via API
   - Restart torrent
   - Verify torrent reaches seeding-safe state (not `stoppedDL` / `missingFiles`)
4. Log `reality-post.json` drift snapshot
5. Optional: Remove source-side torrent views (staged cleanup, see §5.1)

**MOVE Execution:**
1. Verify source exists (file count, bytes)
2. Check for preexisting content at target — abort if target path has unexpected files
3. Copy payload to target; verify target matches expected (file count, bytes) after copy
4. For each sibling torrent:
   - Build torrent view on target
   - Libtorrent-verify donor before any qB mutation
   - Stop torrent in qBittorrent
   - Patch fastresume offline (preferred) or set location via API
   - Restart torrent
   - Verify torrent reaches seeding-safe state (not `stoppedDL` / `missingFiles`)
5. Log `reality-post.json` drift snapshot
6. Source cleanup is deferred (staged, not immediate) — see §5.1

**Post-Apply Download-State Guard:**
After any apply, the system must verify that no torrent transitioned to a downloading-like state (`stoppedDL`, `stalledDL`, `downloading`). Any such regression is a hard failure and must immediately halt further operations on the affected batch. The system should log the failure and restore affected torrents to their prior state where possible.

**BLOCKED Execution:**
- Refuses to execute
- Prints reasons from plan (e.g., "External consumer at /stash/media/movies/...")

**Offline Verify Stagnation:**
Libtorrent verification (`checking_files`) that shows no progress for longer than a configurable timeout (default: 15 minutes at 0% or no change) must be treated as a stagnation failure. The system must abort the verification, restore the torrent to its prior state, and report the stagnation. Do not wait indefinitely.

**Failure Handling:**
- If relocation fails, torrent is restarted at old location
- If any torrent relocation fails in a batch, the failed item is reported but the batch continues for other items unless the failure indicates a systemic issue
- For MOVE plans, source cleanup remains staged (not committed) on any failure
- Cleanup is never performed on apply failure

**Usage examples:** See `docs/RUNBOOK.md`.

### 8.4 qBittorrent Integration

**Client roles (permanent architecture):**
- **RT (rTorrent) is the active seeder.** RT is the operational authority for live seeding, path truth, and repair intent. RT's path is treated as canonical in all path-dispute tiebreakers.
- **qB (qBittorrent) is permanently deprecated — kept on life support.** qB is not active and will not be made active again unless there is a deliberate decision to revert. qB items are kept paused/stopped. qB is retained solely because its tag, category, and path metadata remains useful as a cross-reference during the rehome cleanup. The long-term plan is to complete the RT migration and shut qB down. All new repair work targets RT as the canonical state; qB is adjusted to match RT, not the reverse.

**qB MUST NEVER download.** Every qB torrent must be in `stoppedUP` (or `stoppedDL` transiently, pending recheck). Any qB torrent found in an active download state (`downloading`, `stalledDL`, `pausedDL`, `stoppedDL` after recheck) is a hard failure. Root causes: (a) torrent added without `skip_checking` during a race window when files were not yet stable → fix: always pass `--skip-checking` in sync scripts; (b) save_path mismatch → fix: audit with `make client-drift-audit`; (c) sync script crash left orphaned adds → fix: run `make rt-qb-mirror-drift` and recheck. Immediate remediation: recheck the affected hash in qB; it will resolve to `stoppedUP` once pieces verify.

**Path synchronization rule (§4.4 and §8.4):**
- qB and RT must mirror each other item-for-item, path-for-path.
- When qB and RT paths differ for the same hash:
  1. If only one client is on the correct placement tier (stash vs pool), repoint the other to match the correct-tier client.
  2. If both clients are on the correct placement tier but at different paths, **RT's path is canonical — repoint qB to match RT.** Do not treat this as a manual-review blocker unless there is evidence that RT's path is itself incorrect (non-canonical, missing, or structurally wrong).
  3. RT's path is deemed incorrect only if: it does not follow §4.4.3 category rules, the path does not physically exist, or there is a documented reason to prefer qB's path.
- A path change is not complete until both clients agree. Do not treat a qB-only or RT-only path change as success.

**Authentication:**
- Environment variables: `QBITTORRENT_URL`, `QBITTORRENT_USER`, `QBITTORRENT_PASS`
- Session-based authentication via Web API
- Cookie management handled automatically
- A shared qB client (`src/hashall/qbittorrent.py`) centralizes authentication, API version detection, and state normalization

**Preferred Relocation Flow (offline fastresume patch):**
1. Copy/verify donor content to target (filesystem operation, qB not involved)
2. Libtorrent-verify the donor before any qB mutation
3. Stop torrent in qBittorrent (`POST /api/v2/torrents/stop`)
4. Patch `.fastresume` file offline with correct `save_path` and `content_path`; remove `qbt-downloadPath` if present to prevent stoppedDL regression
5. Start torrent in qBittorrent (`POST /api/v2/torrents/start`)
6. Observe: verify torrent reaches `stalledUP` / `seeding` state, not `stoppedDL` / `missingFiles`

**Why Not `setLocation`?**
The qB `setLocation` API is not the preferred primary mover for dataset migration. It caused the Feb-2026 incident (`qbt-downloadPath` in fastresume → 2103 torrents stoppedDL on restart). For rehome/migration operations, offline fastresume patching provides better control and safety.

**State Normalization:**
qBittorrent API state strings differ across versions. The shared client normalizes:
- `pausedDL` / `stoppedDL` → `stoppedDL`
- `pausedUP` / `stoppedUP` → `stoppedUP`

All code that inspects torrent state must go through the shared client or its normalization layer. Hard-coding version-specific state strings is prohibited.

**qB Cache Layer:**
A local cache (`~/.cache/silo-qb/`) reduces load on the qB API for read-heavy operations (status checks, torrent list queries, triage scripts). The cache daemon is owned by silo; hashall reads the JSON files it writes via `src/hashall/qbittorrent.py`.

**Requirements:**
- Read-heavy operations (list/status queries, triage, dashboards) should use the cache by default
- Write/mutation operations (stop, start, patch) hit qB directly for immediate freshness
- The cache also stores server profile info (`app_version`, `webapi_version`, `libtorrent_version`) detected at startup

**Normalization Success Contract:**

Torrent path-normalization helpers must distinguish between:
- `path_converged`
  - qB save/content path matches expected
  - RT directory matches expected/aligned target
- `verifying`
  - path convergence is complete, but RT and/or qB are still in `checking*` or equivalent verification states
- `verified`
  - path convergence is complete and the torrent has left verification states into a terminal non-checking state
- `ambiguous_needs_review`
  - convergence or verification state cannot be proven within the configured timeout budget
- `partial_state`
  - one client moved and the other did not, or rollback/recovery was required

Default automation requirement:
- require qB canonical path match
- require RT canonical path match
- require RT to leave `checking*` before reporting strongest success

Optional stricter mode may additionally require explicit qB/RT recheck completion before final success is reported.
- If qB is temporarily unavailable or authentication is slow, the client falls back to cached data for read operations

### 8.5 Safety Features

**Pre-Execution Checks:**
- External consumer detection (BLOCKS demotion)
- File count verification
- Total bytes verification
- Source existence verification
- Target device availability
- Preexisting-target content check for MOVE plans (ABORT if target has unexpected content)
- Preflight target-view comparison for REUSE plans (ABORT if preexisting view files have different bytes)
- Libtorrent verification of donor before any qB mutation

**Execution Safety:**
- Dry-run mode for previewing changes
- Step-by-step logging with `key=value` format
- Live drift snapshots: `reality-pre.json`, `reality-post.json`, `reality-failure.json` written per apply run (compare qB state, fastresume paths, catalog rows, and filesystem existence)
- Verification after each major operation
- Fail-fast on any verification failure
- Cleanup is deferred/staged and skipped on failure
- Never destroy the last physical copy of data
- Post-apply download-state guard: halt on any new downloading-like state regression

**Concurrency Control:**
- `~/.hashall/rehome.lock` (fcntl `LOCK_EX|LOCK_NB`) prevents concurrent mutating workflows
- Attempting to run two apply operations simultaneously will fail on the lock
- Diagnostic tooling that only reads state does not require the lock

**Limitations (Current):**
- No advanced view building (assumes torrent name matches directory name for some cases)
- Rollback for MOVE plans: source cleanup is deferred; if a relocation fails mid-batch, remaining siblings in the batch may be in mixed state requiring manual triage
- Sequential batch processing (not parallel)

### 8.6 Recovery Lane

**Purpose:** Classify and repair qBittorrent items in broken or mislocated states without triggering new data movements.

**Trigger Conditions:**
- Torrents in `stoppedDL` / `missingFiles` state after a dataset migration or fastresume patch failure
- Torrents whose `save_path` / `content_path` points to a stale/old root that no longer contains their files
- Fastresume files that disagree with qB runtime state or catalog records

**Key Commands:**
- `hashall rehome qb-missing-audit` — classify `missingFiles` torrents against catalog, fastresume, and rehome history
- `hashall rehome qb-missing-remediate` — build guarded reconnect plans for classified missing-files cohorts
- `hashall rehome drift-audit --plan <plan.json>` — compare qB runtime state, fastresume paths, catalog rows, and filesystem existence for a given plan

**Recovery Principles:**
- Classify before acting: identify whether a `missingFiles` state is due to stale fastresume drift, actual data loss, or a recently completed rehome that hasn't been reconciled
- Use guarded reconnect plans (same plan-review-apply workflow as normal rehome) rather than ad-hoc API calls
- Prefer repoint-to-existing-payload over re-copy when the payload is already on the target device
- Never treat a repair success as implying the whole cohort is clean; audit the full cohort and track individually

### 8.7 Live Drift Snapshots

Each `rehome apply` run writes three structured JSON snapshots to its report directory:

| File | Written | Content |
|---|---|---|
| `reality-pre.json` | Before any mutation | qB runtime state, fastresume paths, catalog rows, filesystem existence for all plan items |
| `reality-post.json` | After apply completes | Same, plus result classifications |
| `reality-failure.json` | On abort | State at point of failure |

**Purpose:** Enable post-hoc diagnosis without relying on memory. Snapshots explain blocked/skipped rows in plain English rather than raw qB state strings. Required reading before any follow-up remediation.

**`hashall rehome drift-audit`:** Reads plan JSON and compares its targets against live qB/catalog state. Useful for proactively identifying plans whose assumptions have drifted before running apply.

---

## 9. Operational Requirements

### 9.1 Automation & Characteristics

The system must be:
- **Seamless:** Low-friction, minimal manual intervention
- **Fault-tolerant:** Recovers gracefully from failures
- **Idempotent:** Safe to re-run (repeated operations produce same result)
- **Safe by default:** Dry-run capable, explicit confirmation required
- **Auditable:** Clear logging with timestamps and reasons
- **Understandable:** System state should be clear months later

### 9.2 Safety Guarantees

**Never:**
- Destroy the last physical copy of data
- Break active media consumers (external hardlinks)
- Silently duplicate data across pools
- Skip verification steps
- Proceed when checks fail
- Create a hitchhiker (multiple payload hashes sharing one target directory)
- Select a cross-filesystem donor for hardlink view building without an explicit override
- Leave a torrent in a downloading-like state after a relocation operation
- Run concurrent mutating workflows (use the rehome lock)
- Commit source cleanup before target is verified live in qB

**Always:**
- Verify before delete (counts, sizes, optional hash spot-checks)
- Move at payload-group level (all siblings together) unless partial reconcile applies
- Preserve hardlink relationships within filesystems
- Log operations with full context including `key=value` format
- Provide dry-run for preview
- Write reality snapshots (pre/post/failure) for every apply run
- Check for preexisting target content before MOVE operations
- Libtorrent-verify the donor before any qB mutation
- Run the post-apply download-state guard before declaring success
- Stage source cleanup rather than deleting immediately

### 9.3 Idempotency

**Scanning:**
- Rescanning same path is safe (incremental update)
- Unchanged files skip rehashing (mtime + size check)
- Deletions are scoped to scan root (no false deletions)

**Rehoming:**
- Applying the same plan multiple times is safe (checks current state before each operation)
- If payload already on target, becomes reconcile-only (`rehome_reconcile_only`)
- If some torrents already relocated and others not, applies partial reconcile (`rehome_reconcile_subset`) rather than failing or re-processing already-good items
- Staged cleanup directories survive re-apply without double-deletion

**Deduplication:**
- Re-running link execution on same duplicates is safe (checks if already linked)
- Already-linked files skip re-linking

---

## 10. Terminology

**ATM (Automatic Torrent Management):** qBittorrent feature that automatically moves torrents to category save paths when categories change. Disabled by cross-seed for precise control. Rehomed torrents must have their ATM category save path consistent with the target device to prevent auto-relocation back to stash.

**Bind Mount:** Linux mount that makes a directory accessible at another location. `/data/media` is a bind mount to `stash/media`, so both paths reference the same filesystem.

**Canonical Path:** The real filesystem path after resolving all symlinks and bind mounts. Used to ensure consistent device_id detection and prevent duplicate scanning.

**Cross-seed:** Open-source tool that automatically finds and injects cross-seeds (same content from different trackers) for existing torrents. Creates hardlinks in linkDirs.

**Demotion:** Moving payloads from warm storage (stash) to cold storage (pool). Only safe when no external consumers exist.

**Device ID:** Linux kernel identifier for a filesystem/device. Used to enforce hardlink boundaries (hardlinks only work within same device_id).

**External Consumer:** A hardlink outside the seeding domain, indicating content is used by \*arr applications. Blocks demotion to pool.

**fast-hash:** Optimization technique that computes a quick hash from partial file content for rapid initial scanning. Full hash computed only for changed files.

**Filesystem UUID:** Persistent identifier for a ZFS dataset/filesystem. Remains stable across reboots, unlike device_id which may change.

**Hardlink:** Multiple directory entries (paths) pointing to the same inode (file data on disk). Zero additional disk usage. Only works within same filesystem.

**Incremental Scan:** Rescan that skips unchanged files (based on mtime + size check), resulting in 10-100x speedup over initial scan.

**Inode:** Linux kernel data structure representing a file on disk. Multiple paths can reference the same inode (hardlinks).

**Payload:** The on-disk content a torrent points to. Single-file torrent = that file; multi-file torrent = directory tree. Identity is payload_hash.

**Payload Hash:** SHA256 of sorted `(path, size, sha256)` tuples. Uniquely identifies content independent of torrent metadata. Payload hash is `NULL` until all file-level SHA256s are present.

**Payload Siblings:** Multiple torrents (different infohashes) with identical payload_hash. Examples: v1 vs v2, different piece sizes, different trackers.

**Payload-Group:** The set of sibling torrents that share a payload_hash. Exact-content unit for identity and many rehome operations.

**Sibling Payload Group:** The broader placement unit used for stash-vs-pool decisions. May include non-duplicate payloads that mostly share inodes on the same filesystem, or would do so if co-located.

**Promotion:** Moving payloads from cold storage (pool) to warm storage (stash). Only occurs when payload already exists on stash (reuse-only, no blind copy).

**Seeding Domain:** Paths where torrent data resides for seeding. Canonical roots are `/stash/media/torrents/seeding/` and `/pool/media/torrents/seeding/`; legacy migration roots may still participate temporarily. Excludes media library paths and `*/media/torrents/orphans`.

**`~noHL` Tag:** qBittorrent tag applied by qbit_manage indicating "no hardlinks". Torrents with this tag have no external consumers (not hardlinked to media libraries). Prime candidates for demotion.

**Unified Catalog:** Single database (`~/.hashall/catalog.db`) that tracks all files across all storage devices using stable fs_uuid-bound files tables plus `files_<device_id>` compatibility views.

**Dataset Migration:** The process of moving seeding content between ZFS datasets within the same pool (e.g., `pool-data` → `pool-media`). Unlike stash↔pool rehoming, this is a same-pool operation. Uses the `hashall rehome relocate-plan` / `rehome apply` workflow rather than `rehome auto`.

**De-hitchhike:** The process of splitting a hitchhiker group (multiple payload hashes sharing a single target directory) into proper per-hash unique target roots. Legacy hitchhiker groups persist until explicitly de-hitchhiked; new operations must not create new hitchhikers.

**Drift Policy:** Controls how the scanner handles files whose size+mtime appear unchanged. `metadata` trusts the cached hash; `quick` rechecks the quick hash; `full` recomputes the full SHA256. See §7.3.

**Fastresume Patch (offline):** Modifying qBittorrent's `.fastresume` files while qB is stopped, to update `save_path`/`content_path` without using the `setLocation` API. The preferred relocation mechanism for dataset migration to avoid `qbt-downloadPath` regressions.

**Hitchhiker:** An anti-pattern where two or more torrents with different payload content share a single on-disk target directory (N→1 mapping). Prohibited for new operations; existing legacy hitchhikers must be tracked and eventually de-hitchhiked.

**Pool-Data / Pool-Media:** The two active ZFS datasets within the `/pool` pool. `pool-data` is the legacy seeding root being migrated from; `pool-media` is the active target. They have distinct `fs_uuid`s and `device_id`s; hardlinks do not cross between them.

**`qbt-downloadPath`:** A field in qBittorrent's `.fastresume` files that, if set to a path not visible to qB, causes `stoppedDL` regression on restart. Must be removed or corrected during fastresume patching.

**Reality Snapshot:** Structured JSON file (`reality-pre/post/failure.json`) capturing qB runtime state, fastresume paths, catalog rows, and filesystem existence at a specific point during a `rehome apply` run. Written per apply run for auditability and post-hoc diagnosis.

**`rehome_reconcile_only`:** Classification for a re-applied plan where all torrents are already on the target paths and verified. No relocation is performed; only catalog is updated.

**`rehome_reconcile_subset`:** Classification for a re-applied plan where some torrents are already on target and others are not. The already-good subset is reconciled into the catalog; remaining items are processed normally.

**`_rehome-unique/<hash>/`:** A path convention for per-item payload trees when a shared target root would create a hitchhiker. Used when two payload families would otherwise collide on the same directory name.

**Seed-Root State Contract:** The file `~/.hashall/seed-root-state.json` that publishes which seeding roots are active, legacy, or mirror roots. Authoritative source for external tools that need to know valid seeding paths.

**Staged Cleanup:** Source cleanup that stages the source root into `.rehome-cleanup-stage/<payload_hash>/...` after a successful move, observes qB state, and only deletes after the target is confirmed live. Automatic restoration on qB regression. See §5.1.

**View (Torrent View):** A torrent-specific payload tree composed from a canonical donor payload, normally via hardlinks. Multiple views can preserve distinct qB item layout semantics while reusing the same physical bytes with zero additional disk usage. Each view must have a unique root per payload hash (no hitchhikers).

**Tracker Key:** The short identifier for a tracker as defined in the traktor tracker registry (`tracker-registry.yml`). This is the YAML top-level key (e.g. `darkpeers`, `fearnopeer`, `abtorrents`). It is the authoritative identifier used for: qB category names, seeding path subdirectories, qbit_manage tags, and rTorrent labels. Resolve announce URLs to tracker keys via the `tracker_url_pattern` field in the registry. See §4.4.4.

**Canonical Path:** The one correct on-disk path for a torrent item, derived from: `<seeding-root>/<category>/<item-payload-name>`. Category is determined by item origin (see §4.4.3). A torrent's current path is non-canonical if it does not match this formula — such paths are legacy artifacts requiring repair. See §4.4.

---

## 11. Implementation Status

### 11.1 Completed ✅

**hashall (Catalog System) - v0.8.0:**
- ✅ Unified catalog model with filesystem-bound files tables and compatibility views
- ✅ Filesystem UUID tracking (persistent across reboots)
- ✅ Incremental scanning with configurable drift policy (`metadata` / `quick` / `full`)
- ✅ SHA256 file hashing (SHA1 legacy retained); `--hash-mode fast|full|upgrade`
- ✅ Parallel scanning (multi-threaded hashing, 4-5x faster)
- ✅ Scoped deletion detection
- ✅ Hardlink tracking (inode + device_id)
- ✅ Symlink/bind mount safe scanning (canonical path resolution)
- ✅ Device management CLI (list, show, alias) using stable `fs_uuid`-bound aliases
- ✅ Statistics and audit trail
- ✅ Payload identity tracking
- ✅ qBittorrent torrent sync (payload mapping)
- ✅ E2E integration tests
- ✅ Collision detection with auto-upgrade logic
- ✅ Fast hash support for rapid initial scanning
- ✅ Link deduplication workflow (analyze → plan → show/list → execute)
- ✅ qB shared cache layer (`src/hashall/qb_cache.py`, `bin/qb-cache-agent.py`, `bin/qb-cache-daemon.py`)
- ✅ qB server profile detection and state alias normalization (centralized in `src/hashall/qbittorrent.py`)
- ✅ Exponential backoff on consecutive qB API fetch failures

**rehome (Orchestration System):**
- ✅ Demotion planning (stash → pool)
- ✅ Demotion execution (REUSE and MOVE flows)
- ✅ Promotion planning (pool → stash, reuse-only)
- ✅ Promotion execution (REUSE flow only, no blind copy)
- ✅ Root-to-root relocation planner (`hashall rehome relocate-plan`) for dataset migration
- ✅ External consumer detection (blocks unsafe demotions)
- ✅ Offline fastresume patching (primary qB relocation mechanism)
- ✅ Libtorrent verification before mutation
- ✅ Batch operations (by payload-hash or tag)
- ✅ REUSE/MOVE/BLOCK decision logic
- ✅ Partial reconcile (`rehome_reconcile_only`, `rehome_reconcile_subset`)
- ✅ Preflight target-view check (abort if preexisting view has different bytes)
- ✅ Preexisting-target content detection for MOVE plans
- ✅ Per-apply reality snapshots (`reality-pre/post/failure.json`)
- ✅ `hashall rehome drift-audit` proactive plan validator
- ✅ `hashall rehome qb-missing-audit` / `qb-missing-remediate` for recovery lane
- ✅ De-hitchhike invariant (per-hash unique target roots; `_rehome-unique/<hash>`)
- ✅ Staged cleanup (`hashall rehome followup --cleanup`) with automatic rollback on qB regression
- ✅ Post-apply download-state guard
- ✅ Concurrency lock (`~/.hashall/rehome.lock`)
- ✅ rsync-based copy with streaming progress for MOVE
- ✅ Dry-run mode

**Integration:**
- ✅ qbit_manage `~noHL` tag detection (advisory pre-filter; not a bypass of plan-time external consumer check)
- ✅ cross-seed linkDirs support (filesystem-aware)
- ✅ \*arr hardlink import compatibility
- ✅ `~/.hashall/seed-root-state.json` published seeding-root contract

### 11.2 In Progress 🚧

- 🚧 Subtree treehash for fast directory comparison
- 🚧 Advanced torrent view building (complex layouts, renamed files)
- 🚧 Pool dataset migration (`pool-data` → `pool-media`): `old_path_count=34`, `new_path_count=317` as of 2026-03-13 (see `docs/operations/RUN-STATE.md` for current live state)

### 11.3 Planned 📋

**hashall:**
- 📋 Web UI for browsing catalog
- 📋 Automated deduplication schedules
- 📋 Advanced filters (size, date, patterns)
- 📋 Cloud integration (S3, Backblaze)

**rehome:**
- 📋 Parallel batch processing (process multiple payloads concurrently)
- 📋 Advanced payload view building (handle renamed files, different layouts)
- 📋 Fuzzy payload matching (similar but not identical content)
- 📋 Automated rehoming schedules (e.g., demote all `~noHL` tagged torrents weekly)
- 📋 Full undo/rollback capability (currently: staged cleanup with manual fallback)
- 📋 Web UI for plan review and approval
- 📋 Offline verify stagnation detection with configurable timeout
- 📋 Explicit lock-holder diagnostics (`~/.hashall/rehome.lock`)
- 📋 Automated de-hitchhike tooling for legacy shared-root groups

**Integration:**
- 📋 Automated rehoming based on qbit_manage tags
- 📋 \*arr webhook integration (auto-promote on import)
- 📋 Notifiarr notifications for rehoming operations

---

## 12. Success Criteria

The system is successful if:

**Functional:**
- ✅ Media-linked data stays on `/stash` (external consumers preserved)
- ✅ Seed-only data can live on `/pool` (cold storage)
- ✅ Data can move back and forth without duplication (REUSE logic works)
- ✅ Sibling torrents are represented as hardlink views (space-efficient)
- ✅ Incremental scans are 10-100x faster than initial scans
- ✅ Deduplication saves measurable disk space

**Operational:**
- ✅ System "just works" with minimal manual intervention
- ✅ State remains understandable months later (clear logs, audit trail)
- ✅ Safe by default (dry-run, verification, fail-fast)
- ✅ Recoverable from failures (rollback, manual intervention paths)

**User Experience:**
- ✅ Solo home hobbyist can operate the system
- ✅ CLI agents can understand and extend the system
- ✅ Documentation is accurate and complete
- ✅ Workflows are clear and repeatable

---

## Document History

**Version 1.6 (2026-05-19):**
- §4.4.3: Clarified that Prowlarr display-name dirs (e.g. `Darkpeers (API)/`) are canonical for cross-seed items alongside short registry-key form; do not rename — cross-seed re-creates them on injection
- §6.3: Added Type A vs Type B hitchhiker taxonomy (content-level vs path-level; different detection and remediation); noted `hitchhiker.py` detects Type B only
- (BACKLOG) Canonical Tree Normalization: replaced thin placeholder with full taxonomy of non-canonical path classes 1–5 (counts, causes, remediation), class 6 acceptance note, safe remediation order, structural rename deferred list

**Version 1.5 (2026-05-19):**
- §2.1: Added explicit note distinguishing `/pool/data/seeds` (cross-seed scan dataDir, not a rehome destination) from `/pool/media/torrents/seeding` (active pool seeding root); flagged stale `default_dest_root` defaults
- §4.2.1: Fixed duplicate §4.2.1 section numbering (renamed "Broader Content Inventory Requirement" to §4.2.2); added concept-clarification table distinguishing exact-hash siblings (catalog identity unit) from broader inode-sharing group (placement unit); added key rule that broader-group members with different `payload_hash` are handled independently
- §4.4.2: Added seeding root selection rule (pool-eligible → pool root, stash-anchored → stash root); added path-preservation-on-rehome clause (seeding-relative path preserved verbatim across roots)
- §5.1.1 (new): Documented cross-filesystem byte-copy requirement — stash→pool MOVE is always rsync, never hardlink or rename; stash source not removed until pool copy verified and clients confirmed seeding
- §5.1.2 (new): Documented primary mover selection rule for inode-sharing group rehome (6-priority ordered rule + disqualifiers); documented hardlink construction phase; clarified target pool path model (unique canonical trees per torrent, hardlinked — not shared-directory REUSE)
- §5.3: Clarified payload-group definition as exact-hash siblings only; distinguished from broader inode-sharing group; noted that different-`payload_hash` members are planned independently but linked by §5.1.2 hardlink optimization

**Version 1.4 (2026-05-19):**
- §4.1.1: Added hardlink threshold rationale (any single hardlink mandates stash; qbit_manage ~noHL alignment)
- §4.4.4: Replaced "Prowlarr tracker name" with traktor tracker registry key as authoritative source; documented registry structure and search path
- §8.4: Updated qB role from "transitional mirror" to "permanently deprecated, kept on life support"; clarified RT-only repair direction
- §10: Added Tracker Key and Canonical Path terminology entries

**Version 1.3 (2026-05-19):**
- Added §4.4: Canonical Seeding Path Specification — payload uniqueness definition, path formula, category rules by origin, historical category evolution, path uniqueness requirement
- Updated §8.4: made RT active-seeder / qB passive-mirror roles explicit; added path-dispute tiebreaker rule (RT wins when both on correct tier)

**Version 1.2 (2026-04-18):**
- (prior entry, content unchanged)

**Version 1.1 (2026-03-18):**
- Corrected pool topology: added `pool-data`/`pool-media` ZFS dataset distinction and active dataset migration
- Added §2.5 (Seeding Domain Definition) and §2.6 (Seed-Root State Contract)
- Updated qB relocation approach from API setLocation to offline fastresume patch as preferred method
- Added `~noHL` advisory-only note; plan-time external consumer check is authoritative
- Added canonicalization requirement to external consumer detection (§4.3)
- Added preexisting-target content check requirement for MOVE (§5.1)
- Added staged cleanup model (§5.1)
- Added partial reconcile handling for split-sibling groups (§5.3)
- Added ATM interaction requirement (§5.3)
- Added hitchhiker invariant and cross-filesystem donor prohibition (§6.3)
- Added drift policy modes documentation (§7.3)
- Updated §8 extensively: fastresume approach, preflight target-view check, stagnation requirement, download-state guard, qB cache layer, state normalization, plan path correction, catalog freshness requirement, NULL hash planning rule
- Added §8.6 Recovery Lane
- Added §8.7 Live Drift Snapshots
- Updated §9.2 safety guarantees with new Never/Always items
- Updated §9.3 idempotency to reflect partial reconcile behavior
- Updated §10 terminology with 14 new terms
- Updated §11 implementation status (hashall 0.8.0, many new completed items)
- Updated §11.3 planned items

**Version 1.0 (2026-02-02):**
- Complete rewrite from user-derived requirements draft
- Added implementation status and architecture details
- Documented qbit_manage `~noHL` tag logic
- Specified SHA256 as hash algorithm standard
- Added bind mount and path mapping documentation
- Consolidated scattered cross-seed information
- Added comprehensive terminology glossary
- Restructured for CLI agent usability

**Previous Version (Draft):**
- User-stated intent only
- No implementation details
- Path inconsistencies
- Terminology undefined
