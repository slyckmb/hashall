# qbit-repair — Session Handoff

**Date:** 2026-02-24
**Branch:** `chatrap/claude-hashall-20260223-124028`
**Worktree:** `/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028`

---

## Goal

Repair ~2103 `stoppedDL` torrents in qBittorrent → get them to `stoppedUP 100%` so they can seed again.

---

## Current State (Feb 24 ~09:30)

| Item | Value |
|------|-------|
| stoppedDL remaining | **1741** |
| stalledUP (seeding) | **3385** |
| stoppedUP (pending daemon start) | ~3 |
| Streak | **50** (perfect v1.2.0 batch) |
| Processable candidates remaining | **~681** (731 total - 50 done) |

---

## Root Cause

Two distinct problems on `stoppedDL` torrents:
1. **`qBt-downloadPath` set** — QB rechecks at wrong path. Fix: clear field in `.fastresume` (requires QB stop/start).
2. **Garbage/placeholder files** — rebuild hardlinks from good (seeding) partner torrent.

---

## Path Mapping (CRITICAL)

- `/stash` is **NOT** mounted in the qBittorrent container
- All stash content appears in QB as `/data/media/...`
- On host: `/data/media` and `/stash/media` are the **same filesystem** (bind mount)
- Pool paths: `/pool/data/...` — same in container and host
- BT_backup (fastresume files): `/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/`
- QB container name: `qbittorrent_vpn`
- QB API: `http://localhost:9003`

---

## Scripts & Versions

| Script | Version | Notes |
|--------|---------|-------|
| `bin/qbit-repair-batch.sh` | **v1.2.0** | P0 includes stalledUP/uploading as good sources (was stoppedUP-only) |
| `bin/qbit-start-seeding-gradual.sh` | **v1.1.1** | Daemon mode; halt state; stop-on-download bug fix |
| `bin/rehome-99_qb-checking-watch.sh` | **v1.0.2** | Dashboard mode (`--dashboard`); checkingDL fixed |
| `iowatch` | **v1.4.3** | Drive map corrected after stash pool refactor |

---

## Daemon Running (keep alive)

```bash
# Auto-starts new stoppedUP torrents when bucket >= 10
nohup bash bin/qbit-start-seeding-gradual.sh --daemon --apply --min-batch 10 --poll 60 > /tmp/gradual-daemon.log 2>&1 &

# If daemon halted due to downloading detection, investigate then:
touch out/reports/qbit-triage/daemon-halt-reset
```

Daemon log: `out/reports/qbit-triage/daemon.log`

---

## Quick Start Next Session

```bash
cd /home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028

# Check state
cat out/reports/qbit-triage/repair-consecutive-successes.txt   # streak
curl -s http://localhost:9003/api/v2/torrents/info | python3 -c "
import json,sys; from collections import Counter
t=json.load(sys.stdin); s=Counter(x['state'] for x in t)
print(f'stoppedDL={s[\"stoppedDL\"]} stalledUP={s[\"stalledUP\"]} stoppedUP={s[\"stoppedUP\"]}')"

# Ensure daemon is running
ps aux | grep qbit-start-seeding | grep -v grep

# Dry-run next batch
bash bin/qbit-repair-batch.sh --limit 50

# Apply
bash bin/qbit-repair-batch.sh --limit 50 --apply
```

---

## Key Fix: v1.2.0 P0 Change

**Before:** `good_hashes = {... if t["state"] == "stoppedUP" ...}`
**After:** `good_hashes = {... if t["state"] in ("stoppedUP", "stalledUP", "uploading") ...}`

Without this, all 3277 stalledUP (seeding) torrents were excluded as repair sources → 0 candidates.

---

## All 6 Bugs Fixed

| Bug | Fix |
|-----|-----|
| BUG-1 | Deletion of live seed files — inode safety check |
| BUG-2 | QB moved partials during restart — delete before QB restart |
| BUG-3 | Transient stoppedDL — 10s grace before recording failure |
| BUG-4 | Wall-clock timeout too short — per-torrent stagnation detection |
| BUG-5 | Stagnation fires on queued-at-0% torrents — `has_started` gate |
| BUG-6 | Pool-pool timing race — retry recheck + 120s grace |

---

## Known Remaining Issues

- **Same-save-path pairs** (1826 total): Skipped by P0. 419 have stoppedUP at same path; 1426 have no seeding partner (likely unrecoverable). Need fastresume-only patch to fix the 419.
- **5fc73670** (Pink Floyd Division Bell): Persistent failure — stash-stash, `garbage:1`. Manual investigation needed.
- **6b3471fd**: Persistent failure — stash-stash. Manual investigation needed.
- **Trashy.Lady** (`43f589275bd8`): stoppedDL at 99.8%, missing 0.2%. No easy fix.
- **Legion S03**: Various issues. Skip.

---

## Catalog DB

Path: `~/.hashall/catalog.db`
Tables: `torrent_instances(torrent_hash, root_name)`, `files_231(path, quick_hash)`, `files_44(...)`
(231=pool device, 44=stash device)
DB may be stale — verify on-disk when critical.

---

## Monitoring

```bash
# Live dashboard
bash bin/rehome-99_qb-checking-watch.sh --dashboard

# Daemon log
tail -f out/reports/qbit-triage/daemon.log
```
