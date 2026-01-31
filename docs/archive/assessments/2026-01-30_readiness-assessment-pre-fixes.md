# Hashall Readiness Assessment

> **⚠️ OBSOLETE (2026-01-31):** This assessment predates bug fixes in commits 65011d2-b67da27.
> All critical issues described here (treehash SQL errors, export path mismatch, missing hardlink detection) have been resolved.
> Current hashall (commit b67da27+) IS production-ready.
> Retained for historical reference only.
> See `archive/sessions/2026-01-30_bug-fixes-and-hardlinks.md` for details on fixes.

**Date:** 2026-01-30
**Version:** 0.4.0
**Commit:** 155d0ff (main)

## Executive Summary

Hashall is **NOT production-ready** for automation workflows. While core functionality (scan, verify) works correctly, there are **2 critical bugs** that break key workflows and **1 critical missing feature** for ZFS environments.

**Recommendation:** Fix critical bugs before proceeding to pipeline integration.

---

## Current State Analysis

### ✅ What Works Well

1. **Core scan/verify workflow** — Basic functionality is solid:
   - `scan` correctly walks directories, computes SHA1 hashes, stores in SQLite
   - `verify` accurately compares files by hash, size, and mtime
   - Session tracking works (UUIDs, timestamps)
   - Database schema is clean and normalized

2. **Session-based architecture** — Good foundation:
   - Composite primary key `(path, scan_session_id)` prevents duplicates
   - Multiple scans of same tree can coexist
   - Sessions tracked with UUIDs for reproducibility

3. **JSON export for automation** — Output is stable:
   - `orjson` provides fast, correct serialization
   - Schema is simple: `{scan_id, root_path, files: [{path, size, mtime, sha1}]}`
   - Machine-readable format suitable for external tools

4. **Error handling in scan** — Graceful degradation:
   - Continues on unreadable files
   - Warns user but doesn't crash

---

## 🔴 Critical Issues (Must Fix)

### Issue #1: Treehash Implementation is Completely Broken
**File:** `src/hashall/treehash.py`
**Severity:** CRITICAL (non-functional code)
**Impact:** Treehash feature cannot be used at all

**Problems:**
1. Line 20: Queries column `rel_path` but schema has `path`
2. Line 22: Queries `WHERE scan_id = ?` but `files` table has `scan_session_id`
3. Line 37: Updates table `scan_session` but actual name is `scan_sessions`

**Evidence:**
```python
# treehash.py:20 - WRONG COLUMN NAME
cursor.execute("""
    SELECT rel_path, sha1, size, mtime  # ❌ No column 'rel_path'
    FROM files
    WHERE scan_id = ?  # ❌ No column 'scan_id'
    ORDER BY rel_path  # ❌ No column 'rel_path'
""", (scan_id,))

# schema.sql:12 - ACTUAL SCHEMA
CREATE TABLE files (
    path TEXT NOT NULL,  # ✅ Column is 'path'
    scan_session_id INTEGER,  # ✅ FK is 'scan_session_id'
```

**Why it matters:**
- Treehash is intended for fast tree comparison without re-hashing
- Automation workflows need this for incremental verification
- Currently unusable — will throw SQL errors on every call

**Root cause:** Code was written for an older schema, migrations changed column names but treehash.py wasn't updated.

---

### Issue #2: Export Path Mismatch Breaks verify-trees Workflow
**Files:** `src/hashall/export.py`, `src/hashall/verify_trees.py`
**Severity:** CRITICAL (workflow broken)
**Impact:** Session-consistent verification fails silently

**Problem:**
- `verify_trees` expects JSON at: `<root>/.hashall/hashall.json`
- `export_json` writes JSON to: `~/.hashall/hashall.json` (when called programmatically)

**Evidence:**
```python
# verify_trees.py:58-59 — WHERE IT LOOKS
src_json = src_root / ".hashall" / "hashall.json"
dst_json = dst_root / ".hashall" / "hashall.json"

# export.py:31 — WHERE IT WRITES (when out_path=None)
out = Path(out_path) if out_path else Path.home() / ".hashall" / "hashall.json"
```

