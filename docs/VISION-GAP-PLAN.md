# Vision Gap Audit and Execution Plan
**Date:** 2026-02-06
**Scope:** Codebase audit against `docs/REQUIREMENTS.md`

## Summary
This repo already delivers the core catalog, incremental scanning, payload identity, and basic rehome workflows. The remaining gaps are mostly about **path canonicalization**, **payload correctness**, and **rehome safety/atomicity**. These gaps can lead to incorrect external-consumer detection, duplicate payloads across pools, and partial or unsafe rehome operations.

## Missing Items to Meet the Vision

### Critical Gaps (Correctness/Safety)
1. **Canonical path + bind mount handling is not implemented in scanning.**
Evidence: `src/hashall/scan.py` stores paths relative to mount points and does not de-duplicate bind-mounted paths; `docs/tooling/symlinks-and-bind-mounts.md` specifies a different algorithm.
Impact: Duplicate catalog entries for the same inode, incorrect payload hashes, and false negatives in external consumer detection.

2. **Payload building uses absolute root paths, but scanned file paths are stored relative to mount points.**
Evidence: `src/hashall/payload.py` queries `files_<device_id>` by `root_path` without converting to relative; `src/hashall/scan.py` writes relative paths.
Impact: `payload_hash` is frequently empty in real data, breaking sibling detection and rehome decisions.

3. **External consumer detection can silently fail with bind-mount paths and ignores file status.**
Evidence: `src/rehome/planner.py` returns an empty list when `root_path` is not under the device mount point; queries do not filter `status='active'`.
Impact: Demotion can be incorrectly allowed, potentially breaking media-library hardlinks.

4. **Rehome view building is not implemented.**
Evidence: `src/rehome/executor.py` logs “build_view” but does not construct hardlink views, and assumes torrent name equals payload root.
Impact: Rehome fails for torrents with renamed top-level directories, differing layouts, or cross-seeds.

5. **Target path mapping is hard-coded.**
Evidence: `src/rehome/planner.py` uses `/pool/torrents/content/<name>` for MOVE.
Impact: Rehome cannot honor real pool layout (e.g., `/pool/data/...`) or tracker/category-specific roots.

6. **Rehome is not atomic across sibling torrents.**
Evidence: `src/rehome/executor.py` relocates siblings sequentially and does not roll back already-moved torrents when a later one fails.
Impact: Violates the payload-group invariant; leaves siblings split across devices.

7. **REUSE keeps duplicate canonical payloads by design.**
Evidence: `_execute_reuse` logs manual cleanup and `_cleanup_source_views` explicitly avoids deleting canonical roots in `src/rehome/executor.py`.
Impact: Violates the “no duplicate payloads across devices” goal.

8. **Rehome allows MOVE when payload_hash is missing.**
Evidence: `_payload_exists_on_pool` returns `None` when payload_hash is `None`, leading to MOVE in `src/rehome/planner.py`.
Impact: Can create duplicates or move payloads without confirmed identity.

9. **Torrent root path resolution does not use `content_path`.**
Evidence: `src/hashall/qbittorrent.py` computes root path from `save_path` + torrent name or file name only.
Impact: Fails for renamed content or non-standard layouts, breaking payload mapping and rehome.

### Important Gaps (Feature Completeness)
10. **Cross-device duplicate detection is missing.**
Evidence: `hashall link analyze` requires `--device` and no `--cross-device` path exists in `src/hashall/cli.py`.
Impact: No visibility into duplicates across stash/pool, reducing safe consolidation.

11. **Treehash is legacy-only and not integrated with the unified catalog.**
Evidence: `src/hashall/treehash.py` operates on the deprecated `files` table.
Impact: No subtree or root integrity checks for the current model.

12. **Rehome audit trail is not persisted.**
Evidence: `src/rehome/executor.py` logs to stdout without timestamps or DB-backed history.
Impact: Reduced auditability compared to requirement “understandable months later.”

13. **No guardrails for scan coverage before rehome.**
Evidence: `src/rehome/planner.py` does not validate that library roots or external consumer paths were scanned.
Impact: External-consumer detection can be incomplete, leading to unsafe demotion.

14. **Symlinked files are not explicitly skipped.**
Evidence: `_hash_file_worker` in `src/hashall/scan.py` uses `os.stat` without symlink checks.
Impact: Possible duplicate records via symlinked files (less severe than bind mounts but still incorrect).

### Test Coverage Gaps
15. **No tests for bind-mount dedupe, path aliasing, or rehome rollback.**
Evidence: `tests/` covers incremental scan and rehome decisions but not bind-mount behavior or rollback/atomicity.
Impact: High-risk logic has no regression protection.

## Execution Plan (Minimal Stages)

### Stage 1 — Canonical Pathing + Payload Correctness
Goal: Fix catalog/path correctness so payload identity and external consumer detection are reliable.

Deliverables:
1. **Canonical path resolver** shared across scan, payload, and rehome.
Implementation: New `src/hashall/pathing.py` with:
   - `resolve_bind_source(path)` using `findmnt -no SOURCE` and `realpath`.
   - `canonicalize_path(path)` to resolve symlinks and bind sources.
   - `to_relpath(path, mount_point)` and `to_abspath(rel, mount_point)`.

2. **Scan pipeline uses canonical mount mapping.**
Implementation:
   - Update `src/hashall/scan.py` to compute a canonical root for bind mounts (source path).
   - Store paths relative to `preferred_mount_point` if present, or the canonical mount point otherwise.
   - Skip symlinked files during scan.

