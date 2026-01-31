# Rehome - Seed Payload Demotion

**Version:** 0.1.0 (Stage 3 MVP)
**Purpose:** Orchestrate safe demotion of seed-only payloads from stash to pool
**Status:** MVP - Demotion only, single-torrent mode

---

## Overview

Rehome is an external orchestration tool that moves seed-only payloads from high-tier storage (stash) to lower-tier storage (pool) without creating duplicate data.

**Key capabilities:**
- Uses hashall catalog as source of truth
- Detects external consumers (blocks demotion if found)
- Reuses existing payloads on pool when available
- Moves payloads safely with verification at each step
- Handles multiple torrents pointing to same payload (siblings)

**What rehome is NOT:**
- Not a promotion tool (pool → stash is out of scope)
- Not a fuzzy/variant payload matcher
- Not an automatic background service
- Not a hashall core feature (external orchestrator)

---

## Architecture

### Data Flow

```
User: rehome plan --demote --torrent-hash abc123...
       ↓
┌─────────────────────────────────────────┐
│ 1. Query hashall catalog                │
│    - Resolve torrent → payload          │
│    - Get payload hash, location, size   │
│    - Find sibling torrents              │
└─────────────────────────────────────────┘
       ↓
┌─────────────────────────────────────────┐
│ 2. Check for external consumers         │
│    - Find all hardlinks for each file   │
│    - Check if any outside seeding domain│
│    - BLOCK if external consumers exist  │
└─────────────────────────────────────────┘
       ↓
┌─────────────────────────────────────────┐
│ 3. Check if payload exists on pool      │
│    - Query by payload_hash              │
│    - Decision: REUSE or MOVE            │
└─────────────────────────────────────────┘
       ↓
┌─────────────────────────────────────────┐
│ 4. Generate plan JSON                   │
│    - Decision + reasons                 │
│    - Source and target paths            │
│    - All affected torrents              │
│    - Steps to execute                   │
└─────────────────────────────────────────┘
```

### Decision Logic

```
┌─────────────────────────────────────────┐
│ Payload on stash, want to demote        │
└──────────────┬──────────────────────────┘
               │
               ▼
       ┌───────────────────┐
       │ External consumers?│
       └───────┬───────────┘
               │
         Yes   │   No
      ┌────────┴────────┐
      ▼                 ▼
  ┌──────┐      ┌────────────────┐
  │BLOCK │      │ Exists on pool? │
  └──────┘      └────┬────────────┘
                     │
               Yes   │   No
              ┌──────┴──────┐
              ▼             ▼
          ┌──────┐      ┌──────┐
          │REUSE │      │MOVE  │
          └──────┘      └──────┘
```

---

## Concepts

### Payload Identity

A **payload** is the on-disk content tree a torrent points to:
- Single-file torrent → that file
- Multi-file torrent → directory tree

**Payload hash:** SHA256 of sorted (path, size, sha1) tuples
**Payload siblings:** Multiple torrents with same payload_hash

See `docs/DEVLOG.md` Stage 2 for payload identity details.

### External Consumer

A file has an **external consumer** if any hardlink points to a path outside the configured seeding domain root(s).

**Example:**
```
Seeding domain: /stash/torrents/seeding/

File: /stash/torrents/seeding/Movie.2024/video.mkv (inode 1234)
Hardlinks:
  - /stash/torrents/seeding/Movie.2024/video.mkv ✅ (inside domain)
  - /media/exports/Movie.mkv ❌ (outside domain - EXTERNAL CONSUMER)

Result: BLOCKED (cannot demote because external consumer exists)
```

### Demotion

**Demotion** means:
- A payload currently on **stash** (high-tier storage)
- With **no external consumers**
- Is moved to **pool** (lower-tier storage)
- All sibling torrents are updated to point to pool location
- No duplicate bytes are created

---

## Commands

### `rehome plan`

Create a demotion plan for a torrent.

**Syntax:**
```bash
rehome plan --demote \
  --torrent-hash <hash> \
  --seeding-root <path> \
  --stash-device <device_id> \
  --pool-device <device_id> \
  [--catalog <db_path>] \
  [--output <plan_file>]
```

