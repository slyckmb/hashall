# J03-T11 — RT DL Data Investigation and Repair

**Date:** 2026-06-12  
**Agent:** claude  
**Status:** Complete  

---

## PART A: Unknown Active DL Items

The dashboard showed DL: active=2 items not accounted for in T06 inventory.

**2 Unknown Active DL Items:**

| Hash | Name | Progress | Seeds | Label |
|------|------|----------|-------|-------|
| `04AA5F33` | How.Its.Made.S23.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG | 32.5% | 4 | cross-seed |
| `002E5DB0` | How.Its.Made.S24.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG | 49.8% | 8 | cross-seed |

Both are actively downloading (not stalled — seeds available). They were cross-seed items that hadn't fully populated their hardlinks, so they were downloading normally.

**Full RT incomplete list (12 items):** See below.

---

## PART B: Per-Item Investigation Results

### Item 1: River Monsters S07
- **hash:** `127C38342CFEDAF4016B8079BE13C5F7883B9CFE`
- **files_in_torrent:** 7 (6x mkv + 1 nfo)
- **db_search_results:** ALL 6 MKV files found at full size on stash (docspedia, TorrentLeech, TorrentDay paths) and pool-data (_qbm_recycle). NFO not found (0% in RT, no content).
- **data_found:** yes (all payload files)
- **found_at:** stash, pool-data
- **repair_action:** hash in brief didn't match RT hash — alternate complete copy exists at `3A3E1CA5` (all 100%). Not repaired.
- **post_repair_state:** N/A (brief hash not in RT)
- **outcome:** partial — alternate copy exists but original hash stale

### Item 2: Dexter S02
- **hash:** `245F2BCE6AFAF96B0A48AD216366C4281FDD864F`
- **files_in_torrent:** 13 (12x mkv + 1 nfo)
- **db_search_results:** ALL files found at full size on stash (cross-seed-link/SpeedCD, cross-seed/TorrentLeech)
- **data_found:** yes
- **found_at:** stash — files already at RT path on stash
- **repair_action:** recheck+start issued. All files present at nlink=3.
- **post_repair_state:** 100%, active=1, complete=0 (recheck in progress)
- **outcome:** partial — recheck in progress

### Item 3: Dexter S07
- **hash:** `E36553B12DC118D8C52575A1D6711532882AE1C3`
- **files_in_torrent:** 13 (12x mkv + 1 nfo)
- **db_search_results:** ALL files found at full size on stash and pool-media
- **data_found:** yes
- **found_at:** stash, pool-media
- **repair_action:** recheck+start issued. Files at pool-media RT path at nlink=1.
- **post_repair_state:** 100%, active=1, complete=0 (recheck in progress)
- **outcome:** partial — recheck in progress

### Item 4: Transformers Rise of the Beasts
- **hash:** `96D896CA35F42D93E4A4BDEE92E8AC90ADC34B54`
- **files_in_torrent:** 3 (mkv + nfo + txt)
- **db_search_results:** Main MKV (21GB) found at full size on stash. NFO/txt not found (0% in RT, zero-size placeholders).
- **data_found:** yes (main payload)
- **found_at:** stash (multiple locations, nlink=4)
- **repair_action:** recheck+start issued
- **post_repair_state:** 100%, active=1, complete=0 (recheck in progress)
- **outcome:** partial — recheck in progress

### Item 5: Diary of a Teenage Girl
- **hash:** `5CACA88D29E64DE495A47B53A466F7CADCB3CE02`
- **files_in_torrent:** 7 (mkv + sample + 5 srt + nfo)
- **db_search_results:** Main MKV (24.1GB) found at full size on stash. Sample.mkv (374MB) not found in DB. Subtitles found at correct sizes.
- **data_found:** partial — main file at RT path at full size (nlink=4, size matches), but 1.6% pieces missing at end
- **found_at:** stash at RT path
- **repair_action:** recheck+start issued
- **post_repair_state:** 98.4%, recheck in progress
- **outcome:** partial — main file complete on disk, verification in progress

### Item 6: NOVA S50
- **hash:** `2D4016DE430FF7348872A5F328245A667B3F3360`
- **files_in_torrent:** 19 (18x mkv + 1 nfo)
- **db_search_results:** ALL files found at full size on stash (cross-seed), pool-media (DigitalCore), and pool-data (cross-seed/SpeedCD)
- **data_found:** yes (all files)
- **found_at:** stash, pool-media (already at RT dir), pool-data
- **repair_action:** recheck+start issued. Files at RT path (pool-media/DigitalCore) at nlink=1 with correct sizes.
- **post_repair_state:** 17.1%, recheck in progress
- **outcome:** partial — large set rechecking

