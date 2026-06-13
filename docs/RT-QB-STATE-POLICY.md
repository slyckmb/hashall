# RT / qB Client State Policy

**Version:** 1.3.0  
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
│   │   │   └─ Repair sequence (order matters):
│   │   │      1. Remove partial download files at RT path:
│   │   │         For each file at RT path with nlinks=1 AND pct < 100%:
│   │   │           rm '<rt_path>/<file>'  (NOT rm -rf — individual files only)
│   │   │      2. Remove empty directory artifacts left by rogue code:
│   │   │         For each empty dir at old path: rmdir '<old_empty_path>'
│   │   │      3. Hardlink complete files from source to canonical path:
│   │   │         ln -f '<source_path>/<file>' '<canonical_path>/<file>'
│   │   │      4. Repoint RT: d.set_directory('<hash>', '<canonical_dir>')
│   │   │      5. Recheck: d.check_hash('<hash>')
│   │   │      6. Start: d.start('<hash>')
│   │   │      → RESOLVED. Verify state=stalledUP after 30s.
│   │   └─ nlinks = 1 (single copy — not hardlinked)
│   │       └─ Same repair sequence as above. The single copy is the source.
│   └─ Data NOT FOUND anywhere on disk
│       └─ Source was lost during rehome damage.
│          Leave stopped. Escalate to operator — do NOT remove without approval.
│          Operator decides: remove, restore from backup, or leave dead.
```

**Note on rm vs rmdir:** Only use `rmdir` on confirmed empty directories (rogue code
artifact directories). Only use `rm` on individual partial download files (nlinks=1,
pct < 100%). Never use `rm -rf`.

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

**Quality rule for all replacements:**
- System runs **1080p only**. Never add 2160p/4K/UHD/HDR torrents.
- trk_warn scores Prowlarr results by: quality match (same resolution as original) →
  group match (same release group) → seeders → grabs → size.
- If only 2160p/4K is available → do not add. Report "no suitable 1080p replacement."
- After a replacement is added, verify the title contains `1080p` and does NOT contain
  `2160p`, `4K`, `UHD`.

**ARR label for replacement torrents:** See §8.2.

---

## 6. Decision Tree — RT Item Repair

```
FOR EACH RT ITEM NOT AT 100% SEEDING (stalledUP/uploading):

  ─────────────────────────────────────────────────────────
  Step 0: LOCAL DATA INVESTIGATION (ALWAYS FIRST)
  ─────────────────────────────────────────────────────────
  
    Search hashall DB for every payload file by name at full size.
    The DB uses per-filesystem tables (NOT the empty `files` table):

      Key filesystem tables (all scanned daily):
        stash/media → files_fs_zfs_4624186565346049802  (/stash/media = /data/media in RT/qB)
        pool-media  → files_fs_zfs_4673783476987974510  (/pool/media)
        pool-data   → files_fs_zfs_7422444370835627448  (/pool/data)

      Query (run for each table):
        sqlite3 ~/.hashall/catalog.db \
          "SELECT path, size FROM files_fs_zfs_<uuid> WHERE path LIKE '%<filename>%' AND size > 0"

      Note: paths in the stash table are relative to /stash/media (e.g. torrents/seeding/...).
      RT reports paths as /data/media/... which maps to /stash/media/... on the host.
    
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
                 Step 1: Trigger qB recheck. Should flip to stoppedUP.
                 Step 2: If recheck fails or stuck at 0% → see §7.1 (fastresume fix).
    
    stoppedDL at 0% AND RT is complete AND recheck fails?
      → Fastresume qBt-downloadPath artifact. See §7.1.
    
    uploading, stalledUP, forcedUP, pausedUP?
      → STOP IT IMMEDIATELY. qB must not upload.
    
    downloading?
      → STOP IT IMMEDIATELY. qB never downloads.
    
    error?
      → Check qB save_path against RT directory.
         Path mismatch → repoint qB (setLocation API or §7.1 fastresume patch).
         Path correct → investigate torrent data.
```

---

## 7.1 qB Fastresume `qBt-downloadPath` Fix

**Symptom:** qB item is stoppedDL at 0% even though:
- RT is at 100% complete and seeding
- Data file(s) exist on disk at the expected path
- qB recheck returns 0% every time
- `content_path` in qB API shows `/incomplete_torrents/...` instead of the seeding path

**Root cause:** The qB fastresume file has a stale `qBt-downloadPath` entry (e.g.
`/incomplete_torrents`) that overrides `qBt-savePath`. qB uses the raw `save_path`
key (not `qBt-savePath`) for recheck. When both are set, `save_path` wins and points
to the wrong location.

**Fix — delete and re-add via .torrent file (preferred, works while qB is running):**

```bash
HASH=<infohash>
TORRENT=/dump/docker/gluetun_qbit/rtorrent_vpn/.session/${HASH^^}.torrent
SAVE_PATH=<correct parent directory>   # parent of the torrent's content dir

