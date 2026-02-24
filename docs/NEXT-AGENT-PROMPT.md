# Next Agent Prompt — qbit-repair campaign

**Date:** 2026-02-24
**Worktree:** `/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028`
**Branch:** `chatrap/claude-hashall-20260223-124028`

---

## Current State

- **stoppedDL:** 1845 (confirmed live — need repair)
- **stalledUP:** 3278 (seeding; 0 have flipped to downloading)
- **stoppedUP:** 6 (newly repaired, not started yet — run gradual-start to pick up)
- **Streak:** 0 (b4345cd: 2 persistent failures; 5fc73670 Pink Floyd, 6b3471fd)
- **Total repaired this campaign:** ~258 confirmed (2103 - 1845)

---

## What Just Happened

1. **BUG-6 fixed** (pool-pool timing race): `bin/qbit-repair-batch.sh` now retries recheck on stoppedDL detection during P5 monitor + 120s grace for pool-pool torrents. Confirmed working: West Wing S02 and Brave New World (pool-pool) both resolved ✓ in b4345cd.

2. **b4345cd batch** (50 torrents, BUG-6 fix active): **COMPLETED.** ~48/50 success. 2 persistent failures:
   - `5fc73670` — Pink Floyd Division Bell (stash-stash; `already_hardlinked: 22, garbage: 1`)
   - `6b3471fd` — (stash-stash; `already_hardlinked: 13`)

3. **qbit-start-seeding-gradual.sh**: **COMPLETED.** All stoppedUP torrents started in 11 escalating batches (1→2→5→10→25→50→100→250→500→1000+mop-up). 3278 total started, **0 flipped to downloading** — all seeding cleanly.

---

## Your Primary Task

Continue repairing stoppedDL torrents. Run batches of 50:

```bash
cd /home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260223-124028

# Check current streak
cat ~/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt

# Dry-run first to see candidates
bash bin/qbit-repair-batch.sh --limit 50

# Apply
bash bin/qbit-repair-batch.sh --limit 50 --apply
```

All 6 known bugs are fixed. Batches should run cleanly. Run as many as needed.

---

## Expected Behavior

- Each batch of 50 takes ~20-30 minutes (P5 monitor waits for all to resolve)
- Pool-pool pairs resolve fine now (BUG-6 fix handles the timing race)
- Streak counter auto-updates in `~/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt`
- ~1845 stoppedDL / ~46 repairs per batch ≈ ~40 more batches to go
- Milestone: streak=10 (was achieved Feb 23 with batch-20 → streak=30, then reset by bugs)

---

## Bugs Fixed (All 6 Active)

| Bug | Summary | Fix |
|-----|---------|-----|
| BUG-1 | Deletion of live seed files | Inode-based safety check in P3 |
| BUG-2 | QB moved partials during restart | Delete before QB restart in P3 |
| BUG-3 | Transient stoppedDL recorded as failure | 10s grace in P5 before failure |
| BUG-4 | Wall-clock timeout too short | Per-torrent stagnation detection (not wall-clock) |
| BUG-5 | Stagnation fires on 0%-queued torrents | `has_started` gate — only stagnate if was >0% |
| BUG-6 | Pool-pool timing race on recheckTorrents | Retry recheck on stoppedDL + 120s grace |

---

## Known Remaining Issues

- **Same-save-path pairs**: Still skipped (P0). These need fastresume-only patch, no hardlink work. Count unknown.
- **Trashy.Lady** (`43f589275bd8`): stoppedDL at 99.8%, missing 0.2%. No easy fix.
- **Legion S03**: Multiple hashes with various issues (corruption, cross-fs). Skip for now.
- **5fc73670** (Pink Floyd Division Bell): Persistent failure. May need manual investigation.
- **6b3471fd**: Persistent failure. May need manual investigation.

---

## Key Files

| File | Purpose |
|------|---------|
| `bin/qbit-repair-batch.sh` | Main repair script |
| `bin/qbit-start-seeding-gradual.sh` | Starts stoppedUP torrents in safe escalating batches |
| `docs/qbit-repair-ops-log.md` | Full ops log with bug history and batch results |
| `~/.logs/hashall/reports/qbit-triage/repair-consecutive-successes.txt` | Streak counter |

---

## QB Environment

- API: `http://localhost:9003`
- Container: `qbittorrent_vpn`
- BT_backup: `/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/`
- Pool: `/pool/data/` (device 231)
- Stash: `/stash/media/` = `/data/media/` (device 44, bind mount)
