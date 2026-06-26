# R4: Payload + CLI Mutation Audit

**Date:** 2026-06-17
**Task:** J09-T04
**Scope:** Cold-read audit of `payload.py` and mutation-relevant sections of `cli.py`

---

## F1 — Orphan GC can race with concurrent scan/rt changes

**File:** `src/hashall/payload.py:694-702`, `src/hashall/cli.py:1469-1481`
**Severity:** Medium

### Description

`prune_orphan_payloads()` selects candidates at line 660-673 with a LEFT JOIN that checks for zero torrent_instances refs. Then at line 698 it checks `count_active_files_for_path()` for live files. Between these two queries and the actual DELETE at lines 791-798, a concurrent process could:

1. Insert a new torrent_instance (sync from another process)
2. Delete files from the files_{device_id} table (scan re-run with files removed)

### Reproduction

- Run `payload sync` (non-dry) with a large payload set
- While it's in the prune phase, run a `scan` on a path that removes files from catalog
- GC may delete payloads that still have live files (scan still running) or may keep payloads that should be deleted

### Proposed fix

Wrap the GC check-to-delete sequence inside a tighter transaction with explicit `SELECT ... FOR UPDATE` or use a two-phase commit pattern: first mark payloads for deletion in a temp table, then verify files still don't exist, then delete.

---

## F2 — Payload sync fcntl lock only protects against concurrent sync, not scan

**File:** `src/hashall/cli.py:932-944`
**Severity:** Medium

### Description

The fcntl.flock at cli.py:938 uses `LOCK_EX | LOCK_NB` on `payload-sync.lock`. This is an **advisory lock** scoped to the lock file. It only prevents concurrent `payload sync` processes from the same DB directory. It does NOT protect against:

- Concurrent `hashall scan` (which writes to files_{device_id} directly)
- External SQLite connections
- Scripts or tools that modify the catalog outside hashall

The GC phase (line 1469-1481) inherits this same vulnerability — it runs under the same lock, but the lock doesn't gate non-sync writers.

### Reproduction

- Run `payload sync` (long-running with --upgrade-missing)
- Simultaneously run `scan --hash-mode upgrade` on a root under the same device
- Both modify the files_{device_id} table; scan updates sha256 values while GC reads them

### Proposed fix

Use SQLite's built-in locking or a WAL-mode transaction to serialize catalog writes. Alternatively, acquire a shared lock scope for the catalog database itself rather than a sidecar lock file.

---

## F3 — Upgrade state file + upsert race on crash

**File:** `src/hashall/cli.py:1416-1421`, `src/hashall/cli.py:1425-1431`
**Severity:** Low

### Description

After upgrade completes for a root, the code at line 1416-1421 calls `upsert_payload(conn, refreshed, commit=False)` without immediate commit — it relies on the batch counter at line 1419. Then at line 1425-1431 it writes the completed root to the upgrade state file. If the process crashes between the `_write_payload_sync_upgrade_state` call and the next batch commit, the state file records the root as complete but the DB payload row still has the old (incomplete) hash. On resume, `count_missing_sha256_for_path` returns 0 (hashes are filled), so the root is skipped as "already complete" — but the payloads table's `payload_hash` is stale.

### Reproduction

1. Run `payload sync --upgrade-missing` with a root that has missing SHA256s
2. Kill the process right after line 1431 `_write_payload_sync_upgrade_state` executes but before the batch commit at line 1419-1420
3. Re-run: root is skipped (hashes are present in files table), but payloads row still has old hash

### Proposed fix

Swap the order: commit the upsert before writing the state file, or make the state file write conditional on a successful commit.

---

## F4 — save-path-repair continues on individual errors but exceptions propagate

**File:** `src/hashall/cli.py:2496-2504`
**Severity:** Medium

### Description

The `payload save-path-repair` loop at cli.py:2497 iterates through all actions and collects results in a list. Individual `execute_repair` errors do NOT break the loop — results accumulate. However, if `execute_repair` raises an unhandled exception (not a return with error status), the entire loop crashes, leaving a partial state: some hashes moved, some not.

What's left behind on partial failure:
- Hashes processed before the crash: files moved to canonical paths
- Hashes after the crash: files still in staging dirs
- The report is never printed (`format_repair_report` at line 2503 never runs)

### Reproduction

1. Have 100 hashes in staging dirs
2. Run `payload save-path-repair --execute`
3. Hash #50 causes an unhandled exception in `execute_repair` (missing dir, permission error, etc.)
4. Hashes 1-49 moved, hashes 50-100 still in staging, no report output

### Proposed fix

Wrap each `execute_repair` call in try/except, capture exception as error in the result, and continue. Only crash after the loop if any critical failures occurred, so the report is always generated.

---

## F5 — DB commits before filesystem verification

**File:** `src/hashall/payload.py:791-798`, `src/hashall/cli.py:1191-1205`
**Severity:** Low-Medium

### Description