3. **Payload builder uses mount-aware paths.**
Implementation:
   - Update `src/hashall/payload.py` to convert absolute roots to relative before querying `files_<device_id>`.
   - Store `payloads.root_path` in canonical form (relative-to-preferred or canonical absolute) consistently.

4. **External consumer detection made safe and accurate.**
Implementation:
   - Filter `files_<device_id>` by `status='active'`.
   - Resolve payload root and hardlink paths using the new canonical path resolver.
   - If root path cannot be resolved under mount point, block with an explicit reason.

5. **Scan coverage guardrails.**
Implementation:
   - Add a rehome preflight check that verifies required seeding roots and library roots exist in `scan_roots` and were scanned recently.

Tests:
- Add bind-mount and symlink scan tests.
- Add payload build tests for relative path storage.
- Add external consumer detection tests using bind-mount-style paths.

### Stage 2 — Rehome Safety + View Building
Goal: Make rehome operations correct, atomic, and layout-aware.

Deliverables:
1. **Torrent root path detection via `content_path`.**
Implementation:
   - Extend `QBitTorrent` data to include `content_path`.
   - Prefer `content_path` for payload roots in `src/hashall/qbittorrent.py`.

2. **View builder for torrent layouts.**
Implementation:
   - New `src/rehome/view_builder.py` to build hardlink views from payload root.
   - Use qBittorrent file list to map relative paths; verify counts and total bytes.
   - Fail fast if mapping is ambiguous or incomplete.

3. **Configurable target path mapping.**
Implementation:
   - Add `rehome` config (YAML or CLI flags) to map stash/pool roots and category paths.
   - Remove hard-coded `/pool/torrents/content`.

4. **Atomic sibling relocation with rollback.**
Implementation:
   - Pause all affected torrents first, then relocate all, then resume all.
   - On any failure, revert already moved torrents to original locations and roll back payload moves.

5. **Optional hash spot-check on rehome.**
Implementation:
   - Add `--verify-hash` or `--spot-check` to verify a subset of files post-move.

6. **Duplicate canonical payload cleanup.**
Implementation:
   - Add `--cleanup-duplicate-payload` that removes source payload root after verified REUSE.
   - Ensure “never destroy last copy” by verifying target payload exists and matches file count/bytes.

Tests:
- Add rehome view builder tests.
- Add rehome rollback tests.
- Add configurable target path tests.

### Stage 3 — Remaining Features + Auditing
Goal: Close the remaining functional gaps and harden operability.

Deliverables:
1. **Cross-device duplicate detection.**
Implementation:
   - Add `hashall link analyze --cross-device` using SHA256 across `files_*` tables.

2. **Treehash for unified catalog.**
Implementation:
   - Replace legacy `src/hashall/treehash.py` with a unified-catalog treehash that works on `files_<device_id>`.

3. **Rehome audit trail.**
Implementation:
   - Add a `rehome_runs` table or structured log file with timestamps and plan metadata.

4. **Post-rehome catalog sync option.**
Implementation:
   - Add `--rescan` flag to rehome apply or a direct DB update of `payloads` and `torrent_instances`.

Tests:
   - Cross-device duplicate analysis tests.
   - Treehash tests against per-device tables.

## Progress Tracker (Living)

### Stage 1 — Canonical Pathing + Payload Correctness
DONE:
- Canonical path resolver shared across scan and payload (`src/hashall/pathing.py`).
- Scan pipeline canonicalizes roots, uses preferred mount for relpaths, skips symlinked files.
- Payload builder converts absolute roots to relative queries when mount metadata exists.
- External consumer detection now uses active-only rows, canonical paths, and blocks on unresolved roots.
- Rehome blocks demotion when payload_hash is missing.

TODO:
- Add bind-mount scan coverage test (real or mocked).
- Add external consumer detection test with bind-mount-style paths.
- Extend scan coverage guardrails to include library roots (not just seeding roots).

### Stage 2 — Rehome Safety + View Building
DONE:
- Use qBittorrent `content_path` for payload root resolution.
- Implement view builder for torrent layouts (`src/rehome/view_builder.py`).
- Add configurable save_path mapping (`--stash-seeding-root`, `--pool-seeding-root`).
- Add configurable MOVE target root (`--pool-payload-root`).
- Make sibling relocation atomic with rollback attempts.
- Add optional SHA256 spot-check (`--spot-check`).
- Add duplicate payload cleanup (`--cleanup-duplicate-payload`).

TODO:
- Add rollback tests for atomic relocation failures.
- Add mapping tests for save_path translation.

### Stage 3 — Remaining Features + Auditing
DONE:
- Cross-device duplicate detection (`hashall link analyze --cross-device`).
- Treehash now supports unified catalog (`files_<device_id>`).
- Rehome audit trail persisted in `rehome_runs`.
- Post-rehome catalog sync updates `payloads` and `torrent_instances`.
- Optional post-rehome rescan (`--rescan`).

TODO:
- Add tests for rehome audit trail and rescan paths.

## Notes and Open Decisions
- **Canonical path format:** Decide whether `files_<device_id>.path` should remain relative to preferred mount or be stored as canonical absolute. Consistency matters more than which choice is made.
- **Path aliasing:** A small `path_aliases` table may be cleaner than ad-hoc remap logic for `/data/media` → `/stash/media`.
- **Migration:** If path format changes, include a one-time migration or re-scan strategy.