**Why it matters:**
- When `verify_trees` auto-exports after scanning (default behavior), the JSON is written to the wrong location
- Subsequent `verify_trees` runs won't find the cached JSON
- Forces re-scan every time, defeating session caching

**Actual behavior:**
```bash
# First run
$ hashall verify-trees /src /dst
→ Scans /src, exports to ~/.hashall/hashall.json
→ Scans /dst, exports to ~/.hashall/hashall.json (overwrites!)

# Second run
$ hashall verify-trees /src /dst
→ Looks for /src/.hashall/hashall.json — NOT FOUND
→ Re-scans /src (unnecessary!)
```

**Root cause:** `export_json()` has poor default behavior when `out_path` is omitted.

---

## ⚠️ High-Priority Gaps (ZFS/Hardlink Environments)

### Issue #3: No Hardlink Detection
**Severity:** HIGH (missing core feature for ZFS use case)
**Impact:** Cannot deduplicate correctly, false positives in verification

**Problem:**
- Schema doesn't store `inode` or `device_id`
- Multiple hardlinks to same file appear as separate files
- Cannot distinguish "same content" from "same inode"

**Evidence:**
```sql
-- schema.sql:11-18 — MISSING INODE/DEVICE
CREATE TABLE files (
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha1 TEXT,
    scan_session_id INTEGER
    -- ❌ No inode
    -- ❌ No device_id
);
```

**Why it matters for your use case:**
- ZFS environments heavily use hardlinks for deduplication
- qBittorrent/cross-seed workflows create many hardlinks
- jdupes deduplication relies on inode tracking
- Without this, hashall cannot:
  - Detect when files are already linked
  - Plan safe migrations (might break links)
  - Generate correct dedup reports

**Example failure scenario:**
```
/data/torrents/movie.mkv (inode 12345)
/data/seeding/movie.mkv  (inode 12345) ← same file, hardlinked

verify-trees reports: ✅ Files match (same hash)
Reality: They're the SAME file, not copies
Impact: rsync repair would break the hardlink
```

---

## 🟡 Medium-Priority Issues

### Issue #4: Repair Command is Non-Functional
**File:** `src/hashall/repair.py`
**Severity:** MEDIUM (feature incomplete)
**Impact:** Cannot use hashall for automated repairs

**Status:** 15-line stub, only has placeholder comment:
```python
# TODO: implement rsync-based repair using manifest
```

**Why it matters:**
- Documented as a feature in CLI (`--repair` flag exists)
- Necessary for automation workflows
- Currently does nothing when invoked

---

### Issue #5: Parallel Mode Not Implemented
**File:** `src/hashall/scan.py`
**Severity:** MEDIUM (performance feature missing)

**Status:** Flag accepted but ignored:
```python
def scan_path(db_path: Path, root_path: Path, parallel: bool = False):
    # ... parallel parameter is never used
```

**Impact:**
- Large scans (TB+ datasets) are slower than necessary
- No multi-threading for hash computation

---

### Issue #6: Test Coverage Insufficient
**Location:** `tests/` (228 lines total)
**Severity:** MEDIUM (quality/reliability risk)

