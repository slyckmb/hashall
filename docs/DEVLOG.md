# Hashall Development Log

This log tracks significant architectural changes, refactorings, and design decisions in the hashall project.

---

## 2026-01-31: Stage 1 - Rename "conductor" to "link"

### Summary

Renamed the deduplication subsystem from "conductor" to "link" across all documentation and scripts. This is a CLI/UX rename with no behavior changes.

### Rationale

The term "link" better describes the core functionality: creating **hardlinks** on the same device to deduplicate files. "Conductor" was too abstract and didn't clearly communicate what the subsystem does.

### Changes Made

#### Documentation
- Renamed `docs/conductor-guide.md` → `docs/link-guide.md`
- Updated all command references: `hashall conductor` → `hashall link`
- Updated table names in schema docs: `conductor_plans` → `link_plans`, `conductor_actions` → `link_actions`
- Updated all conceptual references to the subsystem from "conductor" to "link"

#### Scripts
- Renamed `scripts/conductor_plan.py` → `scripts/link_plan.py`
- Updated internal comments and output filenames
- Updated `scripts/analyze_export.py` docstring

#### Files Modified
- README.md
- docs/architecture.md
- docs/cli.md
- docs/quick-reference.md
- docs/schema.md
- docs/unified-catalog-architecture.md
- docs/link-guide.md (renamed from conductor-guide.md)
- scripts/link_plan.py (renamed from conductor_plan.py)
- scripts/analyze_export.py

### Command Mapping

| Old Command | New Command |
|------------|-------------|
| `hashall conductor analyze` | `hashall link analyze` |
| `hashall conductor plan` | `hashall link plan` |
| `hashall conductor show-plan` | `hashall link show-plan` |
| `hashall conductor execute` | `hashall link execute` |
| `hashall conductor status` | `hashall link status` |

### Database Schema

Planned table renames (not yet implemented in code):
- `conductor_plans` → `link_plans`
- `conductor_actions` → `link_actions`

### What's Next

**Stage 2+** (not part of this change):
- Implement CLI commands `hashall link ...` in `src/hashall/cli.py`
- Implement link module `src/hashall/link.py`
- Create database migration for table renames
- Add integration tests for link commands

### Compatibility Notes

- The actual CLI commands (`hashall link ...`) are not yet implemented - they exist only in documentation
- Standalone scripts `scripts/link_plan.py` and `scripts/analyze_export.py` continue to work as before
- No database changes were made in this stage
- No code in `src/hashall/` was modified (only docs and scripts)

### Key Insight

"Link" terminology:
- **Clear**: Describes what it does (creates hardlinks)
- **Accurate**: Only works on same-device files (hardlink constraint)
- **Distinct**: Differentiates from future orchestration/stash systems that may move files across devices

---

## 2026-01-31: Stage 2 - Payload Identity & Torrent→Payload Mapping

### Summary

Introduced **payload identity** as a first-class concept in hashall. A payload represents the on-disk content tree a torrent points to, independent of torrent metadata. This enables tracking multiple torrents that reference the same physical content.

### Rationale

**Problem**: Different torrents can point to identical content:
- Same content, different piece sizes
- Same content, v1 vs v2 torrents
- Same content, different sources/trackers
- Re-releases, remuxes, renamed directories

These produce **different infohashes** but should map to the **same payload** for deduplication and management purposes.

**Solution**: Payload identity based on content fingerprinting.

### Changes Made

#### Schema
- Added `payloads` table - one row per unique content instance
- Added `torrent_instances` table - maps torrent hashes to payloads
- Migration: `0006_add_payload_tables.sql`

#### Core Logic
- Created `src/hashall/payload.py`:
  - `compute_payload_hash()` - deterministic SHA256 of sorted (path, size, sha1) tuples
  - `build_payload()` - constructs payload from catalog data
  - `get_torrent_siblings()` - finds all torrents mapping to same payload
  - Payload status tracking ('complete' | 'incomplete')

#### qBittorrent Integration
- Created `src/hashall/qbittorrent.py`:
  - Read-only Web API client
  - Fetches torrent list and file trees
  - Maps torrents to on-disk roots
  - Environment/config-based authentication

#### CLI Commands
- Added `hashall payload` command group:
  - `sync` - connect to qBit, map torrents → payloads, compute hashes
  - `show <torrent_hash>` - display payload info
  - `siblings <torrent_hash>` - list all torrents with same content

#### Tests
- Created `tests/test_payload.py`:
  - Deterministic hash generation
  - Multiple torrents → one payload
  - Incomplete payload handling
  - Idempotent sync operations

### Key Concepts

#### Payload Hash Algorithm
```
payload_hash = SHA256(
  sorted list of:
    (relative_path, file_size, file_sha1)
)
```

- Uses **catalog data only** (no file re-reading)
- Deterministic and reproducible
- NULL if any file missing SHA1 (incomplete)

#### Payload States
- **complete**: All files have SHA1, payload_hash computed
- **incomplete**: Some files missing SHA1, hash cannot be computed

