# Rehome - Seed Payload Rehome (Demotion + Promotion)

**Version:** 0.3.0 (Stage 5 - Promotion + Guarded Cleanup)
**Purpose:** Orchestrate safe rehome of seed payloads between stash and pool
**Status:** Production - Demotion + Promotion (reuse-only) with qBittorrent relocation

---

## Overview

Rehome is an external orchestration tool that moves seed payloads between tiers:
- **Demotion**: stash → pool (may reuse or move)
- **Promotion**: pool → stash (**reuse-only, no blind copy**)

**Key capabilities:**
- Uses hashall catalog as source of truth
- Detects external consumers (blocks demotion if found)
- Reuses existing payloads on pool when available
- Moves payloads safely with verification at each step
- Handles multiple torrents pointing to same payload (siblings)
- **Real qBittorrent integration** - pause/relocate/resume torrents via Web API
- **Batch demotion** - demote by payload hash or qBittorrent tag
- **Promotion (reuse-only)** - promote only when payload already exists on stash
- **Guarded cleanup** - optional source-view and empty-dir cleanup

**What rehome is NOT:**
- Not a fuzzy/variant payload matcher
- Not an automatic background service
- Not a hashall core feature (external orchestrator)

**Stage 5 additions:**
- Promotion planning and apply flow (reuse-only)
- **No blind copy** rule for promotion (BLOCK if stash payload missing)
- Guarded cleanup flags (opt-in, safe by default)

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

### Promotion (Reuse-Only)

**Promotion** means:
- A payload currently on **pool** (lower-tier storage)
- A matching payload **already exists on stash**
- All sibling torrents are updated to point to stash location
- **No blind copy**: if stash payload is missing, promotion is BLOCKED

---

## qBittorrent Integration

### Authentication Pattern (Reused from tracker-ctl)

Rehome uses the same qBittorrent authentication pattern as tracker-ctl:
- Credentials from environment variables: `QBITTORRENT_URL`, `QBITTORRENT_USER`, `QBITTORRENT_PASS`
- Session-based authentication via Web API
- Cookie management handled automatically

**Environment variables:**
```bash
export QBITTORRENT_URL=http://localhost:9003  # qBittorrent Web UI URL
export QBITTORRENT_USER=admin                  # Username
export QBITTORRENT_PASS=password               # Password
```

### Relocation Flow

When relocating torrents, rehome follows the tracker-ctl pattern from `qbit_migrate_paths.sh`:

1. **Pause** torrent (`POST /api/v2/torrents/pause`)
2. **Set location** (`POST /api/v2/torrents/setLocation`)
3. **Resume** torrent (`POST /api/v2/torrents/resume`)
4. **Verify** new location matches expected path

**Failure handling:**
- If set_location fails, torrent is resumed at old location
- If any torrent relocation fails, entire operation aborts
- For MOVE plans, payload is rolled back to stash on failure

---

## Commands

### `rehome plan`

Create a demotion or promotion plan for torrents (single or batch mode).

**Syntax (single-torrent mode):**
```bash
rehome plan --demote \
  --torrent-hash <hash> \
  --seeding-root <path> \
  --stash-device <device_id> \
  --pool-device <device_id> \
  [--catalog <db_path>] \
  [--output <plan_file>]
```

**Syntax (promotion - single-torrent mode):**
```bash
rehome plan --promote \
  --torrent-hash <hash> \
  --seeding-root <path> \
  --stash-device <device_id> \
  --pool-device <device_id> \
  [--catalog <db_path>] \
  [--output <plan_file>]
```

**Syntax (batch mode - by payload hash):**
```bash
rehome plan --demote \
  --payload-hash <hash> \
  --seeding-root <path> \
  --stash-device <device_id> \
  --pool-device <device_id> \
  [--catalog <db_path>] \
  [--output <plan_file>]
```

**Syntax (promotion - batch by payload hash):**
```bash
rehome plan --promote \
  --payload-hash <hash> \
  --seeding-root <path> \
  --stash-device <device_id> \
  --pool-device <device_id> \
  [--catalog <db_path>] \
  [--output <plan_file>]
```

**Syntax (batch mode - by tag):**
```bash
rehome plan --demote \
  --tag <tag> \
  --seeding-root <path> \
  --stash-device <device_id> \
  --pool-device <device_id> \
  [--catalog <db_path>] \
  [--output <plan_file>]
```

**Syntax (promotion - batch by tag):**
```bash
rehome plan --promote \
  --tag <tag> \
  --seeding-root <path> \
  --stash-device <device_id> \
  --pool-device <device_id> \
  [--catalog <db_path>] \
  [--output <plan_file>]
```

**Options:**
- `--demote` - Demotion (stash → pool)
- `--promote` - Promotion (pool → stash, reuse-only)
- `--torrent-hash` - Torrent infohash to demote (single-torrent mode)
- `--payload-hash` - Payload hash to demote (batch mode - all torrents with this payload)
- `--tag` - qBittorrent tag to filter by (batch mode - all torrents with this tag)
- `--seeding-root` - Seeding domain root path(s) (can specify multiple times)
- `--stash-device` - Device ID for stash storage
- `--pool-device` - Device ID for pool storage
- `--catalog` - Path to hashall catalog database (default: `~/.hashall/catalog.db`)
- `--output` - Output plan file (default: `rehome-plan-<mode>.json`)

**Modes (mutually exclusive):**
- Specify exactly ONE of: `--torrent-hash`, `--payload-hash`, or `--tag`
- Specify exactly ONE of: `--demote` or `--promote`

**Output:**
- JSON plan file with decision (BLOCK | REUSE | MOVE) and direction
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

