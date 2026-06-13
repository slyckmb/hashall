---
id: J03-T02
job: 3-pending-repairs
slug: recheck-missingfiles
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T02 — Recheck 5 missingFiles Items

## Context

J02-T03 found 5 qB torrents in missingFiles or error state. J02-T06 confirmed
these are NOT Slice 12b leftovers (script found 0 legacy items). J03-T01 reduced
drift to 4 (none of the 4 are in missingFiles state). These 5 are a separate
cohort likely caused by stale fastresume paths. Triggering a recheck should
resolve them if data is present at the correct path.

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
🟦 task-brief=J03-T02_recheck-missingfiles 🟦

id=J03-T02
role=agent
task_type=implementation
goal=Identify the 5 qB missingFiles/error torrents, trigger a recheck for each,
     and verify their state resolves to stoppedUP or stalledUP after recheck.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none
note=qB recheck API calls are expected live-system side effects, not tracked
     file mutations. No git commits in this task.

allowed_commands=
- cat ~/.cache/silo-qb/torrents-info.json | python3 -c "import json,sys; t=json.load(sys.stdin); bad=[x for x in t if x.get('state','') in ('missingFiles','error')]; [print(x['hash'],x['state'],x.get('name','')[:60]) for x in bad]"
- hashall qb recheck --hash <hash>
- hashall qb fetch-cache
- python3 -c "..." (read-only cache inspection)
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 "" Enter

forbidden_commands=
- hashall rehome (any subcommand)
- hashall payload save-path-repair --execute
- Any --execute or --apply flag on any command
- docker stop / docker restart
- git add / git commit

execution_order=
1. List all 5 missingFiles/error hashes with names from qB cache
2. Trigger recheck for each hash
3. Wait 60s for rechecks to complete
4. Refresh qB cache: hashall qb fetch-cache
5. Re-inspect: report new state for each hash

required_artifacts=
- List of 5 hashes with name and initial state
- Recheck trigger output for each
- Final state of each hash after recheck
- Extracted values:
    missingfiles_before=5
    missingfiles_after=
    resolved_count=
    still_broken_count=
    still_broken_hashes=

success_criteria=
- All 5 hashes identified and listed
- Recheck triggered for each
- Final states reported
- missingfiles_after reported (ideally 0)

stop_if=
- qB daemon unreachable
- recheck command errors on all hashes
- Cache refresh fails

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T02_recheck-missingfiles 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T02_recheck-missingfiles 🟪

status="done|blocked"
task_id="J03-T02"
task_type="implementation"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="live: qB rechecks triggered for N hashes"
validation="<one-line summary>"
artifacts="terminal output below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

missingfiles_before=5
missingfiles_after=
resolved_count=
still_broken_count=
still_broken_hashes=

<list of 5 hashes with initial states>
<recheck trigger output>
<final states after recheck>

🟪 task-log=J03-T02_recheck-missingfiles 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T02--recheck-missingfiles/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T02--recheck-missingfiles/TASK-LOG.md

3. Notify Lead (two sends):
   tmux send-keys -t %14 "🟪 J03-T02 done | resolved=<N> still_broken=<N>"
   tmux send-keys -t %14 "" Enter
