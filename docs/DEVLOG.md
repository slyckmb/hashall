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

## Future Entries

Additional entries will be added here as the project evolves.
