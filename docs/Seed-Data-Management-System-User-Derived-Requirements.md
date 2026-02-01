# ZFS-Based qBittorrent Seed Data Management System

## User-Derived Requirements (Draft)

---

## 1. Problem Statement

The user operates a Linux-based media and torrenting system using:

- qBittorrent with Auto Torrent Management (ATM)
- cross-seed
- \*arr applications (Radarr, Sonarr, Lidarr, Readarr, etc.)
- ZFS-backed storage pools

The system must intelligently manage torrent seed data across two ZFS pools in a way that:

- Preserves hardlink-based space savings
- Supports long-term seeding of non-library content
- Allows data to move fluidly between pools as usage changes
- Avoids duplication across filesystems
- “Just works” with minimal manual intervention

---

## 2. Storage Topology (As Stated)

### ZFS Pools

- **/stash/**
  - Hosts active media libraries
  - Hardlink source for \*arr-managed content
  - Canonical location for data actively used by media consumers

- **/pool/**
  - Hosts seed-only or cold data
  - Long-term seeding, orphaned, or staging content
  - No \*arr consumers

### Key Constraint

- **Hardlinks only work within the same ZFS dataset/filesystem**
- Data that must be hardlinked to media libraries must reside on `/stash`

---

## 3. Current qBittorrent Behavior

- ATM is used for **all torrents except cross-seed**
- cross-seed injects torrents with:
  - Specific save paths
  - Category `cross-seed`
- ATM automatically moves torrents based on category
- Some torrents are:
  - Hardlinked into media libraries (zero additional storage cost)
  - Not part of any media library but still desirable to seed

---

## 4. Core Classification Rules (User-Defined)

### 4.1 Hardlink-Based Residency Rule

A torrent’s data **must remain on `/stash`** if:

- Any inode associated with the torrent has **hardlink children outside**  
  `/data/media/torrents/seeding/`

A torrent’s data is **eligible to move to `/pool`** if:

- All hardlinks are **internal siblings** within  
  `/data/media/torrents/seeding/`
- There are **no external consumers** (movies/, shows/, books/, etc.)

### 4.2 Sibling Definition

- “Siblings” = multiple torrent directories referencing the same payload
- Sibling-only hardlinks do **not** justify staying on `/stash`

---

## 5. Desired Data Movement Semantics

### 5.1 Demotion (stash → pool)

When a torrent (or payload group):

- Has no external hardlink children
- Is tagged (e.g. `~noHL`) or otherwise identified as seed-only

Then:

1. Check whether identical data already exists on `/pool`
2. If it exists:
   - Do **not** duplicate data
   - Stand up torrent directories as **hardlink views** on `/pool`
3. If it does not exist:
   - Move the payload **once** to `/pool`
   - Recreate all sibling torrents as hardlinks to that payload
4. Relocate torrents in qBittorrent via API
5. Remove old `/stash` copies only after verification

### 5.2 Promotion (pool → stash)

Promotion should occur **only if the data already exists on `/stash`**.

- No blind copying from `/pool` to `/stash`
- If stash already contains the payload:
  - Stand up torrent directories as hardlink views on `/stash`
  - Relocate torrents back to stash paths
- Optional cleanup of redundant pool copies

---

## 6. Duplicate & Identity Detection

### 6.1 Short-Term Reality

- In the short term, identical data **may exist on both pools**
- The system must detect this and avoid duplication during moves

### 6.2 Long-Term Goal

- Identical payloads should not exist on both filesystems simultaneously

---

## 7. Hashing & Cache Requirements

The user requires a **pre-scanned, searchable cache** of filesystem content:

- Built across **both `/stash` and `/pool`**
- Periodically updated
- Fast to query during move decisions

### Desired Properties

- Per-file hashes
- Subtree / payload identity hashes
- Ability to detect:
  - Exact duplicates
  - Same content with different directory layouts
- Cache-backed decisions (no repeated full rescans)

### Existing Work

- Preliminary tools exist:
  - `hashall`
  - `jdupster` / jdupes-based workflows
- Duplicate nodes should share:
  - Identical subtree hashes
  - Identical content identity

---

## 8. Hardlink Reconstruction Requirements

When creating or recreating torrent directories (“views”):

- Hardlinks must be created **within the target filesystem**
- File mapping must be:
  - File-centric, not directory-blind
  - Capable of handling renamed roots or differing layouts
- Behavior should mirror cross-seed’s linking logic where applicable

---

## 9. cross-seed Integration Requirements

- cross-seed must be able to:
  - Scan data from **both `/stash` and `/pool`** in a single run
- Hardlinks created by cross-seed must:
  - Stay within the same filesystem as the source data
- cross-seed should **not** be responsible for stash vs pool placement decisions
- Placement is determined by an external controller

---

## 10. Automation & Operational Characteristics

The system should be:

- Seamless and low-friction
- Fault-tolerant
- Idempotent (safe to re-run)
- Safe by default (dry-run capable)
- Minimal manual babysitting

### Operational Guarantees

- Never destroy the last physical copy of data
- Never break active media consumers
- Verify before delete (counts, sizes, optional hash spot-checks)
- Moves occur at **payload-group level**, not individual torrents

---

## 11. Controller Expectations (Implicit)

Although not yet implemented, the user’s statements imply a controller that:

- Uses cached identity data
- Uses qBittorrent API for relocation
- Uses jdupes-style hardlink creation
- Enforces the stash/pool residency rules
- Can evolve from stop-gap scripts into a unified system

---

## 12. Non-Goals / Constraints

- No cross-filesystem hardlinks
- No reliance on cross-seed for placement logic
- No speculative promotion that copies data unnecessarily
- No silent duplication across pools

---

## 13. Definition of “Success”

The system is successful if:

- Media-linked data stays on `/stash`
- Seed-only data lives on `/pool`
- Data can move back and forth without duplication
- Sibling torrents are represented as hardlink views
- The system “just works” and remains understandable months later

---

## Status

- This document reflects **only user-stated intent**
- No additional assumptions or design choices added
- Ready to drive:
  - Architecture decisions
  - CLI agent tasking
  - Incremental implementation