Apply a demotion or promotion plan.

**Syntax:**
```bash
rehome apply <plan_file> --dryrun   # Preview only
rehome apply <plan_file> --force    # Execute
```

**Options:**
- `<plan_file>` - Path to plan JSON file (from `rehome plan`)
- `--dryrun` - Show what would happen without making changes
- `--force` - Execute the plan (mutually exclusive with --dryrun)
- `--cleanup-source-views` - Remove source-side torrent views (never payload roots)
- `--cleanup-empty-dirs` - Remove empty directories under seeding roots only
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

**For PROMOTION (REUSE-only) plans:**
1. Verify existing payload on stash
2. For each sibling torrent:
   - Build stash-side torrent view (logical)
   - Relocate torrent in qBittorrent
   - Verify torrent can access files
3. Optional cleanup (if flags provided)

**Cleanup behavior:**
- Cleanup flags are **opt-in** and **disabled by default**
- Cleanup is **skipped on any relocation failure**
- Cleanup actions are shown during dry-run

**Example:**
```bash
# Dry-run first (always recommended)
rehome apply rehome-plan-abc123de.json --dryrun

# Execute if dry-run looks good
rehome apply rehome-plan-abc123de.json --force
```

---

## Workflow

### Single-Torrent Demotion

```bash
# 1. Ensure catalog is up-to-date
hashall scan /stash/torrents/seeding
hashall scan /pool/torrents/content
hashall payload sync

# 2. Create demotion plan for a specific torrent
rehome plan --demote \
  --torrent-hash abc123def456 \
  --seeding-root /stash/torrents/seeding \
  --stash-device 50 \
  --pool-device 49

# 3. Review the plan
cat rehome-plan-abc123de.json | jq .

# 4. Dry-run to preview actions
rehome apply rehome-plan-abc123de.json --dryrun

# 5. Execute if everything looks good
rehome apply rehome-plan-abc123de.json --force

# 6. Rescan to update catalog
hashall scan /stash
hashall scan /pool
hashall payload sync
```

### Batch Demotion by Payload Hash

```bash
# Demote all torrents sharing a specific payload
rehome plan --demote \
  --payload-hash sha256_abc123... \
  --seeding-root /stash/torrents/seeding \
  --stash-device 50 \
  --pool-device 49

# Review and apply
cat rehome-plan-payload-sha256_abc.json | jq .
rehome apply rehome-plan-payload-sha256_abc.json --dryrun
rehome apply rehome-plan-payload-sha256_abc.json --force
```

### Batch Demotion by Tag

```bash
# Demote all torrents with a specific tag (e.g., ~noHL for "no hardlink")
rehome plan --demote \
  --tag ~noHL \
  --seeding-root /stash/torrents/seeding \
  --stash-device 50 \
  --pool-device 49

# This creates a batch plan with one sub-plan per unique payload
cat rehome-plan-tag-~noHL.json | jq .

# Apply will process each payload sequentially
rehome apply rehome-plan-tag-~noHL.json --dryrun
rehome apply rehome-plan-tag-~noHL.json --force
```

---

## Plan File Format

Plans are JSON files with this structure:

```json
{
  "version": "1.0",
  "direction": "demote",
  "decision": "REUSE",
  "torrent_hash": "abc123def456...",
  "payload_id": 42,
  "payload_hash": "sha256_hash...",
  "reasons": ["Payload already exists on pool at /pool/torrents/content/Movie.2024"],
  "affected_torrents": ["abc123def456", "fedcba654321"],
  "source_path": "/stash/torrents/seeding/Movie.2024",
  "target_path": "/pool/torrents/content/Movie.2024",
  "source_device_id": 50,
  "target_device_id": 49,
  "seeding_roots": ["/stash/torrents/seeding"],
  "no_blind_copy": false,
  "file_count": 125,
  "total_bytes": 25000000000
}
```

**Fields:**
- `version` - Plan format version
- `direction` - demote | promote
- `decision` - BLOCK | REUSE | MOVE
- `torrent_hash` - Requested torrent hash
- `payload_id` - Payload ID in catalog
- `payload_hash` - Content-based payload hash (SHA256)
- `reasons` - Human-readable reasons for decision
- `affected_torrents` - All sibling torrents (same payload)
- `source_path` - Current location on stash
- `target_path` - Target location on pool (null for BLOCK)
- `source_device_id` - Source device ID
- `target_device_id` - Target device ID
- `seeding_roots` - Roots allowed for cleanup
- `no_blind_copy` - True for promotion plans
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
- Cleanup is opt-in and skipped on failure

### Limitations (MVP)

- **No advanced view building** - Assumes torrent name matches directory name
- **Limited rollback** - MOVE plans attempt rollback on relocation failure; other failures require manual recovery

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

### Current Constraints (Stage 4)

1. **Demotion only** - No promotion (pool → stash)
2. **Manual cleanup** - Stash-side cleanup requires user verification
3. **No fuzzy matching** - Exact payload_hash match only
4. **Basic view building** - Assumes torrent name = directory name
5. **Sequential batch processing** - Batch plans execute serially, not in parallel

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
### Promotion (Reuse-Only)

```bash
# Promote a payload from pool → stash (reuse-only)
rehome plan --promote \
  --torrent-hash abc123def456 \
  --seeding-root /pool/torrents/seeding \
  --stash-device 50 \
  --pool-device 49

# Dry-run
rehome apply rehome-plan-promote-abc123de.json --dryrun

# Execute (optional cleanup)
rehome apply rehome-plan-promote-abc123de.json --force \\
  --cleanup-source-views \\
  --cleanup-empty-dirs
```
