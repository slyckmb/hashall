# qbit-repair — Running Ops Log

**Script:** `bin/qbit-repair-batch.sh [--limit N] [--apply]`
**Goal:** Repair ~2103 `stoppedDL` torrents → `stoppedUP` (seeding)
**Root cause:** `qBt-downloadPath` set in `.fastresume` causes QB to recheck at wrong path.
**Fix:** Clear that field (requires QB container stop/start) + rebuild hardlinks at correct path.

---

## Quick Reference

| Item | Value |
|------|-------|
| QB API | `http://localhost:9003` |
| QB container | `qbittorrent_vpn` |
| BT_backup (fastresumes) | `/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/` |
| Streak file | `~/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt` |
| Pool path | `/pool/data/...` (dev=231) |
| Stash path | `/stash/media/...` = `/data/media/...` (dev=44) |

---

## Batch History

| Date | Batch ID | Size | ✓ | ✗ | Streak After | Notes |
|------|----------|------|---|---|--------------|-------|
| ~Feb 22 | early batches | 5+10+10 | ~22 | ~4 | 0 | deletion bug, monitor timing bug |
| Feb 23 | batch-10 | 10 | 9 | 1 | 0 | Azrael (cross-seed name variant, files missing) |
| Feb 23 | batch-10 | 10 | 10 | 0 | 10 | clean |
| Feb 23 | batch-20 | 20 | 20 | 0 | 30 | clean |
| Feb 23 | batch-50 (be122cd) | 50 | 21 | 29 | 0 | all 29 were checkingUP; wall-clock timeout too short |
| Feb 24 | batch-50 (b7246e0) | 50 | 20 | 30 | 0 | stale10m on queued-at-0% torrents |
| Feb 24 | batch-50 (bc6b411) | 50 | 46 | 4 | 0 | 4 pool-pool failures (see below) |
| Feb 24 | batch-50 (b4345cd) | 50 | ~48 | 2 | 0 | BUG-6 confirmed fixed (pool-pool pairs ✓); 2 failures: 5fc73670 (Pink Floyd), 6b3471fd |
| Feb 24 | batch-50 (v1.2.0) | 50 | 50 | 0 | 50 | v1.2.0 fix: expanded good pool to stalledUP+uploading; PERFECT BATCH — streak reset to 50 |
| Feb 24 | batch-50 (v1.2.0, 2nd) | ~51 | ~51 | 0 | 51(+1) | daemon drained 1 more; stoppedDL 1741→1690 |
| Feb 24 | batch-50 (v1.2.1) | ABORTED | — | — | 0 | concurrent run collision; both scripts crashed mid-P3; QB manually restarted; 12 fastresumes patched pre-crash, rechecked manually; PermissionError on root-owned dir (HD-Space) → BUG-7 fixed in v1.2.1 |

**Total repaired (confirmed stoppedUP):** ~360+ torrents
**Streak:** 0 (aborted batch; need clean run to re-establish)

---

## Bugs Fixed

### BUG-1: Deletion of live seed files (FIXED)
P3 deleted files that were the torrent's actual seeding content when `download_path == save_path`.
Fix: inode-based safety check before any deletion.

### BUG-2: QB moved partial files during restart (FIXED)
Clearing `qBt-downloadPath` without deleting partials caused QB to move garbage → save_path on restart.
Fix: delete files at download_path (with inode safety) before QB restart.

### BUG-3: 10s grace period on stoppedDL (FIXED)
Monitor recorded transient stoppedDL as failures.
Fix: re-poll after 10s before recording failure.

### BUG-4: Wall-clock timeout too short for large batches (FIXED)
15-min timer fired before QB's serial recheck queue drained.
Fix: per-torrent stagnation timeout — only fires if torrent was >0% then stalled 10+ min.

### BUG-5: Stagnation timeout on queued torrents (FIXED)
Stagnation fired on torrents at 0% waiting in QB's queue (never started).
Fix: only stagnation-timeout torrents that have been >0% at some point (`has_started` set).

### BUG-6: Pool-pool timing race (FIXED — Feb 24)
Pool-pool torrents were failing with immediate `stoppedDL` after recheckTorrents.
**Root cause:** recheckTorrents called while QB still in checkingResumeData state; recheck didn't take effect.
**Fix:** Retry recheck on stoppedDL detection during P5 monitor + 120s grace period for pool-pool pairs.
**Confirmed working:** b4345cd batch shows 62c3d90c (West Wing S02, pool-pool) and 63ce041b (Brave New World, pool-pool) both resolved to ✓.

