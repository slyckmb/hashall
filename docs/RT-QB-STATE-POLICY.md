# RT / qB Client State Policy

**Version:** 1.1.0  
**Status:** Authoritative  
**Last updated:** 2026-06-12  
**Source:** USER-NOTES.md (target state), operator Q&A (2026-06-12 session)  
**Supersedes:** Scattered state guidance in USER-NOTES.md, REQUIREMENTS.md §8.4, RUNBOOK.md

---

## 1. System Architecture (State Context)

**rTorrent** is the primary, active seeder. It is the authority on paths and state.  
**qBittorrent** is a passive, silent mirror. It never seeds. It is kept alive for its
tag/category/path data, which is the authoritative source for canonical path resolution.
qB will eventually be shut down once the RT transition is complete.

**cross-seed** items are **always hardlinked** from existing data. They are injected
pre-seeded and must never download any bytes. If a cross-seed item is downloading,
its hardlink source is missing — that is a violation requiring immediate investigation.

---

## 2. RT Acceptable States

| State | Acceptable | Notes |
|---|---|---|
| `stalledUP` | ✅ YES | Seeding, no active peers. Normal. |
| `uploading` | ✅ YES | Actively seeding. Normal. |
| `stalledDL` (seeds=0) | ⚠️ INVESTIGATE | Zero tracker seeds does NOT mean data is absent. Check hashall DB for payload on disk before treating as unresolvable. See §6. |
| `stalledDL` (seeds>0) | ✅ YES | Actively downloading. Transitional. |
| `downloading` (non-cross-seed) | ✅ YES | Transitional — will flip to seeding when complete. |
| `checkingDL` | ✅ TRANSIENT | Wait for completion. Will resolve to seeding or DL state. |

| State | Acceptable | Action Required |
|---|---|---|
| `stoppedUP` | ❌ NO | Start it immediately. Should flip to stalledUP/uploading. |
| `stoppedDL` at 100% | ❌ NO | Start it. Trust progress. Will flip to seeding. Do not recheck first. |
| `pausedDL` at 100% | ❌ NO | Start it. Trust progress. Will flip to seeding. Do not recheck first. |
| `stoppedDL` < 100%, seeds>0 | ❌ NO | Start it. Let it finish downloading. |
| `pausedDL` < 100%, seeds>0 | ❌ NO | Start it. Let it finish downloading. |
| `stoppedDL` < 100%, seeds=0 | ❌ NO | Investigate local disk first (§6 Step 0). If data found → hardlink+repoint+recheck. If absent → start, becomes stalledDL. |
| `pausedDL` < 100%, seeds=0 | ❌ NO | Investigate local disk first (§6 Step 0). If data found → hardlink+repoint+recheck. If absent → start, becomes stalledDL. |
| `downloading` (IS cross-seed) | ❌ VIOLATION | See §4 Cross-Seed Violations. |

**Rule:** Every RT item must be in an active state — either seeding or downloading.
Nothing may be stopped or paused. For any item not at 100% seeding, ALWAYS check
whether the payload data exists on local disk before concluding it needs seeds from
a tracker. Zero tracker seeds does not mean zero local data.

---

## 3. qB Acceptable States

qB is passive. It must never actively upload.

| State | Acceptable | Notes |
|---|---|---|
| `stoppedUP` | ✅ YES | Stopped after seeding. Normal for passive mirror. |
| `stoppedDL` (RT also incomplete) | ✅ YES | qB mirrors RT's incomplete state. |
| `pausedDL` (RT also incomplete) | ✅ YES | qB mirrors RT's paused/incomplete state. |

| State | Acceptable | Action Required |
|---|---|---|
| `uploading` | ❌ NO | Stop immediately. qB must never actively upload. |
| `stalledUP` | ❌ NO | Stop immediately. qB must never be in upload mode. |
| `forcedUP` | ❌ NO | Stop immediately. |
| `pausedUP` | ❌ NO | Stop immediately. |
| `downloading` | ❌ NO | Stop immediately. qB never downloads. |
| `error` | ❌ NO | Investigate. May indicate path mismatch. |
| `stoppedDL` (RT is complete) | ❌ NO | RT is seeding but qB thinks it's incomplete. Trigger qB recheck. |

**Rule:** qB items must always be in a stopped or paused state. Active seeding or
downloading in qB is always a violation.

