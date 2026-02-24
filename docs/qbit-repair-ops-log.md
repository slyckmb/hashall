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
| Streak file | `out/reports/qbit-triage/repair-consecutive-successes.txt` |
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

**Total repaired (confirmed stoppedUP):** ~308+ torrents
**Streak:** 50 (first clean batch with v1.2.0 fix)

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

---

## Known Skipped Cases

- **Same-save-path pairs**: Discovery skips them (P0). Need fastresume-only fix, no hardlink work. Analyzed: 1826 total (419 have stoppedUP partner at same path; 1426 have no seeding partner — likely unrecoverable without source data).
- **Trashy.Lady** (`43f589275bd8`): stoppedDL 99.8%, missing 0.2% of BD50. No easy fix.
- **Legion S03** (`0782850032bf`, `20f1e09447b6`, `f38a29c856e9`, `4c11952b3840`): Various issues. `109ffabfc401` was manually repaired Feb 23.

---

## Current State (Feb 24 ~09:30)

stoppedDL count: **1741** (started at ~2103; ~362 repaired total this campaign)
seeding (stalledUP): **3385** (daemon continuously starts new stoppedUP rounds)
stoppedUP (not yet started): **3** (daemon active, will start when ≥10 accumulate)
Streak: **50** (v1.2.0 first batch — perfect 50/50)

Scripts:
- `qbit-repair-batch.sh` **v1.2.0** — P0 now includes `stalledUP`/`uploading` as good sources
- `qbit-start-seeding-gradual.sh` **v1.1.1** — daemon mode + halt state + stop-on-download bug fix (was passing truncated 12-char hashes to API)
- `rehome-99_qb-checking-watch.sh` **v1.0.2** — dashboard mode; checkingDL removed from `down=` bucket
- `iowatch` **v1.4.3** — drive map corrected after stash pool refactor; pool drives always shown

**v1.2.0 key fix:** P0 now includes `stalledUP`/`uploading` as good sources (was only `stoppedUP`).
**Impact:** Unlocked 731 processable stoppedDL pairs (was 0 after previous batches exhausted stoppedUP pool).

**Daemon running:** `qbit-start-seeding-gradual.sh --daemon --apply --min-batch 10 --poll 60 &`
Polls every 60s, triggers ramp-start when stoppedUP ≥ 10. Logs: `out/reports/qbit-triage/daemon.log`
Reset file (to resume after halt): `out/reports/qbit-triage/daemon-halt-reset`

**~681 more processable candidates remain** (731 total - 50 done). Run:
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
- **Streak:** `cat out/reports/qbit-triage/repair-consecutive-successes.txt`

---

## Handoff Notes for Next Agent

Read this file first. Then:
```bash
# Check streak
cat out/reports/qbit-triage/repair-consecutive-successes.txt

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
