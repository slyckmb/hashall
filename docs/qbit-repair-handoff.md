# qbit-repair — Session Handoff

**Date:** 2026-02-23
**Branch:** `chatrap/claude-hashall-20260223-124028`
**Worktree:** `/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028`

---

## Goal

Repair ~2103 `stoppedDL` torrents in qBittorrent → get them to `stoppedUP 100%` so they can seed again. These are mostly cross-seed torrents whose `qBt-downloadPath` in the `.fastresume` pointed to stale/wrong locations.

---

## Root Cause

Two distinct problems on `stoppedDL` torrents:
1. **`qBt-downloadPath` set** — QB rechecks at the old incomplete download path instead of `save_path`. Fix: clear `qBt-downloadPath` in `.fastresume` (requires QB stop/start since API returns 400).
2. **Garbage/placeholder files** — incomplete cross-seed downloads left sparse files at `save_path`. Fix: rebuild hardlinks from the good (stoppedUP 100%) partner torrent.

---

## Path Mapping (CRITICAL)

- `/stash` is **NOT** mounted in the qBittorrent container
- All stash content appears in QB as `/data/media/...`
- On host: `/data/media` and `/stash/media` are the **same filesystem** (bind mount)
- Pool paths: `/pool/data/...` — same in container and host
- Incomplete downloads: container `/incomplete_torrents` = host `/dump/torrents/incomplete_vpn`
- BT_backup (fastresume files): `/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/`
- QB container name: `qbittorrent_vpn`
- QB API: `http://localhost:9003`

---

## Scripts

### `bin/qbit-find-repair-candidates.sh [--limit N]`
Discovers stoppedDL torrents that have a stoppedUP 100% partner with same `root_name` in catalog.
Output: `good_hash broken_hash same_fs progress root_name`

### `bin/qbit-repair-batch.sh [--limit N] [--apply]`
**Main repair script.** Phases:
- **P0**: Discovery + filter (skips same-save-path pairs)
- **P1**: Content analysis via catalog DB (classify: already_hardlinked / dup_copy / garbage / missing)
- **P2**: Hardlink rebuild (same-fs) or setLocation (cross-fs), QB still running
- **P3**: QB stop → delete incomplete files (inode-safe) → patch fastresumes → QB start
- **P4**: recheckTorrents for all hashes at once
- **P5**: Monitor all in parallel until terminal state
- **P6**: Update streak counter

Streak tracked in: `out/reports/qbit-triage/repair-consecutive-successes.txt`

### `bin/qbit-repair-payload-group.sh --good HASH --broken HASH [--apply]`
Original single-pair script. Kept for debugging individual cases.

---

## Known Issues / Bugs Fixed This Session

### 1. FIXED: Deletion bug — removed hardlinks to live seed files
**What happened:** P3 deleted "incomplete" files that were actually the broken torrent's live seed file (when `download_path == save_path` in the container). Since `/data/media == /stash/media` on host, string comparison failed to detect this.
**Fix:** Inode-based safety check — skip deletion if target file shares inode+device with the good source file or save_path file (`os.stat(a).st_ino == os.stat(b).st_ino`).
**Affected torrents (manually fixed):** Contagion (2834e40f) and A.River (289e4a23) hardlinks recreated and verified.

### 2. FIXED: QB moved partial files during restart
**What happened:** If QB had partially-downloaded files at `download_path`, clearing `qBt-downloadPath` and restarting QB caused it to *move* those partial files to `save_path`, overwriting good hardlinks.
**Fix:** Delete files at `download_path/root_name` *before* QB restart (P3), with inode safety check.

### 3. KNOWN: Legion S03 corruption
**Hash:** good=`0782850032bf`, broken=`109ffabfc401` and `20f1e09447b6`
**What happened:** First repair attempt cleared download_path on FileList.io Legion torrent; QB moved partial E08 from `/incomplete_torrents` to save_path, corrupting E08. Good torrent `0782850032bf` was rechecked → now stoppedDL, will no longer appear as good source.
**Status:** Isolated. Legion S03 currently has no restorable good source on pool (E08 is partially corrupted at inode=34111; good copy exists on stash at inode=143611 but cross-fs copy would be needed). Skip for now.

### 4. KNOWN: Monitor timing — transient stoppedDL catch
**What happened:** Monitor occasionally catches a torrent at `stoppedDL` during a brief transition (checkingDL→stoppedDL→stoppedUP), recording it as failed. Batch 3 showed Contagion+A.River as failures but QB shows them as `stoppedUP 1.000`.
**Fix needed:** After detecting `stoppedDL`, wait 10s and re-poll before recording as final failure. (Not yet implemented.)

---

## Batch Results

| Batch | Size | ✓ | ✗ | Notes |
|-------|------|---|---|-------|
| 1 | 5 | 4 | 1 | Legion S03 — corrupted good source |
| 2 | 10 | 8 | 2 | Contagion+A.River — deletion bug (now fixed) |
| 3 | 10 | ~10 | ~0 | Both "failures" stoppedUP in QB; monitor timing bug |

**~22 torrents repaired.** Streak counter = 0 (due to above bugs, now fixed).
**Next session:** Should see clean runs. Run with `--limit 20` once confident.

---

## TODO — Next Session

1. **Fix monitor timing bug** — re-poll stoppedDL after 10s before recording as failure
2. **Run clean batches** to reach 10 consecutive successes → unlock batch mode
3. **Handle same-save-path pairs** separately (just need fastresume clear, no hardlink work; currently skipped by discovery)
4. **Test cross-fs case** (stash broken → pool good): setLocation approach, not yet validated end-to-end
5. **Scale to batch mode** — run all ~2103 stoppedDL candidates in large batches once 10-streak achieved
6. **Legion S03** — needs fresh download or cross-fs copy of E08 from stash; defer

---

## Catalog DB

Path: `~/.hashall/catalog.db`
Tables: `torrent_instances(torrent_hash, root_name)`, `files_231(path, inode, quick_hash, status)`, `files_44(...)` (231=pool, 44=stash)
Paths stored relative: pool=`seeds/...`, stash=`torrents/...`
**DB may be stale** — use for quick_hash/inode lookups but verify on-disk when critical.
Always query DB instead of running `find` on filesystem.

---

## Quick Start Next Session

```bash
cd /home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028

# Dry-run to see candidates
bash bin/qbit-repair-batch.sh --limit 10

# Apply
bash bin/qbit-repair-batch.sh --limit 10 --apply

# Check streak
cat out/reports/qbit-triage/repair-consecutive-successes.txt
```
