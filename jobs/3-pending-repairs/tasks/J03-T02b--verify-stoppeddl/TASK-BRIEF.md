---
id: J03-T02b
job: 3-pending-repairs
slug: verify-stoppeddl
task_type: verification
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T02b — Verify stoppedDL 0% Items from J03-T02

## Context

J03-T02 triggered rechecks on 5 missingFiles torrents. They cleared missingFiles
but landed in stoppedDL 0% — not stoppedUP. Per target state (USER-NOTES.md):

  stoppedDL is acceptable ONLY when RT is also incomplete.
  If RT is seeding at 100%, qB at stoppedDL 0% means qB path is still wrong.

The 5 hashes from J03-T02:

  ef48a9203545aa798775fba7e9a3e7ca396032fe  Fly.Me.To.The.Moon.2024...
  6b6043cacaada917da6d05cc551765f4530ca55a  Hunter's Code Book 4
  815e28c8cce2ef07ace15529485442046f39fffa  Smart Brevity (2022)
  282ec595d866745c115d5a418c028a2bb939f603  The.Conjuring.2013...
  8e438130b072708877003225a5079040991de5d7  The.Muppet.Christmas.Carol.1992...

## Bootstrap Context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
head=c92d2b9530218f38db01cb91f5f649757188b4be
goal=Pending repairs: resolve drift, recheck missingFiles, clean staging paths
```

Verify before starting:
- `git branch --show-current` → `cr/hashall-20260530-000517-claude__j03`
- `git status --short` → clean

## Brief

```
🟦 task-brief=J03-T02b_verify-stoppeddl 🟦

id=J03-T02b
role=agent
task_type=verification
goal=For each of the 5 hashes from J03-T02, check RT state and progress.
     Determine whether stoppedDL 0% in qB is acceptable (RT also incomplete)
     or still broken (RT seeding, qB path wrong).

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none

allowed_commands=
- cat ~/.cache/silo-rt/torrents.json | python3 -c "
    import json,sys
    t=json.load(sys.stdin)
    hashes=['ef48a920','6b6043ca','815e28c8','282ec595','8e438130']
    for h in hashes:
        match=[x for x in t if x.get('hash','').startswith(h)]
        if match:
            m=match[0]
            print(h, m.get('state'), m.get('progress'), m.get('name','')[:50])
        else:
            print(h, 'NOT FOUND IN RT')
  "
- cat ~/.cache/silo-qb/torrents-info.json | python3 -c "
    import json,sys
    t=json.load(sys.stdin)
    hashes=['ef48a920','6b6043ca','815e28c8','282ec595','8e438130']
    for h in hashes:
        match=[x for x in t if x.get('hash','').startswith(h)]
        if match:
            m=match[0]
            print(h, m.get('state'), m.get('progress'), m.get('save_path','')[:60])
        else:
            print(h, 'NOT FOUND IN QB')
  "
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 "" Enter

forbidden_commands=
- Any --execute or --apply flag on any command
- hashall rehome (any subcommand)
- git add / git commit
- docker stop / docker restart

required_artifacts=
- RT state and progress for each of the 5 hashes
- qB state and save_path for each of the 5 hashes
- Per-hash verdict: acceptable|broken
- Extracted values:
    acceptable_count=   (RT also incomplete → stoppedDL OK)
    broken_count=       (RT seeding → qB path wrong)
    broken_hashes=      (list of hashes needing further repair)

success_criteria=
- RT and qB states reported for all 5 hashes
- Per-hash verdict provided
- broken_count reported (0 is ideal)

stop_if=
- RT cache file not found or stale (>24h)
- qB cache file not found or stale (>24h)

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T02b_verify-stoppeddl 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T02b_verify-stoppeddl 🟪

status="done|blocked"
task_id="J03-T02b"
task_type="verification"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="<one-line summary>"
artifacts="terminal output below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

acceptable_count=
broken_count=
broken_hashes=

<per-hash table: hash | RT state | RT progress | qB state | qB save_path | verdict>

🟪 task-log=J03-T02b_verify-stoppeddl 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T02b--verify-stoppeddl/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T02b--verify-stoppeddl/TASK-LOG.md

3. Notify Lead (two sends):
   tmux send-keys -t %14 "🟪 J03-T02b done | acceptable=<N> broken=<N> broken_hashes=<list or none>"
   tmux send-keys -t %14 "" Enter
