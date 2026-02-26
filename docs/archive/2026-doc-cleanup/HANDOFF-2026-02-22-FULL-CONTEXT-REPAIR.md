# qbit-repair — Full Context Handoff

**Session start:** ~2026-02-22
**Last updated:** 2026-02-24
**Branch:** `chatrap/claude-hashall-20260223-124028`
**Worktree:** `/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028`

---

## Problem Statement

~2103 qBittorrent torrents stuck in `stoppedDL` state due to `qBt-downloadPath` being set in their `.fastresume` files. When QB starts, it rechecks at the wrong (stale download) path instead of the actual `save_path` where content lives, causing the torrent to stop as incomplete.

**Goal:** Repair all ~2103 stoppedDL torrents → stoppedUP (seeding) state.

---

## Root Cause

Two distinct sub-problems on stoppedDL torrents:

1. **`qBt-downloadPath` set in fastresume** — QB rechecks at old incomplete download path. Fix: clear this field. Requires QB container stop/start (API returns 400 for this change).

2. **Garbage/placeholder files at save_path** — Cross-seed downloads left sparse files. Fix: rebuild hardlinks from a good (stoppedUP 100%) partner torrent.

---

## Path Mapping (CRITICAL)

- `/stash` is NOT mounted in the qBittorrent container
- All stash content appears in QB as `/data/media/...`
- On host: `/data/media` and `/stash/media` are the **same filesystem** (bind mount, device 44)
- Pool paths: `/pool/data/...` — same in container and on host (device 231)
- Incomplete downloads: container `/incomplete_torrents` = host `/dump/torrents/incomplete_vpn`
- BT_backup: `/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/`
- QB container: `qbittorrent_vpn`
- QB API: `http://localhost:9003`

---

## Main Script: `bin/qbit-repair-batch.sh`

**Usage:** `bash bin/qbit-repair-batch.sh [--limit N] [--apply]`

Phases:
- **P0**: Discovery — finds stoppedDL torrents with a stoppedUP 100% partner (same `root_name` in catalog). Skips same-save-path pairs.
- **P1**: Content analysis via catalog DB — classifies each file: `already_hardlinked` / `dup_copy` / `garbage` / `missing` / `no_match`
- **P2**: Hardlink rebuild (same-fs) or setLocation (cross-fs) while QB still running
- **P3**: QB stop → delete incomplete files (inode-safe) → patch fastresumes → QB start
- **P4**: `recheckTorrents` for all hashes
- **P5**: Monitor all in parallel until terminal state (stoppedUP=success, stoppedDL=failure)
- **P6**: Update streak counter

Streak file: `~/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt`

---

## Other Scripts

- **`bin/qbit-start-seeding-gradual.sh [--apply]`** — Starts stoppedUP torrents in escalating batches (1,2,5,10,25,50,100,...), monitors 45s per batch for any that flip to downloading/checkingDL/missingFiles, halts and stops bad torrents if detected.
- **`bin/qbit-repair-payload-group.sh --good HASH --broken HASH [--apply]`** — Original single-pair debug script.

---

## Bugs Fixed

### BUG-1: Deletion of live seed files (FIXED ~Feb 22)
P3 deleted files that were the broken torrent's actual live seed file when `download_path == save_path` in the container (path strings differed on host due to /stash vs /data/media alias).
**Fix:** Inode-based safety check — skip deletion if target shares inode+device with good source or save_path file.

### BUG-2: QB moved partial files during restart (FIXED ~Feb 22)
Clearing `qBt-downloadPath` without deleting partial files caused QB to move garbage to save_path on restart, overwriting good hardlinks.
**Fix:** Delete files at download_path before QB restart (P3), with inode safety.

### BUG-3: Transient stoppedDL catch (FIXED Feb 23)
Monitor caught torrents at stoppedDL during brief checkingDL→stoppedDL→stoppedUP transition, recording them as failures.
**Fix:** Re-poll after 10s before recording stoppedDL as failure.

