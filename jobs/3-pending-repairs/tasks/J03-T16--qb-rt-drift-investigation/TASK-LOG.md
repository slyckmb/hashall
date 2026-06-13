# J03-T16 — qB/RT Drift Investigation — Task Log

## Metadata

- **Task**: J03-T16 — qb-rt-drift-investigation
- **Type**: discovery
- **Agent**: claude
- **Executed**: 2026-06-13
- **Brief Revision**: 1

## Inventory Snapshot (live)

| Metric | Original Brief | Live |
|---|---|---|
| RT total | 4883 | 4881 |
| qB total | 4882 | 4882 |
| Queue size | 4918 | 4918 |

## Q1: Is the queue backlogged with unprocessed items?

**Result: No.**

| Metric | Value |
|---|---|
| Queue entries | 4918 |
| In queue + RT but NOT qB (pending sync) | **0** |
| In queue but removed from RT (historical) | **43** |

All queue entries that still have active RT counterparts are already mirrored to qB. No actionable backlog.

## Q2: Is the mirror queue stale?

**Result: Yes — heavily stale.**

- Most recent entry timestamp: 2.4 hours ago
- Oldest entries: ~940–976 hours ago (~39–41 days)
- The queue contains **4918 entries** for only **4881 active RT items** — most are already-processed entries never cleaned up.
- 43 entries correspond to items that were removed from RT entirely (historical junk).

## Q3: What does `make rt-qb-mirror-queue-apply` do and when was it last run?

The target (`Makefile` line shown above) runs:
```
python3 -m hashall.cli rt-qb-mirror process-queue \
  --queue-dir /dump/docker/gluetun_qbit/rtorrent_vpn/rt-qb-mirror-queue \
  --apply --min-age 120 --limit 20 --sleep-row 5
```
- Processes the oldest queue items first in batches of 20
- Default 120s min-age before processing
- Monitor mode with 900s timeout
- Supports `FORCE=1` to bypass journal checks

**Last run**: No mirror-queue-specific logs found in the VPN logs directory. No cron automation exists. The last relevant git commit was `130ef47` (wiring the make target). Uncertain when it was last executed.

## Q4: Is the 1 drift item (Euphoria pack) expected to self-resolve?

**Yes.**

| Field | Value |
|---|---|
| Hash | `406ff76c` |
| Name | Euphoria.US.S03.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune |
| State | 1 (downloading) |
| Complete | 0 |
| Progress | **38.9%** |

When the download finishes, RT fires the completion hook which enqueues the hash. Running `rt-qb-mirror-queue-apply` then mirrors it to qB. Self-resolving — no intervention needed.

## Q5: Are there any OTHER RT seeding items missing from qB?

**Result: No — but 2 qB orphans exist.**

| Metric | Value |
|---|---|
| RT seeding not in qB | **0** |
| RT items NOT in qB (all states) | **1** (Euphoria pack, downloading) |
| qB items NOT in RT | **2** (orphans) |

The 2 qB orphans:
1. `9e403665` — How.Its.Made.S32.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
2. `07828500` — Legion.S03.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb

These were likely removed from RT (explaining the RT count drop from 4883→4881) but were not cleaned up in qB.

## Findings Summary

### Required Artifacts

| Artifact | Value |
|---|---|
| queue_size | 4918 |
| queue_backlog_pending_items | 0 |
| queue_historical_items | 43 |
| rt_seeding_not_in_qb | 0 |
| drift_item_status | Euphoria pack downloading at 38.9%, will self-resolve |
| sync_mechanism_health | **degraded** |
| recommended_action | **investigate-further** |

### Sync Mechanism Health Assessment

**Verdict: DEGRADED**

Reasoning:
1. **Core sync works** — items in queue+RT are properly mirrored to qB (0 pending items).
2. **Queue is bloated** — 4918 entries for 4881 RT items; 43 historical orphans; oldest entries 40+ days stale. No cleanup/trimming mechanism.
3. **RT count dropped** — from 4883 (brief) to 4881 (live). Two items now only in qB suggest RT cleanup without qB counterpart cleanup.
4. **No automation** — no cron or scheduled runner processes the queue; last manual run uncertain.
5. **No recent evidence of queue-apply execution** — no logs, no journal files referencing recent runs.

The drift at brief time was 1 item (Euphoria, expected). The live drift has reversed polarity with 2 qB-only orphans — but the original question's 1 RT-to-qB drift is still just the downloading Euphoria pack.

### Recommended Next Action

**investigate-further**

1. Determine why `How.Its.Made.S32` and `Legion.S03` were removed from RT — were they intentionally deleted or is this a RT data loss incident?
2. If intentional, run the reverse drift tool (`client-drift-qb-to-rt-dry` then `-apply`) to remove them from qB, or just manually delete from qB.
3. Consider adding queue cleanup/stale-entry trimming to a maintenance routine.
4. Once Euphoria finishes downloading and the 2 qB orphans are resolved, run `make rt-qb-mirror-queue-apply` to bring the system current.
