# Database Architecture Analysis - Current State vs Requirements

**Date:** 2026-02-02
**Issue:** Discovered multiple database files and architectures coexisting
**Status:** 🔴 CRITICAL - Needs decision before proceeding with Sprint 1

---

## Problem Statement

While implementing Sprint 1 (link deduplication), we discovered that the system has THREE different databases with potentially divergent data:

```bash
~/.hashall/catalog.db         18M   (unified catalog - CLI default)
~/.hashall/catalog-pool.db    68M   (per-device for /pool)
~/.hashall/catalog-stash.db  209M   (per-device for /stash)
```

**Total:** 295M across 3 databases vs 18M in unified catalog

---

## Architecture History (from Git)

### Evolution of Approaches

**1. Initial: Single Unified Catalog**
- One `catalog.db` with per-device tables (`files_49`, `files_50`, etc.)
- WAL mode enabled for concurrency
- Used by all CLI commands

**2. Concurrent Scanning Issues (commits 9ca0544, 960d12e)**
- Database lock contention during parallel scans
- Added retry logic and connection management
- Enabled WAL mode for better concurrency

**3. Per-Device Databases (commit 9ab4d6d - Feb 1, 2026)**
```
feat(scan): add per-device databases for zero-contention concurrent scanning

Per-device database support:
- Add get_device_db_path() to determine device-specific database paths
  (e.g., /pool/data → ~/.hashall/catalog-pool.db)
- Add --per-device flag to hashall-auto-scan
- Databases stored on fast SSD instead of slow USB drives

Benefits:
- Concurrent scans on different devices have zero database contention
- 8 workers optimal for fast hash (only reading 1MB per file)
```

**4. Return to Unified? (commit e14187d - Feb 1, 2026)**
```
fix(cli): use catalog.db as default database path
```

---

## Current Implementation

### Code Analysis

**`hashall-auto-scan` script:**
```python
def get_device_db_path(scan_path: Path) -> Path:
    """
    Get per-device database path for a scan path.
    Example: /pool/data → ~/.hashall/catalog-pool.db
             /stash/media → ~/.hashall/catalog-stash.db
    """
    abs_path = scan_path.resolve()
    parts = abs_path.parts
    if len(parts) >= 2 and parts[0] == '/':
        device_name = parts[1]  # 'pool' or 'stash'
    else:
        device_name = 'default'

    return Path.home() / '.hashall' / f'catalog-{device_name}.db'
```

**`src/hashall/cli.py`:**
```python
DEFAULT_DB_PATH = Path.home() / ".hashall" / "catalog.db"

@cli.command("scan")
@click.option("--db", type=click.Path(), default=DEFAULT_DB_PATH)
```

**Result:** Two code paths using different databases!

### When Each Database is Used

| Operation | Database Used | Code Path |
|-----------|---------------|-----------|
| `hashall scan /pool` | `catalog.db` | CLI default |
| `hashall-auto-scan /pool` | `catalog-pool.db` | Script with `get_device_db_path()` |
| `hashall payload sync` | `catalog.db` | CLI default |
| `hashall devices list` | `catalog.db` | CLI default |
| `rehome plan` | `catalog.db` | Uses catalog path |
| Link deduplication (new) | `catalog.db` | Will use CLI default |

---

## Schema Comparison

All three databases have **identical schema**:

```sql
-- In all databases: catalog.db, catalog-pool.db, catalog-stash.db

devices                  -- Device registry
files_44, files_49, etc  -- Per-device file tables
scan_sessions            -- Scan history
scan_roots               -- Scoped scan tracking
payloads                 -- Torrent content
torrent_instances        -- qBittorrent mapping
link_plans              -- NEW (only in catalog.db from migration)
link_actions            -- NEW (only in catalog.db from migration)
```

**Issue:** Per-device databases have MORE data (287M) than unified (18M)!

---

## Cross-Feature Dependencies

**Features that NEED unified catalog:**

1. **Link Deduplication (Sprint 1)**
   - Analyze: Query single device (OK with per-device)
   - Plan: Query single device (OK with per-device)
   - Execute: Query single device (OK with per-device)
   - **Cross-device analysis:** Needs access to both /pool and /stash
   - **Verdict:** Can work with per-device, but harder