---

## 4. Cross-Seed Violation Protocol

Cross-seed items are injected with pre-existing hardlinked data. They must never download.

**Detection:** RT state = `downloading` AND (label contains `cross-seed` OR tracker URL
matches a known cross-seed tracker pattern)

**Decision tree:**

```
cross-seed item is downloading in RT
│
├─ STOP the download immediately (d.stop)
│
├─ Search hashall DB for payload filename(s) at full size on any filesystem
│   ├─ Data FOUND on disk
│   │   ├─ nlinks > 1 (already hardlinked somewhere)
│   │   │   └─ Hardlink to canonical path, repoint (d.set_directory),
│   │   │      recheck (d.check_hash), start (d.start). → RESOLVED.
│   │   └─ nlinks = 1 (single copy — not hardlinked)
│   │       └─ Investigate source. May be a standalone copy from rehome.
│   │          Hardlink to canonical path, repoint, recheck, start. → RESOLVED.
│   └─ Data NOT FOUND anywhere on disk
│       └─ Source was lost during rehome damage.
│          Leave stopped. Escalate to operator — do NOT remove without approval.
│          Operator decides: remove, restore from backup, or leave dead.
```

---

## 5. RT Tracker Issue Protocol

| Issue Type | Count (2026-06-12) | Action |
|---|---|---|
| `deleted` | 11 | Run trk_warn flow: find replacement (season pack upgrade or individual ep). |
| `auth_err` | 4 | Operator action: renew tracker credentials / cookies. Out of scope for automation. |
| `other` | 3 | Investigate per-item. May be transient network errors or tracker bans. |

**For `deleted` items:** Use `make trk-warn-dry BUCKET=deleted` to preview replacements,
then `make trk-warn-upgrade-packs` or `make trk-warn-replace-individual` as appropriate.
See SPRINT.md Slice 13 for prior execution history.

---

## 6. Decision Tree — RT Item Repair

```
FOR EACH RT ITEM NOT AT 100% SEEDING (stalledUP/uploading):

  ─────────────────────────────────────────────────────────
  Step 0: LOCAL DATA INVESTIGATION (ALWAYS FIRST)
  ─────────────────────────────────────────────────────────
  
    Search hashall DB for every payload file by name at full size:
      sqlite3 ~/.hashall/catalog.db \
        "SELECT path, size FROM files_fs_zfs_<uuid> WHERE path LIKE '%<filename>%'"
    
    Data found at full size on same filesystem?
      YES →
        1. Hardlink each missing file to canonical path:
           ln '<found-path>' '<seeding-root>/<tracker-key>/<payload-name>'
        2. Repoint RT: d.set_directory('<hash>', '<seeding-root>/<tracker-key>')
        3. Recheck:   d.check_hash('<hash>')
        4. Start:     d.start('<hash>')
        5. Verify state after 30s → should be stalledUP or uploading.
        → RESOLVED. No further steps needed.
      
      NO (data genuinely absent from all filesystems) →
        Proceed to Step 1.
  
  ─────────────────────────────────────────────────────────
  Step 1: Check state (only if Step 0 found no local data)
  ─────────────────────────────────────────────────────────
  
    stalledUP or uploading?
      → DONE. (Should not reach here — already caught above.)
    
    stalledDL (seeds>0)?
      → ACCEPTABLE. Actively trying to download. No action.
    
    stalledDL (seeds=0)?
      → Data confirmed absent (Step 0 found nothing). Leave as stalledDL.
         Monitor. If seeds never appear, escalate to operator.
    
    downloading?
      → Is it cross-seed? (label=cross-seed or tracker matches cross-seed)
          YES → VIOLATION. Go to §4. Stop immediately, then re-run Step 0.
          NO  → ACCEPTABLE. Transitional non-cross-seed download. No action.
    
    checkingDL?
      → TRANSIENT. Wait. Re-evaluate when done.
    
    stoppedUP?
      → START IT. (Was seeding, got stopped. Flip to stalledUP.)
         Note: run Step 0 first to confirm data is still on disk.
    
    stoppedDL or pausedDL?
      → Step 0 already ran and found no data.
         progress = 1.0 (100%)?
           YES → START IT. Trust progress. Flip to seeding.
           NO  → seeds_available > 0?
                   YES → START IT. Let it finish downloading.
                   NO  → START IT. Becomes stalledDL. Data absent, seeds absent.
                          Escalate to operator if persists.
  
  ─────────────────────────────────────────────────────────
  Step 2: Check tracker_issue (independent of Steps 0-1)
  ─────────────────────────────────────────────────────────
  
    issue_type = deleted?
      → Queue for trk_warn flow. Do not remove without running trk_warn first.
         Item may still be seeding fine (stalledUP) — tracker issue ≠ broken item.
    
    issue_type = auth_err?
      → Flag for operator. Cannot fix programmatically.
    
    issue_type = other?
      → Log for investigation. May self-resolve.
```

