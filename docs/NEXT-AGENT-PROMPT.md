# Next Agent Prompt — qbit-repair campaign

**Date:** 2026-02-25
**Worktree:** `/home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260224-132659`
**Branch:** `chatrap/claude-hashall-20260224-132659`

---

## Current State

- **stoppedDL:** ~1027 (T1=6 pending repair, T2=29 pending repair, T3=4 direct recheck, T4=988 nohl-basics pipeline)
- **Scripts:** `qbit-repair-batch.sh` v1.6.1, `pd-score.sh` v1.0.0, `pd-triage.sh` v1.0.0
- **Recent commits:** 24cd941 (v1.6.1), 327bfc0 (pd-score), 6698bb5 (v1.6.0), 82a37df (db-refresh)

---

## Tier Breakdown (from pd-score.sh output)

| Tier | Count | Description | Tool |
|------|-------|-------------|------|
| T1 | 6 | EXACT name match, ≥99% progress | qbit-repair-batch (--limit 10) |
| T2 | 29 | Has QB partner (EXACT or FUZZY) | qbit-repair-batch (--limit 30) |
| T3 | 4 | No QB partner but disk=100% (Legion S03 ×2, Bullet Train, Trapped) | Direct QB recheck |
| T4 | 988 | No QB partner, 0% progress, cross-seed slots | rehome-100/101/102 |

10 torrents timed out in the last --same-save run (NOT blacklisted). v1.6.1 will properly
fail them (stpDL grace) and blacklist them on next run.

---

## Primary Tasks (in order)

### T1/T2 — qbit-repair-batch

```bash
cd /home/michael/dev/work/hashall/.agent/worktrees/claude-hashall-20260224-132659

# T1: EXACT ≥99% (6 torrents)
bin/qbit-repair-batch.sh --limit 10           # dryrun
bin/qbit-repair-batch.sh --limit 10 --apply

# --same-save pass (clears 10 timed-out + same-save partners)
bin/qbit-repair-batch.sh --same-save --apply

# T2: remaining with QB partner
bin/qbit-repair-batch.sh --limit 30 --apply
```

### T3 — Direct recheck (4 hashes with disk=100%)

```bash
# Get T3 hashes from pd-score output
python3 -c "
import json
data = json.load(open('/home/michael/.logs/hashall/reports/qbit-triage/pd-score-20260225-120826.json'))
t3 = [x['hash'] for x in data['torrents'] if x['tier'] == 3]
print('|'.join(t3))
"
# Then recheck via QB API:
source /home/michael/dev/secrets/qbittorrent/api.env
COOKIE=$(mktemp /tmp/qb.XXXXX)
curl -fsS -c "$COOKIE" -X POST http://localhost:9003/api/v2/auth/login \
  --data-urlencode "username=$QBITTORRENTAPI_USERNAME" \
  --data-urlencode "password=$QBITTORRENTAPI_PASSWORD" >/dev/null
curl -fsS -b "$COOKIE" -X POST http://localhost:9003/api/v2/torrents/recheck \
  --data-urlencode "hashes=HASH1|HASH2|HASH3|HASH4"
```

### T4 — DB Refresh + nohl-basics pipeline

**CRITICAL ORDER — UUID migration MUST precede any rescan:**

```bash
# Step 1: UUID migration (ONE-TIME, before first rescan)
bin/db-uuid-migration.sh           # dryrun — confirms 6 dev-XX → zfs-XXXX mappings
bin/db-uuid-migration.sh --apply   # apply

# Steps 2-5: DB Refresh
bin/db-refresh-step1-scan-stash.sh
bin/db-refresh-step2-scan-pool-hotspare.sh
bin/db-refresh-step3-sha256-backfill.sh
bin/db-refresh-step4-payload-sync.sh

# Safety gate
bin/rehome-89_nohl-basics-qb-automation-audit.sh
bin/rehome-89_nohl-basics-qb-automation-audit.sh --mode apply  # if risks found

# Baseline snapshot
bin/rehome-100_nohl-basics-qb-repair-baseline.sh

# Candidate mapping (exit 2 = unresolved OK; confident list still written)
bin/rehome-101_nohl-basics-qb-candidate-mapping.sh
# If many unresolved (>100):
# MAP_ENABLE_DISCOVERY_SCAN=1 bin/rehome-101_nohl-basics-qb-candidate-mapping.sh

# Dryrun pilot
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode dryrun --limit 10

# Pilot apply
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 10

# Full batch (repeat until done)
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 100
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 250
```

**102 auto-skips items with final_state=stoppedup in prior result files.**

On failures in 102: items where recheck lands in stoppedDL (data not at target path) are
logged as errors and skipped. Review errors in result JSON. These likely went to unresolved.

**Unresolved items (COAs):**
- COA A (Recommended): Accept as truly lost — queue for QB deletion
- COA B: Re-run rehome-101 with `MAP_ENABLE_DISCOVERY_SCAN=1`
- COA C: Manual sample investigation

Note: Phases 95-97 are for `missingFiles` state torrents (separate pipeline). Do NOT run
them for stoppedDL unresolved items.

---

## All Bugs Fixed

| Bug | Summary | Fixed in |
|-----|---------|----------|
| BUG-1 | Deletion of live seed files | early |
| BUG-2 | QB moved partials during restart | early |
| BUG-3 | Transient stoppedDL recorded as failure | early |
| BUG-4 | Wall-clock timeout too short | early |
| BUG-5 | Stagnation fires on queued-at-0% torrents | early |
| BUG-6 | Pool-pool timing race on recheckTorrents | Feb 24 |
| BUG-7 | PermissionError on root-owned dirs | Feb 24 |
| Fix-A | pausedDL now included in broken states | v1.6.0 |
| Fix-B | catalog fallback to QB API name | v1.6.0 |
| Fix-C | fuzzy name matching | v1.6.0 |
| Fix-D | already_hardlinked noops → recheck instead of skip | v1.6.0 |
| BUG-8 | retry_recheck loop → timeout on genuine stpDL | v1.6.1 |

---

## QB Environment

- API: `http://localhost:9003`
- Container: `qbittorrent_vpn`
- BT_backup: `/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/`
- Pool: `/pool/data/` (device 231)
- Stash: `/stash/media/` = `/data/media/` (device 44, bind mount)

---

## Key Files

| File | Purpose |
|------|---------|
| `bin/qbit-repair-batch.sh` | Main repair script (v1.6.1) |
| `bin/pd-score.sh` | Tier scoring for bulk stoppedDL triage |
| `bin/pd-triage.sh` | Per-torrent diagnosis helper |
| `bin/db-uuid-migration.sh` | ONE-TIME: migrate dev-XX UUIDs → zfs-XXXX (run before db-refresh) |
| `bin/db-refresh-step1-4` | Catalog DB refresh pipeline |
| `bin/rehome-89,100,101,102` | nohl-basics repair pipeline |
| `docs/qbit-repair-ops-log.md` | Full ops log with bug history and batch results |
| `docs/qbit-repair-handoff.md` | Session handoff notes |