#### Many Torrents → One Payload
Multiple torrents can reference the same payload:
- Torrent A (v1, 2MB pieces) → Payload X
- Torrent B (v2, 4MB pieces) → Payload X
- Torrent C (different tracker) → Payload X

Query `siblings` to find these relationships.

### Example Workflow

```bash
# 1. Scan content to populate file catalog
hashall scan /pool/torrents

# 2. Sync torrents from qBittorrent
hashall payload sync

# 3. Show payload for a torrent
hashall payload show abc123...

# 4. Find sibling torrents (same content)
hashall payload siblings abc123...
```

### Implementation Notes

#### Compatibility with Session-Based Model
Stage 2 works with the **existing session-based schema**. The unified catalog model described in documentation is not yet implemented. Payload tables are designed to be compatible with future migration.

#### Read-Only qBittorrent Access
All qBittorrent operations are read-only. No torrent state modifications, no relocations, no deletions.

#### Derived State
Payload identity is **derived from catalog data**. If catalog is stale, payloads may be incomplete. Re-scan content to update.

### Database Tables

```sql
payloads (
  payload_id, payload_hash, device_id, root_path,
  file_count, total_bytes, status, last_built_at
)

torrent_instances (
  torrent_hash, payload_id, device_id, save_path,
  root_name, category, tags, last_seen_at
)
```

### What's Next

**Stage 3+** (not part of this change):
- Implement link CLI commands (still documented but not coded)
- Migrate to unified catalog model (devices, files_<device_id> tables)
- Stash/pool orchestration
- Automatic torrent relocation based on payload analysis
- Payload-aware deduplication strategies

### Limitations

- Requires files to be scanned first (`hashall scan`)
- Payloads with unscanned files show as 'incomplete'
- qBittorrent must be running and accessible
- No automatic rescanning of changed content

### Environment Variables

```bash
QBITTORRENT_URL=http://localhost:8080  # qBittorrent Web UI URL
QBITTORRENT_USER=admin                  # Username
QBITTORRENT_PASS=password               # Password
```

---

## 2026-01-31: Stage 3 - Rehome (Seed Payload Demotion MVP)

### Summary

Implemented **rehome**, an external CLI tool for orchestrating safe demotion of seed-only payloads from stash (high-tier storage) to pool (lower-tier storage). Uses hashall's payload identity system as the source of truth.

### Rationale

**Problem**: Stash storage is expensive/limited. Payloads that are only being seeded (not actively consumed) should be demoted to pool to free up stash space.

**Challenges**:
- Must detect external consumers (hardlinks outside seeding domain)
- Must avoid creating duplicate data
- Must handle multiple torrents pointing to same payload (siblings)
- Must coordinate with qBittorrent for torrent relocation

**Solution**: Payload-based demotion with external consumer blocking.

### Changes Made

#### New Module: rehome

Created `src/rehome/` as a separate CLI module:
- `__init__.py` - Package metadata
- `cli.py` - Click-based CLI (`rehome plan`, `rehome apply`)
- `planner.py` - Demotion planning logic
- `executor.py` - Plan execution logic

#### Planning Logic

**External Consumer Detection** (`planner.py:_detect_external_consumers`):
- For each file in payload, find all hardlinks (same inode)
- Check if any hardlink path is outside seeding domain root(s)
- BLOCK demotion if external consumers found

**Decision Algorithm** (`planner.py:plan_demotion`):
1. Resolve torrent → payload (via `torrent_instances` table)
2. Verify payload is on stash device
3. Get all sibling torrents (same payload_hash)
4. Check for external consumers → BLOCK if found
5. Check if payload exists on pool → REUSE if yes, MOVE if no
6. Generate plan JSON with decision and steps

**Decisions**:
- **BLOCK**: External consumers detected, cannot demote
- **REUSE**: Payload already exists on pool, reuse it
- **MOVE**: Payload doesn't exist on pool, move it from stash

#### Execution Logic

**Dry-Run Mode** (`executor.py:dry_run`):
- Prints all actions that would occur
- No filesystem or database changes
- Greppable `key=value` log format

**Force Mode** (`executor.py:execute`):
- **REUSE path**:
  1. Verify existing payload on pool
  2. Build torrent views (hardlinks to payload)
  3. Relocate torrents in qBittorrent
  4. Remove stash-side views
- **MOVE path**:
  1. Verify source exists and matches expected size/count
  2. Move payload root directory (stash → pool)
  3. Verify target matches expected size/count
  4. Build torrent views on pool
  5. Relocate torrents in qBittorrent
  6. Verify source is removed

**Safety Features**:
- File count verification before and after
- Total bytes verification before and after
- Fail-fast on any verification failure
- Step-by-step logging

#### Tests

Created `tests/test_rehome.py` with coverage for:
- External consumer detection (BLOCK case)
- REUSE decision when payload exists on pool
- MOVE decision when payload doesn't exist on pool
- Sibling torrents included in plan
- Dry-run produces no side effects

All tests use mocked database fixtures (no real qBittorrent or filesystem changes).

