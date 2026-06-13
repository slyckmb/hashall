---
id: J03-T02b
job: 3-pending-repairs
slug: verify-stoppeddl
task_type: verification
status: done
brief_revision_id: 1
executed_by: agent
executed_at: 2026-06-12
---

# J03-T02b — Verify stoppedDL 0% Items from J03-T02

## Agent Report

```
🟪 task-log=J03-T02b_verify-stoppeddl 🟪

status="done"
task_id="J03-T02b"
task_type="verification"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="All 5 hashes stoppedDL 0% in both RT and qB → acceptable"
artifacts="terminal output below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none"
next="future TBD by lead after current task log"

acceptable_count=5
broken_count=0
broken_hashes=none

| hash | RT state | RT progress | qB state | qB save_path | verdict |
|------|----------|-------------|----------|--------------|---------|
| ef48a920 | stoppedDL | 0% | stoppedDL | /data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79 | acceptable |
| 6b6043ca | stoppedDL | 0% | stoppedDL | /data/media/torrents/seeding/abtorrents | acceptable |
| 815e28c8 | stoppedDL | 0% | stoppedDL | /data/media/torrents/seeding/MaM | acceptable |
| 282ec595 | stoppedDL | 0% | stoppedDL | /data/media/torrents/seeding/movies/The.Conjuring.2013.1080p | acceptable |
| 8e438130 | stoppedDL | 0% | stoppedDL | /pool/media/torrents/seeding/_rehome-unique/8e438130b0727088 | acceptable |

🟪 task-log=J03-T02b_verify-stoppeddl 🟪
```

## Raw Command Output

### RT state (from `~/.cache/silo-rt/torrents.json`)
```
ef48a920 stoppedDL 0.0 Fly.Me.To.The.Moon.2024.REPACK.1080p.AMZN.WEB-DL.D
6b6043ca stoppedDL 0.0 Hunter's Code Book 4
815e28c8 stoppedDL 0.0 Jim VandeHei and Mike Allen Roy Schwartz - Smart B
282ec595 stoppedDL 0.0 The.Conjuring.2013.1080p.Blu-Ray.ReMuX.AVC.DTS-HDM
8e438130 stoppedDL 0.0 The.Muppet.Christmas.Carol.1992.BluRay.1080p.DTS-H
```

### qB state (from `~/.cache/silo-qb/torrents-info.json`)
```
ef48a920 stoppedDL 0.0 /data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79
6b6043ca stoppedDL 0.0 /data/media/torrents/seeding/abtorrents
815e28c8 stoppedDL 0.0 /data/media/torrents/seeding/MaM
282ec595 stoppedDL 0.0 /data/media/torrents/seeding/movies/The.Conjuring.2013.1080p
8e438130 stoppedDL 0.0 /pool/media/torrents/seeding/_rehome-unique/8e438130b0727088
```

## Cache Freshness
- `silo-rt/torrents.json`: 2026-06-12 13:48 (fresh)
- `silo-qb/torrents-info.json`: 2026-06-12 13:41 (fresh)

## Analysis

All 5 hashes are in `stoppedDL` with 0% progress in **both** RT and qB. Per the target state rule: "stoppedDL is acceptable ONLY when RT is also incomplete." Since RT shows 0% progress (incomplete), the stoppedDL state in qB is acceptable for all 5 hashes.

**Result: 0 broken — no further repair needed for these hashes.**