**Current coverage:**
- ✅ Unit tests for diff logic
- ✅ Mock-based tests for verify
- ❌ No end-to-end integration tests
- ❌ No scan → export → verify roundtrip tests
- ❌ No hardlink tests (can't test what doesn't exist)
- ❌ No treehash tests (would fail due to Issue #1)

**Why it matters:**
- Can't prove correctness for automation use
- Regression risk when fixing issues
- No confidence for ZFS/hardlink scenarios

---

## 🟢 Low-Priority / Out-of-Scope

1. **mtime comparison strictness** — Currently uses `int(mtime)` which loses subsecond precision. Acceptable for most use cases.

2. **Database size growth** — Multiple scans accumulate rows. Could add cleanup command later.

3. **Progress bars** — Already implemented with tqdm, works well.

4. **Platform portability** — Currently Linux-focused, acceptable for ZFS use case.

---

## Risk Assessment for Automation Use

### Can hashall be trusted for automated move/link decisions?

**Current answer: NO**

| Requirement | Status | Risk Level |
|------------|--------|-----------|
| Correct hash computation | ✅ Works | LOW |
| Accurate file comparison | ✅ Works | LOW |
| Session consistency | ❌ Broken (Issue #2) | **CRITICAL** |
| Hardlink awareness | ❌ Missing (Issue #3) | **CRITICAL** |
| Treehash for fast comparison | ❌ Broken (Issue #1) | HIGH |
| Repair/migration support | ❌ Stub only (Issue #4) | MEDIUM |
| Test coverage | ⚠️ Minimal | MEDIUM |

**Failure modes if used today:**
1. Treehash calls will crash with SQL errors
2. Session caching won't work, forcing re-scans
3. Hardlink detection impossible → false positives in verification
4. Automated repairs not possible
5. No confidence in edge cases (symlinks, permissions, special files)

---

## Recommended Fix Priority

### Phase 1: Make It Correct (Critical Bugs)
**Goal:** Core functionality works as designed

1. **Fix treehash schema mismatch** (Issue #1)
   - Change `rel_path` → `path`
   - Change `scan_id` → `scan_session_id`
   - Change `scan_session` → `scan_sessions`
   - Add integration test

2. **Fix export path default** (Issue #2)
   - When `root_path` is provided, default to `<root>/.hashall/hashall.json`
   - Update `verify_trees` to pass `out_path` explicitly
   - Add test for session caching

### Phase 2: Make It Complete (ZFS Support)
**Goal:** Support hardlink/ZFS environments

3. **Add hardlink detection** (Issue #3)
   - Add `inode` and `device_id` columns to schema
   - Update `scan.py` to capture `st_ino` and `st_dev`
   - Update `verify.py` to report hardlink status
   - Add tests with hardlinked files

### Phase 3: Make It Reliable (Testing)
**Goal:** Prove correctness

4. **Add end-to-end tests**
   - Full scan → export → verify roundtrip
   - Hardlink scenarios
   - Edge cases (empty files, large files, special chars in names)

### Phase 4: Make It Useful (Features)
**Goal:** Enable automation

5. **Implement repair command** (Issue #4)
6. **Add parallel mode** (Issue #5)

---

## Estimated Effort

| Phase | Issues | Commits | Complexity |
|-------|--------|---------|-----------|
| Phase 1 | #1, #2 | 2 | Low (schema fixes, path logic) |
| Phase 2 | #3 | 1-2 | Medium (schema migration, scan update) |
| Phase 3 | #6 | 1-2 | Medium (test infrastructure) |
| Phase 4 | #4, #5 | 2-3 | High (new features) |

**Recommendation:** Complete Phase 1 immediately. Phase 2 is required for your ZFS use case. Phase 3 is required before trusting automation. Phase 4 can wait.

---

## Decision Point

**Is hashall "good enough" for the next pipeline stage?**

**Answer: NO — but it's close.**

**What needs to happen:**
1. Fix Issue #1 (treehash) — 1 commit, ~10 min
2. Fix Issue #2 (export path) — 1 commit, ~15 min
3. Add Issue #3 (hardlinks) — 1-2 commits, ~1 hour
4. Add basic E2E test — 1 commit, ~30 min

**After these fixes:** hashall becomes a dependable foundation for ZFS+hardlink environments.

**Without these fixes:** Using hashall in automation is unsafe and will produce incorrect results.

---

## Next Steps

**Immediate action:**
1. Fix critical bugs (Issues #1, #2)
2. Prove fixes with manual tests
3. Add hardlink support (Issue #3)
4. Write E2E test covering full workflow

**Each commit should:**
- Follow Conventional Commits format
- Include detailed body explaining the fix
- Provide proof (command output showing fix works)
- Be minimal and focused on one concern

**Stop condition:**
- All Phase 1 and Phase 2 issues resolved
- Basic E2E test passing
- Manual verification of scan → export → verify-trees workflow

---

## Conclusion

Hashall has a **solid architectural foundation** but **critical bugs prevent production use**. The good news: all issues are fixable with small, focused commits. The schema is clean, the code is readable, and the problems are well-understood.

**Verdict: Fix 4 critical issues, then proceed to pipeline integration.**