#### Documentation

Created `docs/REHOME.md`:
- Overview and architecture
- Payload identity and external consumer concepts
- Command reference (`rehome plan`, `rehome apply`)
- Plan file format (JSON schema)
- Typical workflow examples
- Safety features and limitations
- Troubleshooting guide
- Design rationale

Updated `pyproject.toml`:
- Added `rehome` package to setuptools config
- Added `rehome` CLI entry point
- Added `requests` dependency (for qBittorrent client)

### Key Concepts

#### External Consumer Rule

A payload **MUST STAY on stash** if any file in the payload has a hardlink whose path is outside the seeding domain root(s).

**Example**:
```
Seeding domain: /stash/torrents/seeding/

Payload: /stash/torrents/seeding/Movie.2024/
Files:
  - video.mkv (inode 1234)
  - subtitles.srt (inode 1235)

Hardlinks for inode 1234:
  - /stash/torrents/seeding/Movie.2024/video.mkv ✅ (inside domain)
  - /media/exports/Movie.mkv ❌ (outside domain)

Decision: BLOCKED (external consumer detected)
```

#### Payload Siblings

Multiple torrents can map to the same payload:
- Torrent A (v1, 2MB pieces) → Payload X
- Torrent B (v2, 4MB pieces) → Payload X
- Torrent C (different tracker) → Payload X

Demotion plan includes **all siblings** to ensure consistent state.

### CLI Commands

#### rehome plan

```bash
rehome plan --demote \
  --torrent-hash <hash> \
  --seeding-root /stash/torrents/seeding \
  --stash-device 50 \
  --pool-device 49 \
  --output rehome-plan.json
```

Output: JSON plan file with decision (BLOCK | REUSE | MOVE)

#### rehome apply

```bash
# Dry-run (preview)
rehome apply rehome-plan.json --dryrun

# Execute
rehome apply rehome-plan.json --force
```

### Example Workflow

```bash
# 1. Ensure catalog is up-to-date
hashall scan /stash/torrents/seeding
hashall scan /pool/torrents/content
hashall payload sync

# 2. Create demotion plan
rehome plan --demote \
  --torrent-hash abc123def456 \
  --seeding-root /stash/torrents/seeding \
  --stash-device 50 \
  --pool-device 49

# 3. Review and execute
cat rehome-plan-abc123de.json | jq .
rehome apply rehome-plan-abc123de.json --dryrun
rehome apply rehome-plan-abc123de.json --force

# 4. Rescan to update catalog
hashall scan /stash
hashall scan /pool
hashall payload sync
```

### Known Limitations (MVP)

1. **Demotion only** - No promotion (pool → stash)
2. **Single-torrent mode** - Process one at a time
3. **Stubbed qBittorrent integration** - Torrent relocation not implemented
4. **Basic view building** - Assumes torrent name = directory name
5. **Manual cleanup** - Stash-side cleanup not automated
6. **No rollback** - Manual recovery required on failure

### Implementation Notes

#### Separation from hashall Core

Rehome is a **separate module** with its own CLI entry point because:
- Different responsibility (orchestration vs cataloging)
- Optional workflow (not all users need demotion)
- Experimental (can iterate without affecting hashall stability)
- Allows different release cadence

#### Read-Only Catalog Access

Rehome **reads** from hashall catalog but does **not modify** it. Catalog updates happen via:
- `hashall scan` (filesystem changes)
- `hashall payload sync` (qBittorrent state)

This keeps rehome loosely coupled to hashall internals.

#### Plan-and-Execute Pattern

Demotion is split into two phases:
1. **Plan**: Generate JSON plan with decision + steps
2. **Apply**: Execute plan with dry-run or force mode

This allows:
- User review before execution
- Plan archival for auditing
- Replay or modification of plans
- Batch processing (future)

### What's Next

**Stage 4+** (not part of this change):
- Full qBittorrent integration (actual torrent relocation)
- Smart view building (hardlink forests for complex layouts)
- Batch demotion (process multiple torrents in one plan)
- Promotion (pool → stash for active torrents)
- Automatic cleanup with verification
- Fuzzy payload matching (variants)
- Web UI for plan review

### Testing

```bash
# Run rehome tests
pytest tests/test_rehome.py -v

# All tests pass:
# - test_block_when_external_consumer_detected
# - test_no_block_when_all_hardlinks_internal
# - test_reuse_when_payload_exists_on_pool
# - test_move_when_payload_not_on_pool
# - test_siblings_included_in_plan
# - test_dryrun_no_side_effects
```

### Files Added/Modified

**New files**:
- `src/rehome/__init__.py`
- `src/rehome/cli.py`
- `src/rehome/planner.py`
- `src/rehome/executor.py`
- `tests/test_rehome.py`
- `docs/REHOME.md`

**Modified files**:
- `pyproject.toml` (added rehome package + entry point + requests dependency)
- `docs/DEVLOG.md` (this entry)

---

## Future Entries

Additional entries will be added here as the project evolves.