**Options:**
- `--demote` - Required flag indicating demotion operation
- `--torrent-hash` - Torrent infohash to demote
- `--seeding-root` - Seeding domain root path(s) (can specify multiple times)
- `--stash-device` - Device ID for stash storage
- `--pool-device` - Device ID for pool storage
- `--catalog` - Path to hashall catalog database (default: `~/.hashall/catalog.db`)
- `--output` - Output plan file (default: `rehome-plan-<hash>.json`)

**Output:**
- JSON plan file with decision (BLOCK | REUSE | MOVE)
- Summary printed to stdout

**Example:**
```bash
rehome plan --demote \
  --torrent-hash abc123def456 \
  --seeding-root /stash/torrents/seeding \
  --stash-device 50 \
  --pool-device 49

# Output:
# ✅ Plan written to: rehome-plan-abc123de.json
# ♻️  REUSE - Payload already exists on pool
#    Payload hash: payload_hash_789...
#    Sibling torrents: 2
```

### `rehome apply`

Apply a demotion plan.

**Syntax:**
```bash
rehome apply <plan_file> --dryrun   # Preview only
rehome apply <plan_file> --force    # Execute
```

**Options:**
- `<plan_file>` - Path to plan JSON file (from `rehome plan`)
- `--dryrun` - Show what would happen without making changes
- `--force` - Execute the plan (mutually exclusive with --dryrun)
- `--catalog` - Path to hashall catalog database (default: `~/.hashall/catalog.db`)

**Behavior:**

**For REUSE plans:**
1. Verify existing payload on pool
2. For each sibling torrent:
   - Build torrent view on pool (hardlinks to payload)
   - Relocate torrent in qBittorrent
   - Verify torrent can access files
3. Remove stash-side torrent views

**For MOVE plans:**
1. Verify source exists and matches expected file count/bytes
2. Move payload root directory (stash → pool)
3. Verify target matches expected file count/bytes
4. For each sibling torrent:
   - Build torrent view on pool
   - Relocate torrent in qBittorrent
   - Verify torrent can access files
5. Verify source is removed

**For BLOCKED plans:**
- Refuses to execute, prints reasons

**Example:**
```bash
# Dry-run first (always recommended)
rehome apply rehome-plan-abc123de.json --dryrun

# Execute if dry-run looks good
rehome apply rehome-plan-abc123de.json --force
```

---

## Workflow

### Typical Demotion Flow

```bash
# 1. Ensure catalog is up-to-date
hashall scan /stash/torrents/seeding
hashall scan /pool/torrents/content

# 2. Sync payloads from qBittorrent
hashall payload sync

# 3. Create demotion plan for a torrent
rehome plan --demote \
  --torrent-hash abc123def456 \
  --seeding-root /stash/torrents/seeding \
  --stash-device 50 \
  --pool-device 49

# 4. Review the plan
cat rehome-plan-abc123de.json | jq .

# 5. Dry-run to preview actions
rehome apply rehome-plan-abc123de.json --dryrun

# 6. Execute if everything looks good
rehome apply rehome-plan-abc123de.json --force

# 7. Rescan to update catalog
hashall scan /stash/torrents/seeding
hashall scan /pool/torrents/content
hashall payload sync
```

---

## Plan File Format

Plans are JSON files with this structure:

```json
{
  "version": "1.0",
  "decision": "REUSE",
  "torrent_hash": "abc123def456...",
  "payload_id": 42,
  "payload_hash": "sha256_hash...",
  "reasons": ["Payload already exists on pool at /pool/torrents/content/Movie.2024"],
  "affected_torrents": ["abc123def456", "fedcba654321"],
  "source_path": "/stash/torrents/seeding/Movie.2024",
  "target_path": "/pool/torrents/content/Movie.2024",
  "file_count": 125,
  "total_bytes": 25000000000
}
```

**Fields:**
- `version` - Plan format version
- `decision` - BLOCK | REUSE | MOVE
- `torrent_hash` - Requested torrent hash
- `payload_id` - Payload ID in catalog
- `payload_hash` - Content-based payload hash (SHA256)
- `reasons` - Human-readable reasons for decision
- `affected_torrents` - All sibling torrents (same payload)
- `source_path` - Current location on stash
- `target_path` - Target location on pool (null for BLOCK)
- `file_count` - Number of files in payload
- `total_bytes` - Total size of payload

---

## Safety Features

### Pre-Execution Checks

- External consumer detection (BLOCKS demotion)
- File count verification
- Total bytes verification
- Source existence verification