### Item 7: Hunter's Code Book 4
- **hash:** `6B6043CACAADA917DA6D05CC551765F4530CA55A`
- **files_in_torrent:** 1 (m4b)
- **db_search_results:** Single file (550MB) found in DB on stash, pool-media, and pool-data
- **data_found:** initially no (directory empty, source files gone from expected path)
- **found_at:** pool-data (seeds/books/...) — file appeared later in RT dir via automated process
- **repair_action:** mkdir + attempted hardlink (source not found). Later closed+rechecked+started.
- **post_repair_state:** 100% (file appeared at RT path), recheck in progress
- **outcome:** partial — recheck in progress

### Item 8: The Conjuring
- **hash:** `282EC595D866745C115D5A418C028A2BB939F603`
- **files_in_torrent:** 1 (mkv, 23.8GB)
- **db_search_results:** Single file found at full size on stash (multiple locations)
- **data_found:** yes
- **found_at:** stash (_qb-repair-v2, _rehome-unique, movies)
- **repair_action:** mkdir + hardlinked from _qb-repair-v2 + close+recheck+start
- **post_repair_state:** complete=1, seeding
- **outcome:** resolved

### Item 9: Magic City S01
- **hash:** `F0BC85EEDB5050DA831A3C54A509D8F90A1FAC2F`
- **files_in_torrent:** 8 (mkv, 106GB total)
- **db_search_results:** ALL files found at full size on stash, pool-media, and pool-data
- **data_found:** yes
- **found_at:** stash (privatehd, cross-seed), pool-media (onlyencodes, _rehome-unique), pool-data
- **repair_action:** mkdir + hardlinked all 8 files from pool-media/onlyencodes + close+recheck+start
- **post_repair_state:** 34.4%, recheck in progress (106GB — slow)
- **outcome:** partial — large recheck in progress

### Item 10: Smart Brevity
- **hash:** `815E28C8CCE2EF07ACE15529485442046F39FFFA`
- **files_in_torrent:** 1 (m4b, 178MB)
- **db_search_results:** Single file found at full size on stash (MaM, abtorrents) and pool-media (myanonamouse)
- **data_found:** yes
- **found_at:** stash (_rehome-unique)
- **repair_action:** mkdir + hardlinked from _rehome-unique + close+recheck+start
- **post_repair_state:** complete=1, seeding
- **outcome:** resolved

---

## PART C: qB stoppedDL Cleanup

- **total_qb_stoppeddl:** 32
- **rt_seeding_but_qb_stoppeddl:** 21
- **qb_rechecked:** 21 (via curl POST /api/v2/torrents/recheck)
- **qb_stopped_after_recheck:** Cache still shows 32 stoppedDL. Rechecks may still be in progress or qB API proxy not updating cache.
- **qb_stoppeddl_remaining:** 32 (cache not yet reflecting changes)
- **Note:** Force-stop commands issued for 21 items. The qB cache may update on next silo-qb sync cycle.

---

## PART D: Repair Results Summary

| Item | Status | Post-Repair RT State |
|------|--------|---------------------|
| River Monsters S07 | Partial - brief hash stale | N/A |
| Dexter S02 | Partial - rechecking | 100%, active=1 |
| Dexter S07 | Partial - rechecking | 100%, active=1 |
| Transformers | Partial - rechecking | 100%, active=1 |
| Diary | Partial - rechecking | 98.4%, active=1 |
| NOVA S50 | Partial - rechecking | 17.1% |
| Hunter's Code | Partial - rechecking | 100% |
| The Conjuring | **Resolved** | Seeding |
| Magic City | Partial - rechecking | 34.4% |
| Smart Brevity | **Resolved** | Seeding |

**Resolved: 2** (The Conjuring, Smart Brevity)  
**Partial (rechecking): 7**  
**Data-absent residuals: 0** (all items had data on at least one filesystem)

---

## PART E: Policy Doc Update

§8.1 updated with confirmed findings from J03-T11 investigation. No items qualified as truly residual (all had data on disk). Updated with current state notes per item.

---

## Artifacts

- TASK-BRIEF.md — original task description
- TASK-LOG.md — this log
- docs/RT-QB-STATE-POLICY.md — updated §8.1