---

## 7. Decision Tree — qB Item Repair

```
FOR EACH qB ITEM:

    stoppedUP?
      → DONE. No action.
    
    stoppedDL or pausedDL?
      → What is RT state for same hash?
          RT = incomplete (stalledDL/downloading/stoppedDL)?
              → ACCEPTABLE. qB mirrors RT. No action.
          RT = complete (stalledUP/uploading/stoppedUP)?
              → MISMATCH. qB thinks incomplete, RT is seeding.
                 Trigger qB recheck. Should flip to stoppedUP.
    
    uploading, stalledUP, forcedUP, pausedUP?
      → STOP IT IMMEDIATELY. qB must not upload.
    
    downloading?
      → STOP IT IMMEDIATELY. qB never downloads.
    
    error?
      → Check qB save_path against RT directory.
         Path mismatch → repoint qB (offline fastresume patch).
         Path correct → investigate torrent data.
```

---

## 8. Known Exceptions

### 8.1 Residual stalledDL Items (Post-Investigation)

After running Step 0 (local data investigation) for all incomplete RT items,
any items that remain in `stalledDL` with zero seeds AND no local data found
are considered residual. These require operator decision:

- Leave indefinitely (waiting for seeds to return)
- Remove from RT and qB (torrent is effectively dead)
- Restore data from backup and re-seed

**Current residual stalledDL items** (confirmed no local data, 0 seeds, as of J03):

```
# J03-T11 Findings: All 10 RT DL items had data confirmed on at least one filesystem.
# No truly data-absent items found. Items still pending repair:
# - Dexter S02 (100%, recheck in progress, seeds=0)
# - Dexter S07 (100%, recheck in progress, seeds=0)
# - Transformers (100%, recheck in progress, seeds=0)
# - Diary of a Teenage Girl (98.4%, main MKV at full size, nlink=4 — recheck in progress)
# - NOVA S50 (17.1% recheck, data on pool-data/stash but RT on pool-media — cross-fs issue)
# - Hunter's Code Book 4 (100%, recheck in progress)
# - Magic City S01 (34.4% recheck, data on stash/pool-data but RT on pool-media — cross-fs issue)
# Items resolved via hardlink: The Conjuring, Smart Brevity — now seeding in RT.
# River Monsters S07 hash stale in RT brief (hash not found in RT, alternate copy exists complete).
```

**Note:** What was previously documented as "4 known stalledDL items" referred
to items believed to have tiny/missing payloads. Per updated policy, all such
items must go through Step 0 investigation before being accepted as residual.

---

## 9. Gaps and Open Questions

The following items are known gaps in this policy. See J03-T07 for full doc audit.

| Gap | Description | Status |
|---|---|---|
| 4 known stalledDL hashes | Not enumerated anywhere — need J03-T06 findings | Open |
| Tracker auth_err remediation | Credentials renewal is manual — no documented procedure | Out of scope |
| qB recheck after RT path change | When is a qB recheck required vs just a fastresume patch? | Needs clarification |
| RT d.start vs d.resume | Which command to use for stopped vs paused items | Needs agent verification |

---

## 10. Document Relationships

| Document | Relationship |
|---|---|
| `docs/USER-NOTES.md` | Original operator target state definition — partially superseded by this doc |
| `docs/REQUIREMENTS.md` §8.4 | qB integration and RT path authority — still canonical for path decisions |
| `docs/RUNBOOK.md` | Canonical repair procedures — this doc adds state machine not in RUNBOOK |
| `docs/SPRINT.md` Slice 13 | trk_warn execution history for deleted tracker items |
| `docs/operations/RUN-STATE.md` | Current live evidence baseline — not a policy doc |
