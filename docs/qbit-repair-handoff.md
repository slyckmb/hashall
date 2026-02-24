# qbit-repair — Session Handoff

**Date:** 2026-02-24
**Branch:** `chatrap/claude-hashall-20260223-124028`
**Worktree:** `/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028`

---

## Background Context (read first, every session)

### Hashall Repo Baseline Docs

Always read these to understand the system before doing anything:

| Doc | Purpose |
|-----|---------|
| `README.md` | Repo overview, goals, key concepts |
| `docs/REQUIREMENTS.md` | Detailed functional requirements |
| `docs/theory-of-operations.md` | How the system works (hardlinks, catalog DB, QB integration) |
| `docs/tooling/quick-reference.md` | Script inventory and usage cheat-sheet |

### Hydration: Pre-existing Chatrap Session (continuing from a previous session)

If you are a **new agent instance resuming a prior chatrap session** (i.e. you received a
handoff prompt or next-agent prompt rather than a clean bootstrap), hydrate with:

1. **Chatrap bootstrap template:**
   `/home/michael/dev/tools/chatrap/prompts/bootstrap-template.md`

2. **Session baseline** (objective facts about this session's starting state):
   `/home/michael/dev/work/hashall/.agent/baselines/<chat_id>-baseline.md`
   → substitute the actual chat ID shown at the top of this file or in the handoff prompt

> These two docs apply **only** when continuing an existing session. If this is a
> freshly bootstrapped new session, the bootstrap process has already handled hydration.

---

## Goal

Repair ~2103 `stoppedDL` torrents in qBittorrent → get them to `stoppedUP 100%` so they can seed again.

---

## Current State (Feb 24 ~10:20)

| Item | Value |
|------|-------|
| stoppedDL remaining | **1679** |
| stalledUP (seeding) | **3421** |
| stoppedUP (pending daemon start) | ~12 |
| checking (resolving) | ~17 |
| Streak | **0** (aborted batch; needs clean run) |
| Processable candidates remaining | **~630** (~731 total - ~101 done) |

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
| `bin/qbit-repair-batch.sh` | **v1.2.1** | BUG-7: PermissionError on root-owned dirs handled gracefully |
| `bin/qbit-start-seeding-gradual.sh` | **v1.1.1** | Daemon mode; halt state; stop-on-download bug fix |
| `bin/rehome-99_qb-checking-watch.sh` | **v1.0.3** | Curl error robustness; version in dashboard header |
| `bin/fix-permissions.sh` | **v1.0.0** | NEW: resets media root perms after docker ownership damage |
| `iowatch` | **v1.4.3** | Drive map corrected after stash pool refactor |

---

## Permissions Note (IMPORTANT)

Docker containers sometimes `chown` media dirs to root, causing `PermissionError` in repair scripts.
**Fix:** Run periodically (especially after docker ops):
```bash
bash bin/fix-permissions.sh
# Targets: /data/media  /pool/data  /mnt/hotspare6tb
# Sets: owner=michael:michael  dirs=2755  files=644
```

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
checking = sum(v for k,v in s.items() if 'checking' in k.lower())
print(f'stoppedDL={s[\"stoppedDL\"]} stalledUP={s[\"stalledUP\"]} stoppedUP={s[\"stoppedUP\"]} checking={checking}')"

# Ensure no concurrent batch is running
ps aux | grep qbit-repair-batch | grep -v grep

# Ensure daemon is running
ps aux | grep qbit-start-seeding | grep -v grep

# Wait for checking=0 before running batch
# Then dry-run
bash bin/qbit-repair-batch.sh --limit 50

# Apply (ONE at a time — never run concurrent batches)
bash bin/qbit-repair-batch.sh --limit 50 --apply
```

**CRITICAL: Never run two `qbit-repair-batch.sh --apply` concurrently.** Both will stop QB,
patch overlapping fastresumes, and crash each other — QB ends up stopped with partial patches.
If this happens: `docker start qbittorrent_vpn`, then wait for QB to come up and recheck affected hashes.

---

## All 7 Bugs Fixed

| Bug | Fix |
|-----|-----|
| BUG-1 | Deletion of live seed files — inode safety check |
| BUG-2 | QB moved partials during restart — delete before QB restart |
| BUG-3 | Transient stoppedDL — 10s grace before recording failure |
| BUG-4 | Wall-clock timeout too short — per-torrent stagnation detection |
| BUG-5 | Stagnation fires on queued-at-0% torrents — `has_started` gate |
| BUG-6 | Pool-pool timing race — retry recheck + 120s grace |
| BUG-7 | PermissionError on root-owned dirs — try/except, warn+skip |

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