# 1. Delete from qB (no file deletion)
curl -s -X POST http://localhost:9003/api/v2/torrents/delete \
  --data "hashes=$HASH&deleteFiles=false"

# 2. Re-add via .torrent file with correct save path (stopped)
curl -s -X POST http://localhost:9003/api/v2/torrents/add \
  -F "torrents=@$TORRENT" \
  -F "savepath=$SAVE_PATH" \
  -F "category=<original_category>" \
  -F "stopped=true"

# 3. Recheck
curl -s -X POST http://localhost:9003/api/v2/torrents/recheck \
  --data "hashes=$HASH"
# → Should flip to stoppedUP at 100%
```

**Fix — offline fastresume patch (requires stopping qB or patching between flushes):**

```python
from pathlib import Path
from hashall.fastresume import patch_fastresume_file

result = patch_fastresume_file(
    Path(f"/dump/docker/gluetun_qbit/rtorrent_vpn/.session/{HASH.upper()}.fastresume"),  # note: qB BT_backup, not RT session
    target_save_path=SAVE_PATH,
    backup_suffix=".bak",
)
# Then trigger recheck in qB — but only if qB doesn't immediately overwrite the file.
# qB overwrites fastresume on state changes; the delete-and-readd approach is safer.
```

**Important: setLocation API does NOT fix this.**
Calling `POST /api/v2/torrents/setLocation` updates `qBt-savePath` in the fastresume
but does NOT update `save_path`. When `qBt-downloadPath` is also set, qB ignores
`qBt-savePath` and uses `save_path` (which still points to `/incomplete_torrents`).
The delete-and-readd approach is the only reliable fix while qB is running.

**Note:** `qBt-downloadPath` artifacts were introduced during the Feb-2026 disaster
when `qBt-downloadPath` caused 2103 torrents to become stoppedDL on restart. Any
torrent that was mid-download during that incident may have this artifact.

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

### 8.2 ARR Label Protocol for Replacement Torrents

When adding a replacement torrent for ARR-managed content (Sonarr, Radarr, etc.),
the RT label MUST be the **download-stage label**, not the seeding label.

**Why:** ARR apps monitor the download-stage label for completed items to trigger
import. After import, the ARR flips the label to the seeding label. If you add a
replacement with the seeding label, the ARR never sees it and never imports the files
into the media library.

| ARR | Download-stage label (use this) | Seeding label (RT uses after import) |
|-----|--------------------------------|--------------------------------------|
| Sonarr | `sonarr` | `tv` |
| Radarr | `radarr` | `movies` |
| Lidarr | `lidarr` | `music` |
| Readarr | `readarr` | `ebooks` |
| Speakarr | `speakarr` | `audiobooks` |

**Rule:** When adding a replacement torrent to RT that should trigger ARR re-import
(repacks, season pack upgrades, individual ep replacements), always set the label
to the download-stage label (e.g. `sonarr`). After the ARR processes and imports,
it will automatically flip the label to the seeding label (`tv`).

**trk_warn handles this automatically** via `_arr_label_for_replacement()` in
`rt-tracker-manual-report.py`, which maps the existing item's label to the correct
download-stage label before adding the replacement.

**Manual add:** If adding a replacement outside of trk_warn, derive the correct
label from the item's current seeding label:
```python
seeding_to_download = {"tv": "sonarr", "movies": "radarr", "music": "lidarr",
                       "ebooks": "readarr", "audiobooks": "speakarr"}
download_label = seeding_to_download.get(current_label, current_label)
```

---

## 9. Gaps and Open Questions

The following items are known gaps in this policy. See J03-T07 for full doc audit.

| Gap | Description | Status |
|---|---|---|
| 4 known stalledDL hashes | Superseded — J03-T11 confirmed all had data on disk; no residuals | ✅ Resolved |
| Tracker auth_err remediation | Credentials renewal is manual — no documented procedure | Out of scope |
| qB recheck after RT path change | Documented in §7 and §7.1 — setLocation alone insufficient; use delete+readd | ✅ Resolved |
| RT d.start vs d.resume | J03 confirmed d.start() works for both stoppedDL and pausedDL; d.check_hash() must precede d.start() when data was just hardlinked | ✅ Resolved |

---

## 10. Document Relationships

| Document | Relationship |
|---|---|
| `docs/USER-NOTES.md` | Original operator target state definition — partially superseded by this doc |
| `docs/REQUIREMENTS.md` §8.4 | qB integration and RT path authority — still canonical for path decisions |
| `docs/RUNBOOK.md` | Canonical repair procedures — this doc adds state machine not in RUNBOOK |
| `docs/SPRINT.md` Slice 13 | trk_warn execution history for deleted tracker items |
| `docs/operations/RUN-STATE.md` | Current live evidence baseline — not a policy doc |
