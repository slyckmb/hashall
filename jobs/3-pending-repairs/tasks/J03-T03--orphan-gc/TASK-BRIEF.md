---
id: J03-T03
job: 3-pending-repairs
slug: orphan-gc
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T03 — Orphan GC (Clear Aged Candidates)

## Context

J02-T01 and J02-T03 both reported orphan GC blocked:
- aged candidates: 2481 (were in catalog but no longer tracked by any client)
- new candidates: 2062
- pruned: 0 — blocked because 2481 > 1000 (the default limit)

The aged cohort (2481) is safe to prune — these are catalog rows for payloads
that have been tracked by neither qB nor RT for long enough to be considered
orphaned. The new cohort (2062) should NOT be pruned yet — they are freshly
orphaned and may still be in transition.

Approach: run payload sync with raised limit targeting aged candidates only,
then verify counts drop.

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
🟦 task-brief=J03-T03_orphan-gc 🟦

id=J03-T03
role=agent
task_type=implementation
goal=Run a dry-run of orphan GC with raised limits to preview what will be pruned,
     then execute if dry-run looks safe. Target aged candidates only (2481).
     Do not prune new candidates (2062).

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none
note=hashall payload sync --orphan-gc-max-prune-count writes to catalog.db only
     (expected side-effect). No tracked file mutations or git commits.

allowed_commands=
- hashall payload sync --dry-run --orphan-gc-max-prune-count 3000 --orphan-gc-max-prune-fraction 0.9
- hashall payload sync --orphan-gc-max-prune-count 3000 --orphan-gc-max-prune-fraction 0.9
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 "" Enter

forbidden_commands=
- hashall payload sync without --orphan-gc-max-prune-count flag (uses default 1000 limit)
- hashall rehome (any subcommand)
- Any --execute or --apply flag on non-sync commands
- docker stop / docker restart
- git add / git commit
- rm, mv, rsync --delete

execution_order=
1. Dry-run first: hashall payload sync --dry-run --orphan-gc-max-prune-count 3000 --orphan-gc-max-prune-fraction 0.9
2. Review dry-run output — confirm orphans_to_prune <= 2481 (aged only, not new)
3. Stop if dry-run shows pruning new candidates or count seems wrong
4. Execute: hashall payload sync --orphan-gc-max-prune-count 3000 --orphan-gc-max-prune-fraction 0.9
5. Report final counts

required_artifacts=
- Full dry-run output
- Full execute output
- Extracted values:
    aged_before=2481
    new_before=2062
    pruned_count=
    aged_after=
    new_after=
    complete_after=
    incomplete_after=

success_criteria=
- Dry-run exits 0
- Execute exits 0
- pruned_count > 0 (aged candidates cleared)
- aged_after significantly reduced from 2481

stop_if=
- Dry-run shows pruned count > 2481 (would be pruning new candidates)
- Dry-run exits non-zero
- Output contains "database is locked"
- Any error suggesting catalog corruption

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T03_orphan-gc 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T03_orphan-gc 🟪

status="done|blocked"
task_id="J03-T03"
task_type="implementation"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="live: orphan GC pruned N catalog entries from catalog.db"
validation="<one-line summary>"
artifacts="terminal output below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

aged_before=2481
new_before=2062
pruned_count=
aged_after=
new_after=
complete_after=
incomplete_after=

<full dry-run output>
<full execute output>

🟪 task-log=J03-T03_orphan-gc 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T03--orphan-gc/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T03--orphan-gc/TASK-LOG.md

3. Notify Lead (two sends):
   tmux send-keys -t %14 "🟪 J03-T03 done | pruned=<N> aged_after=<N> new_after=<N>"
   tmux send-keys -t %14 "" Enter