`prune_orphan_payloads()` deletes from `payloads` table based on `count_active_files_for_path()` which reads from the catalog (files_{device_id}), not from the live filesystem. Similarly, `upsert_payload` at cli.py:1191 commits whether or not the filesystem state matches the catalog.

This is by design — the system treats the catalog as truth. But if the catalog is stale (no recent scan), then:
- Orphan GC may prune payloads whose files were recently added but not scanned yet
- Payload sync may build incomplete payloads from a stale file catalog

### Proposed fix

Document the assumption explicitly. Consider adding a "catalog age" check before GC: if files_{device_id} last_modified is older than N hours, warn or skip GC.

---

## F6 — Unnecessary COUNT(*) on every prune_orphan_payloads call

**File:** `src/hashall/payload.py:675-677`
**Severity:** Low

### Description

The `total_payloads = COUNT(*)` query at line 675-677 runs unconditionally, even when there are zero candidates (empty scope or no orphan payloads). This is used only for the spike-detection threshold (line 777). For the common case where no candidates exist, this overhead is wasted.

### Proposed fix

Move the `total_payloads` query inside the `if candidates:` guard block at line 709. Only compute total when there are actually candidates to evaluate.

---

## F7 — Orphan GC skipped when --limit > 0

**File:** `src/hashall/cli.py:1469`
**Severity:** Low

### Description

At cli.py:1469-1481, `prune_orphan_payloads()` is only called when `limit == 0`. When `--limit N` is used for a partial sync (e.g., troubleshooting or pilot runs), orphans are never GC'd. This means partial syncs accumulate orphan payloads indefinitely.

This is documented by the output at line 1537 ("orphan payload prune: skipped (limit applied)"), but could surprise operators running repeated limited syncs.

### Proposed fix

Consider a separate `--orphan-gc` flag or always run GC regardless of limit. If the concern is that GC with a partial scope is unsafe, use the existing `roots` parameter to scope GC to the path_prefix set.

---

## F8 — Inode key collision across filesystems

**File:** `src/hashall/payload.py:1070`
**Severity:** Low

### Description

In `upgrade_payload_missing_sha256()`, inode groups are keyed by `(inode, size)` at line 1070. Inode numbers are only unique within a single filesystem (device). If the same `device_id` spans multiple mount points (e.g., bind mounts, ZFS datasets), the same `(inode, size)` pair could refer to different files on different filesystems.

The `device_id` is derived from `os.stat(root_path).st_dev` at line 1020-1024, which resolves to the device of the root path. If the payload root crosses dataset boundaries (nested datasets), the inode lookup could return false matches.

### Proposed fix

Include `st_dev` in the inode group key, or validate that paired inodes resolve to the same filesystem before collapsing.

---

## Summary

| ID | Severity | Category | File:Line |
|----|----------|----------|-----------|
| F1 | Medium | Race condition | payload.py:694-702, cli.py:1469-1481 |
| F2 | Medium | Concurrency | cli.py:932-944 |
| F3 | Low | Crash consistency | cli.py:1416-1431 |
| F4 | Medium | Error handling | cli.py:2496-2504 |
| F5 | Low-Medium | Stale data | payload.py:791-798 |
| F6 | Low | Performance | payload.py:675-677 |
| F7 | Low | Incomplete GC | cli.py:1469 |
| F8 | Low | Data integrity | payload.py:1070 |

---

## Specific questions answered

### Q1: Can orphan GC delete a payload that is still actively seeding?

**Yes — but only in a narrow window.** The GC checks torrent_instances refs then files_{device_id} active count in sequence. Between these two read checks and the DELETE, a concurrent process could add a ref or delete files. In practice the fcntl lock serializes sync processes. The highest-risk scenario is a concurrent `scan` removing files while GC reads the catalog. Mitigation: the two-phase staging (first mark, then age-delete) means a payload must be seen as orphan across multiple sync runs + 24h before deletion, which dramatically reduces the window.

### Q2: Does the payload sync lock protect against all concurrent access?

**No.** It's an advisory fcntl lock on a sidecar file. It protects against concurrent `payload sync` runs only. Other hashall commands (`scan`, `verify-trees`) and external SQLite connections bypass it entirely.

### Q3: Is the DB left consistent if payload sync crashes mid-loop?

**Mostly yes.** Batch commits at 400 ops bound partial writes. Each batch is atomic for one torrent (payload upsert + torrent_instance upsert). The upgrade phase has a state file for resume. The one exception (F3): the state file records completion before the upsert is committed, creating a stale hash on resume.

### Q4: Does save-path-repair stop on first error or continue?

**Continues on individual errors, crashes on exceptions.** The loop collects per-item results and does NOT break on error returns from `execute_repair`. However, unhandled exceptions in `execute_repair` propagate and terminate the loop early, leaving partial state (F4).

### Q5: Are there DB-before-filesystem operations?

**Yes.** `upsert_payload`, `prune_orphan_payloads`, and all `upsert_torrent_instance` calls operate on catalog state without live filesystem verification (F5). This is by design but assumes a recent scan has populated the files table accurately.