### BUG-7: PermissionError on root-owned directories (FIXED — Feb 24)
P3 `os.remove()` raised `PermissionError` on files in dirs owned by root (e.g. `HD-Space` cross-seed dir set by docker container).
**Root cause:** Some docker containers `chown`/`chmod` media dirs to root, leaving them inaccessible to the `michael` user.
**Fix (script):** Wrap `os.remove()` in `try/except PermissionError` — log warning, skip deletion, continue with fastresume patch. (`qbit-repair-batch.sh` v1.2.1)
**Fix (system):** `bin/fix-permissions.sh` — recursively resets `/data/media`, `/pool/data`, `/mnt/hotspare6tb` to `michael:michael`, dirs `2755`, files `644`. Run periodically after docker ops.

---

## Known Skipped Cases

- **Same-save-path pairs**: Discovery skips them (P0). Need fastresume-only fix, no hardlink work. Analyzed: 1826 total (419 have stoppedUP partner at same path; 1426 have no seeding partner — likely unrecoverable without source data).
- **Trashy.Lady** (`43f589275bd8`): stoppedDL 99.8%, missing 0.2% of BD50. No easy fix.
- **Legion S03** (`0782850032bf`, `20f1e09447b6`, `f38a29c856e9`, `4c11952b3840`): Various issues. `109ffabfc401` was manually repaired Feb 23.

---

## Current State (Feb 24 ~10:20)

stoppedDL count: **1679** (started at ~2103; ~360+ repaired this campaign)
seeding (stalledUP): **3421** (daemon continuously starts new stoppedUP rounds)
stoppedUP (not yet started): **12** (daemon will drain these)
checking: **~17** (resolving from aborted batch + manual recheck)
Streak: **0** (aborted batch; needs clean run to re-establish)

Scripts:
- `qbit-repair-batch.sh` **v1.2.1** — BUG-7: PermissionError on root-owned dirs handled gracefully
- `qbit-start-seeding-gradual.sh` **v1.1.1** — daemon mode (running)
- `rehome-99_qb-checking-watch.sh` **v1.0.3** — curl robustness; version in header
- `iowatch` **v1.4.3** — drive map corrected
- `fix-permissions.sh` **v1.0.0** — NEW: resets media root perms after docker ownership damage

**Daemon running:** PID 3559295 — `qbit-start-seeding-gradual.sh --daemon --apply --min-batch 10 --poll 60`
Logs: `~/.logs/hashall/reports/qbit-triage/daemon.log`

**fix-permissions.sh** running in background (PID 4127316), fixing `/data/media`, `/pool/data`, `/mnt/hotspare6tb`.

**~630 processable candidates remain** (~731 - ~101 done). Next:
```bash
bash bin/qbit-repair-batch.sh --limit 50 --apply
```

---

## TODO

- [x] Fix pool-pool batch timing bug (BUG-6 fixed)
- [ ] Run clean batch → establish streak > 0
- [ ] Scale: ~1845 / 46 per batch ≈ 40 more batches needed
- [ ] Reach streak=10 (milestone)
- [ ] Handle same-save-path pairs
- [ ] Handle Trashy.Lady and Legion S03 variants

---

## Monitoring

- **Fleet status:** `bin/rehome-99_qb-checking-watch.sh` — shows checking/missing/stoppedDL counts
- **During batch:** P5 monitor built into `qbit-repair-batch.sh` polls every 5s per-torrent
- **Streak:** `cat ~/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt`

---

## Handoff Notes for Next Agent

Read this file first. Then:
```bash
# Check streak
cat ~/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt

# Dry-run to see next candidates
bash bin/qbit-repair-batch.sh --limit 20

# Apply
bash bin/qbit-repair-batch.sh --limit 20 --apply
```

Pool-pool pairs (save_path starts with `/pool/data/seeds/`) are now handled by BUG-6 fix (retry-recheck + 120s grace). No manual intervention needed.

If any torrents still end up as stoppedDL after a batch, manually recheck:
```bash
curl -s -c /tmp/qb_cookie.txt -d 'username=admin&password=adminadmin' http://localhost:9003/api/v2/auth/login
curl -s --cookie /tmp/qb_cookie.txt -X POST http://localhost:9003/api/v2/torrents/recheck \
  --data-urlencode "hashes=HASH1|HASH2"
```