2. **Rehoming (existing)**
   - Query payload on device A
   - Check if payload exists on device B
   - Move between devices
   - **Verdict:** REQUIRES unified catalog or complex multi-DB queries

3. **Payload Tracking (existing)**
   - Sync torrents from qBittorrent
   - Map to on-disk payloads
   - Find siblings across devices
   - **Verdict:** REQUIRES unified catalog

4. **Cross-Device Duplicate Detection**
   - Find same content on /pool and /stash
   - Informational reporting
   - **Verdict:** REQUIRES unified catalog

---

## Options Analysis

### Option A: Unified Catalog (RECOMMENDED)

**Approach:** Consolidate everything to `catalog.db`

**Implementation:**
1. Merge `catalog-pool.db` and `catalog-stash.db` into `catalog.db`
2. Remove per-device database logic from `hashall-auto-scan`
3. Rely on WAL mode for concurrency
4. All tools use single database

**Pros:**
- ✅ Simple architecture (single source of truth)
- ✅ All features work naturally (rehome, payload, link dedup)
- ✅ No data duplication or sync issues
- ✅ WAL mode provides good concurrency (readers don't block writers)
- ✅ Migration already applied to `catalog.db`

**Cons:**
- ⚠️ Concurrent scans may have *some* contention (mitigated by WAL)
- ⚠️ Database grows large (but SQLite handles this well)

**Concurrency with WAL Mode:**
- Multiple readers: ✅ No blocking
- Single writer + readers: ✅ No blocking
- Multiple writers: ⚠️ Serialize (one at a time)
- **Result:** Concurrent scans of /pool and /stash work fine (readers during scan, one writer per device)

### Option B: Per-Device Databases

**Approach:** Keep separate databases, sync for cross-device operations

**Implementation:**
1. Use `catalog-pool.db` and `catalog-stash.db` for scanning
2. Merge/sync to `catalog.db` for cross-device features
3. Add sync logic to keep unified catalog up-to-date
4. Link dedup, rehome, payload use unified catalog

**Pros:**
- ✅ True zero-contention during scans
- ✅ Scanning performance optimal

**Cons:**
- ❌ Complex sync logic needed
- ❌ Potential data divergence
- ❌ Which database has correct data?
- ❌ Migrations need to apply to 3 databases
- ❌ 295M total vs 18M - wasteful duplication

### Option C: Scan to Per-Device, Immediate Merge

**Approach:** Scan creates per-device DB, immediately merge to unified

**Implementation:**
1. Scan writes to `catalog-{device}.db`
2. After scan completes, merge to `catalog.db`
3. Delete per-device database
4. All queries use unified catalog

**Pros:**
- ✅ No long-lived duplication
- ✅ Unified catalog for all queries

**Cons:**
- ⚠️ Merge overhead after each scan
- ⚠️ Complexity for minimal benefit (WAL mode already good enough)

---

## Recommendation: OPTION A (Unified Catalog)

### Why Unified Catalog is Best

1. **WAL Mode is Sufficient for Concurrency**
   - Recent benchmarks (Feb 1): 142 files/sec (stash), 97 files/sec (pool)
   - No evidence of severe contention issues
   - Concurrent scans work: `/pool` scan + `/stash` scan simultaneously

2. **Architecture Simplicity**
   - Single source of truth
   - No sync logic needed
   - Clear data lineage

3. **Feature Requirements**
   - Rehome NEEDS unified view (check if payload on device A or B)
   - Payload tracking NEEDS unified view (siblings across devices)
   - Link dedup benefits from unified view (cross-device analysis)

4. **Current State Suggests Unified**
   - CLI defaults to `catalog.db`
   - Migration applied to `catalog.db`
   - Per-device databases are 15x larger (287M vs 18M) - suggests duplication/staleness

5. **Industry Standard**
   - SQLite with WAL mode handles this use case well
   - Many tools use single database with device partitioning
   - Per-device databases are optimization for extreme scale (not needed here)

### Migration Plan

**Step 1: Verify Current Data**
```bash
# Check what's in each database
sqlite3 ~/.hashall/catalog.db "SELECT device_id, alias, COUNT(*) FROM devices d LEFT JOIN files_49 f ON 1=1 GROUP BY device_id;"
sqlite3 ~/.hashall/catalog-pool.db "SELECT device_id, alias, COUNT(*) FROM devices d LEFT JOIN files_49 f ON 1=1 GROUP BY device_id;"
sqlite3 ~/.hashall/catalog-stash.db "SELECT device_id, alias, COUNT(*) FROM devices d LEFT JOIN files_50 f ON 1=1 GROUP BY device_id;"

# Compare file counts
for db in catalog.db catalog-pool.db catalog-stash.db; do
    echo "=== $db ==="
    sqlite3 ~/.hashall/$db ".tables" | grep files_
    sqlite3 ~/.hashall/$db "SELECT COUNT(*) FROM devices;"
done
```

**Step 2: Merge Per-Device Databases to Unified** (if needed)
```bash
# Backup everything first
cp -r ~/.hashall ~/.hashall.backup-$(date +%Y%m%d)

# Merge pool data
sqlite3 ~/.hashall/catalog-pool.db ".dump files_49" | sqlite3 ~/.hashall/catalog.db

# Merge stash data
sqlite3 ~/.hashall/catalog-stash.db ".dump files_50" | sqlite3 ~/.hashall/catalog.db

# Merge devices table (if different)
# ... (detailed SQL commands)
```

**Step 3: Update Code**
```bash
# Remove per-device database logic from hashall-auto-scan
# Or add --unified flag and make it default

# Update Makefile if needed
```

**Step 4: Verify**
```bash
# Run full scan to unified catalog
python3 -m hashall scan /pool --db ~/.hashall/catalog.db
python3 -m hashall scan /stash --db ~/.hashall/catalog.db

# Check devices registered
python3 -m hashall devices list

# Check file counts match expectations
```

**Step 5: Archive Per-Device Databases**
```bash
mkdir -p ~/.hashall/archive
mv ~/.hashall/catalog-pool.db ~/.hashall/archive/
mv ~/.hashall/catalog-stash.db ~/.hashall/archive/
```

---

## Impact on Sprint 1

### If We Choose Unified Catalog (Recommended)

**Changes Needed:**
- ✅ Migration already applied to `catalog.db` (link_plans, link_actions)
- ✅ CLI commands already default to `catalog.db`
- ✅ No code changes needed for link dedup implementation
- ⚠️ May need to merge per-device databases first

**Timeline Impact:** +2 hours (merge databases, verify data)

### If We Keep Per-Device Databases

**Changes Needed:**
- ❌ Apply migration to `catalog-pool.db` and `catalog-stash.db`
- ❌ Update link analysis to query multiple databases
- ❌ Update link plan to handle cross-device scenarios
- ❌ Add database selection logic to all commands
- ❌ Document when to use which database

**Timeline Impact:** +2 days (complexity throughout Sprint 1)

---

## Decision Required

**Question for User:**

1. **Have you been using `hashall-auto-scan` exclusively?**
   - If yes: Per-device databases have all the data
   - If no: `catalog.db` has the data

2. **Do you scan /pool and /stash concurrently?**
   - If yes: How often? Any contention issues observed?
   - If no: Unified catalog is clearly better

3. **What's your preference?**
   - **Option A:** Merge to unified catalog (recommended, +2 hours)
   - **Option B:** Keep per-device, add complexity (not recommended, +2 days)
   - **Option C:** Investigate further before deciding

---

## Recommendation

**Proceed with Option A: Unified Catalog**

**Rationale:**
- WAL mode provides sufficient concurrency
- Architecture simplicity is valuable
- All features need unified view
- Per-device databases appear to be an incomplete migration
- Recent commit moved back to unified catalog as default

**Action Items:**
1. Verify which database(s) have current data
2. Merge per-device databases to unified (if needed)
3. Archive per-device databases
4. Update `hashall-auto-scan` to use unified catalog
5. Proceed with Sprint 1 using `catalog.db`

---

**Status:** ⏸️ SPRINT 1 PAUSED - Awaiting architecture decision
**Next:** User confirms approach, then resume implementation