### BUG-4: Wall-clock timeout too short (FIXED Feb 24)
15-min wall-clock timer fired before QB's serial recheck queue drained for large batches (50+).
**Fix:** Per-torrent stagnation detection — only fires if torrent was >0% then stalled 10+ min.

### BUG-5: Stagnation on queued 0% torrents (FIXED Feb 24)
Stagnation timer fired on torrents queued at 0% that had never started checking.
**Fix:** `has_started` gate — stagnation only triggers if torrent has been >0% at some point.

### BUG-6: Pool-pool timing race (FIXED Feb 24)
Pool-pool torrents (save_path on `/pool/data/`) failed immediately to stoppedDL after recheckTorrents.
**Root cause:** recheckTorrents called while QB still in `checkingResumeData` state.
**Fix:** Retry recheck on stoppedDL detection in P5 + 120s grace for pool-pool pairs.

---

## Batch Results

| Date | Batch | Size | ✓ | ✗ | Streak After | Notes |
|------|-------|------|---|---|--------------|-------|
| ~Feb 22 | early (batches 1-3) | 5+10+10 | ~22 | ~4 | 0 | BUG-1, BUG-2 found & fixed; monitor timing false failures |
| Feb 23 | batch-10 | 10 | 9 | 1 | 0 | Azrael (cross-seed name variant, files missing) |
| Feb 23 | batch-10 | 10 | 10 | 0 | 10 | clean |
| Feb 23 | batch-20 | 20 | 20 | 0 | 30 | clean |
| Feb 24 | batch-50 (be122cd) | 50 | 21 | 29 | 0 | BUG-4: wall-clock timeout; 29 were checkingUP at timeout |
| Feb 24 | batch-50 (b7246e0) | 50 | 20 | 30 | 0 | BUG-5: stagnation on queued 0% torrents |
| Feb 24 | batch-50 (bc6b411) | 50 | 46 | 4 | 0 | BUG-6: 4 pool-pool failures |
| Feb 24 | batch-50 (b4345cd) | 50 | ~48 | 2 | 0 | BUG-6 fixed (pool-pool ✓); 2 persistent failures: 5fc73670 (Pink Floyd), 6b3471fd |

**Total confirmed repaired:** ~258 (2103 - 1845)
**Streak:** 0

---

## Known Issues (Unresolved)

- **Same-save-path pairs**: Skipped by P0. These need fastresume-only patch with no hardlink work. Count unknown. Not handled yet.
- **Trashy.Lady** (`43f589275bd8`): stoppedDL at 99.8%, missing ~0.2% of a BD50. No easy fix.
- **Legion S03** (`0782850032bf`, `20f1e09447b6`, `f38a29c856e9`, `4c11952b3840`): E08 corruption from early repair attempt. Good copy exists on stash but cross-fs copy needed. Deferred.
- **5fc73670** (Pink Floyd - The Division Bell): Persistent failure across batches. Likely missing files or catalog mismatch. Needs investigation.
- **6b3471fd**: Persistent failure. Needs investigation.

---

## Catalog DB

- Path: `~/.hashall/catalog.db`
- `files_231` = pool (`/pool/data/`), `files_44` = stash (`/stash/media/` = `/data/media/`)
- `quick_hash` = fast partial-content hash (present for all scanned files)
- `sha256` = full SHA256 (NULL for ~330k files; use quick_hash as fallback)
- DB is a pre-session snapshot — good for hash lookups but verify on-disk for critical decisions

---

## Current State (Feb 24 ~07:10)

- stoppedDL: **1845** (confirmed live)
- stalledUP: **3278** (seeding; 0 flipped to downloading — gradual-start complete)
- stoppedUP: **6** (newly repaired, not yet started — run gradual-start)
- Streak: **0** (b4345cd: 2 persistent failures: 5fc73670 Pink Floyd, 6b3471fd)
- All 6 bugs fixed; ~40 more batches of 50 needed to clear the backlog

---

## Quick Start

```bash
cd /home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028

# Check streak
cat ~/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt

# Dry-run
bash bin/qbit-repair-batch.sh --limit 50

# Apply
bash bin/qbit-repair-batch.sh --limit 50 --apply
```