### Execution Safety

- Dry-run mode for previewing changes
- Step-by-step logging with `key=value` format
- Verification after each major operation
- Fail-fast on any verification failure

### Limitations (MVP)

- **No qBittorrent integration** - Torrent relocation is stubbed (TODO)
- **No view building** - Assumes torrent name matches directory name
- **No automatic cleanup** - Stash-side cleanup is manual for safety
- **Single-torrent mode** - Process one torrent at a time
- **No rollback** - Manual recovery required if execution fails partway

---

## Configuration

### Environment Variables

Rehome inherits qBittorrent config from hashall:

```bash
export QBITTORRENT_URL=http://localhost:8080  # qBittorrent Web UI URL
export QBITTORRENT_USER=admin                  # Username
export QBITTORRENT_PASS=password               # Password
```

### Device IDs

Find device IDs using `stat`:

```bash
stat -c '%d' /stash  # e.g., 50
stat -c '%d' /pool   # e.g., 49
```

Or query the hashall catalog:

```bash
sqlite3 ~/.hashall/catalog.db "SELECT device_id, mount_point FROM devices;"
```

---

## Troubleshooting

### Plan is BLOCKED

**Symptom:** `decision: BLOCK` in plan

**Cause:** External consumer detected (hardlink outside seeding domain)

**Solution:**
1. Review `reasons` in plan file
2. Identify external hardlink paths
3. Either:
   - Remove external hardlinks, or
   - Exclude torrent from demotion (keep on stash)

**Example:**
```bash
# Plan shows:
# "reasons": ["File /stash/torrents/seeding/Movie/video.mkv has hardlink at /media/exports/video.mkv"]

# Option 1: Remove external hardlink
rm /media/exports/video.mkv

# Option 2: Keep torrent on stash (don't demote)
```

### Payload Not Found

**Symptom:** `Torrent <hash> not found in catalog`

**Cause:** Torrent not synced from qBittorrent

**Solution:**
```bash
hashall payload sync
```

### File Count Mismatch

**Symptom:** Execution fails with "file count mismatch"

**Cause:** Catalog is stale or filesystem changed

**Solution:**
```bash
hashall scan /stash
hashall payload sync
# Re-create plan
```

---

## Known Limitations

### MVP Constraints

1. **Demotion only** - No promotion (pool → stash)
2. **Single-torrent mode** - Process one at a time
3. **No batch operations** - Must run plan/apply for each torrent
4. **Manual cleanup** - Stash-side cleanup is not automated
5. **No fuzzy matching** - Exact payload_hash match only
6. **Stubbed qBittorrent integration** - Torrent relocation not implemented
7. **Basic view building** - Assumes torrent name = directory name

### Future Enhancements (Stage 4+)

- Batch demotion (process multiple torrents in one plan)
- Promotion (pool → stash for active torrents)
- Automatic stash cleanup after verification
- Full qBittorrent integration (torrent relocation)
- Smart view building (hardlink forests for complex layouts)
- Fuzzy payload matching (similar but not identical content)
- Web UI for plan review and approval
- Undo/rollback capability

---

## Design Rationale

### Why External Tool?

Rehome is separate from hashall core because:
- Different responsibility (orchestration vs cataloging)
- Optional workflow (not all users need demotion)
- Experimental (can iterate without affecting hashall stability)
- Focused scope (single-purpose tool)

### Why Payload-Based?

Traditional torrent demotion tools work per-torrent. Rehome works per-payload because:
- Multiple torrents can share content (same payload_hash)
- Moving all siblings together is more efficient
- Avoids partial moves (some torrents demoted, others not)
- Clearer reasoning (payload-level decisions, not torrent-level)

### Why Block on External Consumers?

External consumers indicate the content is used outside the seeding domain. Moving it could:
- Break hardlinks (if moved across devices)
- Disrupt workflows (if content is referenced elsewhere)
- Violate user expectations (content meant to stay on stash)

Blocking is the safe default. Users can remove external consumers if demotion is truly desired.

---

## See Also

- `docs/DEVLOG.md` - Stage 2 (Payload Identity), Stage 3 (Rehome)
- `docs/schema.md` - Payload and torrent_instances tables
- `tests/test_rehome.py` - Test coverage and examples
- `src/rehome/` - Implementation

---

**Questions or issues?** File a GitHub issue with the `rehome` label.
