# Seed Data Management System - Requirements & Implementation

**Version:** 1.0 (Living Document)
**Last Updated:** 2026-02-05
**Status:** Active Development - Core features implemented, refinements in progress

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
2. [Storage Architecture](#2-storage-architecture)
3. [Application Stack](#3-application-stack)
4. [Core Requirements](#4-core-requirements)
5. [Data Movement (Rehoming)](#5-data-movement-rehoming)
6. [Deduplication](#6-deduplication)
7. [Catalog System (hashall)](#7-catalog-system-hashall)
8. [Orchestration System (rehome)](#8-orchestration-system-rehome)
9. [Operational Requirements](#9-operational-requirements)
10. [Terminology](#10-terminology)
11. [Implementation Status](#11-implementation-status)
12. [Success Criteria](#12-success-criteria)

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

**Seeding Domain (Cold - Pool):**
```
/pool/data/cross-seed/                  (cross-seed links on pool)
/pool/data/RecycleBin/                  (qbit_manage recycle bin)
/pool/data/orphaned_data/               (orphaned files)
```

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

**Seeding Domain Paths:**
- Primary: `/stash/media/torrents/seeding/` (or `/data/media/torrents/seeding/` via bind mount)
- Pool: `/pool/data/cross-seed/`

**External Consumer Paths (Media Libraries):**
- `/stash/media/books/`
- `/stash/media/movies/`
- `/stash/media/shows/`
- `/stash/media/downloads/`
- (Any path outside the seeding domain)

**Rule: Must Stay on Stash**

A torrent's data **must remain on `/stash`** if:
- Any inode associated with the torrent has hardlink children in external consumer paths
- Example:
  ```
  Torrent file: /stash/media/torrents/seeding/radarr/Movie.2024/video.mkv (inode 1234)
  Hardlink:     /stash/media/movies/Movie (2024)/video.mkv (inode 1234)

  Result: MUST stay on stash (external consumer exists)
  ```

**Rule: Eligible for Pool Migration**

A torrent's data is **eligible to move to `/pool`** if:
- All hardlinks are siblings within the seeding domain only
- No hardlinks exist in external consumer paths
- Typically identified by `~noHL` tag from qbit_manage

### 4.2 Payload Identity

**Definition:** A payload is the on-disk content tree a torrent points to:
- Single-file torrent → that file
- Multi-file torrent → directory tree

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

### 4.3 External Consumer Detection

**Definition:** A file has an **external consumer** if any hardlink points to a path outside the seeding domain.

**Detection Method:**
1. For each file in torrent payload:
   - Get inode + device_id
   - Find all paths with matching inode + device_id
   - Check if any path is outside seeding domain roots
2. If ANY file has external consumer → BLOCK demotion

**Example:**
```
Seeding domain: /stash/media/torrents/seeding/

File: /stash/media/torrents/seeding/radarr/Movie.2024/video.mkv (inode 5678)
Hardlinks:
  ✅ /stash/media/torrents/seeding/radarr/Movie.2024/video.mkv (inside domain)
  ❌ /stash/media/movies/Movie (2024)/video.mkv (outside domain - EXTERNAL CONSUMER)

Result: BLOCKED (cannot demote because external consumer exists)
```

**Automated Detection:** qbit_manage's `~noHL` tag indicates no external consumers detected.

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
2. Move payload root directory (stash → pool)
3. Verify target matches expected file count/bytes
4. For each sibling torrent:
   - Build torrent view on pool (hardlinks to payload)
   - Pause torrent in qBittorrent
   - Relocate torrent to pool path via API
   - Resume torrent
   - Verify torrent can access files
5. Verify stash source is removed

**Safety:** Demotion is BLOCKED if external consumers exist. No silent breakage of media library links.

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

**Definition:** A payload-group is the set of sibling torrents that share a payload_hash.

**Rehoming Principle:** All siblings in a payload-group are rehomed together as a unit.

**Why?**
- Prevents split scenarios (some siblings on stash, others on pool)
- Single source of truth for payload location
- Simplifies reasoning about system state

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
Canonical payload: /pool/data/Movie.2024/
Torrent A view:    /pool/data/cross-seed/Aither (API)/Movie.2024/
                   └── (hardlinks to canonical payload)
Torrent B view:    /pool/data/cross-seed/Darkpeers (API)/Movie.2024/
                   └── (hardlinks to canonical payload)

Result: Distinct per-torrent payload trees on disk, with shared physical bytes when hardlinks are possible
```

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
   - If unchanged → skip hash computation, use cached hashes
   - If changed → recompute SHA256, update catalog
   - If new → compute SHA256, insert into catalog
3. Detect deletions (files in catalog but not on filesystem, scoped to scan root)
4. Performance: ~500-1000 files/sec (sequential), ~2000-5000 files/sec (parallel)

**Result: 10-100x speedup on rescans**

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

**CLI usage:** See `docs/tooling/CLI-OPERATIONS.md` (payload commands).

---

## 8. Orchestration System (rehome)

### 8.1 Overview

**Tool:** `rehome` (external orchestration tool, not part of hashall core)

**Purpose:** Safely orchestrate payload movement between stash and pool

**Why it matters:** Rehome is the core workflow this system is built to support. Hashall’s catalog + payload identity are required inputs to rehome’s plan/apply logic.

**Current Version:** Stage 5 (Demotion + Promotion with qBittorrent integration)

**Capabilities:**
- Demotion planning and execution (stash → pool)
- Promotion planning and execution (pool → stash, reuse-only)
- External consumer detection (blocks unsafe demotions)
- qBittorrent API integration (pause/relocate/resume)
- Batch operations (by payload-hash or qBittorrent tag)
- REUSE/MOVE/BLOCK decision logic
- Dry-run mode for safety

**Architecture:** Plan → Review → Apply workflow

**Detailed Usage:** See `docs/tooling/REHOME-RUNBOOK.md`

### 8.2 Planning Phase

**Command:** `rehome plan` (details in `docs/tooling/REHOME-RUNBOOK.md`)

**Modes:** single-torrent, batch by payload hash, batch by tag.

**Directions:** demote (stash → pool), promote (pool → stash, reuse-only).

**Inputs:**
- Torrent hash, payload hash, or tag (mutually exclusive)
- `--seeding-root`: Path(s) defining seeding domain (can specify multiple)
- `--stash-device`: Device ID for stash (e.g., 50)
- `--pool-device`: Device ID for pool (e.g., 49)
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

**Output:** Plan JSON file (e.g., `rehome-plan-abc123de.json`)

### 8.3 Application Phase

**Command:** `rehome apply <plan_file>` (details in `docs/tooling/REHOME-RUNBOOK.md`)

**Modes:**
- `--dryrun`: Preview actions without making changes
- `--force`: Execute the plan (mutually exclusive with --dryrun)

**Optional Cleanup Flags (opt-in, disabled by default):**
- `--cleanup-source-views`: Remove source-side torrent views after relocation
- `--cleanup-empty-dirs`: Remove empty directories under seeding roots

**REUSE Execution:**
1. Verify existing payload on target device
2. For each sibling torrent:
   - Build torrent view on target (hardlinks to payload)
   - Pause torrent in qBittorrent
   - Set location to target path via API
   - Resume torrent
   - Verify torrent can access files (spot-check)
3. Optional: Remove source-side torrent views (if cleanup flags enabled)

**MOVE Execution:**
1. Verify source exists (file count, bytes)
2. Move payload root directory (stash → pool or vice versa)
3. Verify target matches expected (file count, bytes)
4. For each sibling torrent:
   - Build torrent view on target
   - Pause torrent in qBittorrent
   - Set location to target path via API
   - Resume torrent
   - Verify torrent can access files
5. Verify source is removed

**BLOCKED Execution:**
- Refuses to execute
- Prints reasons from plan (e.g., "External consumer at /stash/media/movies/...")

**Failure Handling:**
- If relocation fails, torrent is resumed at old location
- If any torrent relocation fails, entire operation aborts
- For MOVE plans, payload is rolled back to source on failure
- Cleanup is skipped on any relocation failure

**Usage examples:** See `docs/tooling/REHOME-RUNBOOK.md`.

### 8.4 qBittorrent Integration

**Authentication:**
- Environment variables: `QBITTORRENT_URL`, `QBITTORRENT_USER`, `QBITTORRENT_PASS`
- Session-based authentication via Web API
- Cookie management handled automatically

**Relocation Flow:**
1. Pause torrent: `POST /api/v2/torrents/pause`
2. Set location: `POST /api/v2/torrents/setLocation`
3. Resume torrent: `POST /api/v2/torrents/resume`
4. Verify new location matches expected path

**Why Pause/Resume?**
- Ensures qBittorrent isn't accessing files during relocation
- Prevents partial state (files moved but qBittorrent still checking old location)
- Clean state transition

### 8.5 Safety Features

**Pre-Execution Checks:**
- External consumer detection (BLOCKS demotion)
- File count verification
- Total bytes verification
- Source existence verification
- Target device availability

**Execution Safety:**
- Dry-run mode for previewing changes
- Step-by-step logging with `key=value` format
- Verification after each major operation
- Fail-fast on any verification failure
- Cleanup is opt-in and skipped on failure
- Never destroy the last physical copy of data

**Limitations (Current):**
- No advanced view building (assumes torrent name matches directory name)
- Limited rollback (MOVE plans attempt rollback on relocation failure; other failures require manual recovery)
- Sequential batch processing (not parallel)

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

**Always:**
- Verify before delete (counts, sizes, optional hash spot-checks)
- Move at payload-group level (all siblings together)
- Preserve hardlink relationships within filesystems
- Log operations with full context
- Provide dry-run for preview

### 9.3 Idempotency

**Scanning:**
- Rescanning same path is safe (incremental update)
- Unchanged files skip rehashing (mtime + size check)
- Deletions are scoped to scan root (no false deletions)

**Rehoming:**
- Applying same plan multiple times is safe (checks current state)
- If payload already on target, becomes no-op
- If torrents already relocated, verified and continued

**Deduplication:**
- Re-running link execution on same duplicates is safe (checks if already linked)
- Already-linked files skip re-linking

---

## 10. Terminology

**ATM (Automatic Torrent Management):** qBittorrent feature that automatically moves torrents to category save paths when categories change. Disabled by cross-seed for precise control.

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

**Payload-Group:** The set of sibling torrents that share a payload_hash. Rehomed together as a unit.

**Promotion:** Moving payloads from cold storage (pool) to warm storage (stash). Only occurs when payload already exists on stash (reuse-only, no blind copy).

**Seeding Domain:** Paths where torrent data resides for seeding. Primary: `/stash/media/torrents/seeding/`, Pool: `/pool/data/cross-seed/`. Excludes media library paths.

**`~noHL` Tag:** qBittorrent tag applied by qbit_manage indicating "no hardlinks". Torrents with this tag have no external consumers (not hardlinked to media libraries). Prime candidates for demotion.

**Unified Catalog:** Single database (`~/.hashall/catalog.db`) that tracks all files across all storage devices using stable fs_uuid-bound files tables plus `files_<device_id>` compatibility views.

**View (Torrent View):** A torrent-specific payload tree composed from a canonical donor payload, normally via hardlinks. Multiple views can preserve distinct qB item layout semantics while reusing the same physical bytes with zero additional disk usage.

---

## 11. Implementation Status

### 11.1 Completed ✅

**hashall (Catalog System) - v0.5.0+:**
- ✅ Unified catalog model with filesystem-bound files tables and compatibility views
- ✅ Filesystem UUID tracking (persistent across reboots)
- ✅ Incremental scanning (10-100x speedup on rescans)
- ✅ SHA256 file hashing (SHA1 legacy retained)
- ✅ Parallel scanning (multi-threaded hashing, 4-5x faster)
- ✅ Scoped deletion detection
- ✅ Hardlink tracking (inode + device_id)
- ✅ Symlink/bind mount safe scanning (canonical path resolution)
- ✅ Device management CLI (list, show, alias)
- ✅ Statistics and audit trail
- ✅ Payload identity tracking
- ✅ qBittorrent torrent sync (payload mapping)
- ✅ E2E integration tests
- ✅ Collision detection with auto-upgrade logic
- ✅ Fast hash support for rapid initial scanning
- ✅ Link deduplication workflow (analyze → plan → show/list → execute)

**rehome (Orchestration System) - Stage 5:**
- ✅ Demotion planning (stash → pool)
- ✅ Demotion execution (REUSE and MOVE flows)
- ✅ Promotion planning (pool → stash, reuse-only)
- ✅ Promotion execution (REUSE flow only, no blind copy)
- ✅ External consumer detection (blocks unsafe demotions)
- ✅ qBittorrent API integration (pause/relocate/resume)
- ✅ Batch operations (by payload-hash or tag)
- ✅ REUSE/MOVE/BLOCK decision logic
- ✅ Verification and safety checks
- ✅ Dry-run mode
- ✅ Guarded cleanup (opt-in flags)

**Integration:**
- ✅ qbit_manage `~noHL` tag detection
- ✅ cross-seed linkDirs support (filesystem-aware)
- ✅ \*arr hardlink import compatibility

### 11.2 In Progress 🚧

- 🚧 Subtree treehash for fast directory comparison
- 🚧 Advanced torrent view building (complex layouts, renamed files)

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
- 📋 Undo/rollback capability
- 📋 Web UI for plan review and approval

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
