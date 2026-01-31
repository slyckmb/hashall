# Hashall Issues — Ranked by Risk

> **⚠️ OBSOLETE (2026-01-31):** All critical issues listed here have been resolved as of commit b67da27.
> Issues #1 (treehash), #2 (export path), #3 (hardlinks) are fixed.
> Retained for historical reference only.

## 🔴 CRITICAL (Blocks Production Use)

### #1: Treehash SQL Schema Mismatch
- **File:** `src/hashall/treehash.py`
- **Problem:** Queries non-existent columns (`rel_path`, `scan_id`) and table (`scan_session`)
- **Impact:** Feature completely non-functional, crashes on every call
- **Fix:** Update column/table names to match current schema
- **Effort:** 10 minutes, 1 commit

### #2: Export Path Mismatch
- **Files:** `src/hashall/export.py`, `src/hashall/verify_trees.py`
- **Problem:** Exports to `~/.hashall/hashall.json` but verify-trees looks in `<root>/.hashall/hashall.json`
- **Impact:** Session caching broken, forces re-scans every time
- **Fix:** Change export default path to use root_path when available
- **Effort:** 15 minutes, 1 commit

### #3: No Hardlink Detection (ZFS/Dedup Critical)
- **Files:** `schema.sql`, `src/hashall/scan.py`, `src/hashall/verify.py`
- **Problem:** No `inode` or `device_id` stored, can't detect hardlinks
- **Impact:** False positives in verification, unsafe for ZFS+jdupes workflows
- **Fix:** Add inode/device columns, capture in scan, report in verify
- **Effort:** 1 hour, 2 commits (schema migration + implementation)

## 🟡 HIGH (Limits Usefulness)

### #4: Repair Command Non-Functional
- **File:** `src/hashall/repair.py`
- **Problem:** 15-line stub, does nothing
- **Impact:** Can't use hashall for automated repairs
- **Fix:** Implement rsync integration
- **Effort:** 2-3 hours

### #5: Test Coverage Minimal
- **Location:** `tests/`
- **Problem:** Only 228 lines, no E2E tests
- **Impact:** Can't prove correctness, regression risk
- **Fix:** Add scan→export→verify roundtrip test
- **Effort:** 30 minutes for basic E2E

## 🟢 MEDIUM (Nice to Have)

### #6: Parallel Mode Not Implemented
- **File:** `src/hashall/scan.py`
- **Problem:** Flag accepted but ignored
- **Impact:** Slower scans on large datasets
- **Fix:** Add ThreadPoolExecutor for hashing
- **Effort:** 1 hour

---

## Fix Order

**Phase 1 (Do Now):**
1. Fix #1 (treehash) — prevents crashes
2. Fix #2 (export path) — enables session caching
3. Fix #3 (hardlinks) — required for ZFS use case
4. Add E2E test (#5) — proves fixes work

**Phase 2 (Later):**
5. Implement repair (#4)
6. Add parallel mode (#6)

**Total time to production-ready:** ~2 hours (Phase 1 only)
