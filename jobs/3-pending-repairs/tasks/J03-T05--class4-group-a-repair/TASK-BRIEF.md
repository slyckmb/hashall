---
id: J03-T05
job: 3-pending-repairs
slug: class4-group-a-repair
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T05 — Class 4 Group A Repair (50 items with data)

## Context

J03-T04 found 84 Class 4 items:
  Group A (50): real files in _rehome-unique/<hash>/ — needs mv + repoint
  Group B (34): empty dirs — separate task, not this one

This task runs save-path-repair dry-run to preview all 50 Group A items,
then executes a pilot of the first 5 only. Lead reviews pilot results
before authorising the full batch.

save-path-repair per item:
  1. Infers canonical save path from qB category/tags
  2. Moves files from _rehome-unique/<hash>/ to canonical path
  3. Patches qB fastresume to new path (stops/starts qB container)
  4. Repoints RT via d.directory.set
  5. Triggers RT recheck

SAFETY RULES (from RUNBOOK.md):
  - Always dry-run first and review every line before execute
  - Never run --execute on cached/stale dry-run output
  - Pilot first 5 only — do NOT run LIMIT=0 without Lead approval
  - After pilot: run drift audit to confirm no regressions
  - Recovery: .bak-repair files written alongside each patched fastresume

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
🟦 task-brief=J03-T05_class4-group-a-repair 🟦

id=J03-T05
role=agent
task_type=implementation
goal=Run save-path-repair dry-run on all candidates, review output, then execute
     a pilot of the first 5 items only. Stop after pilot and report results.
     Do not run LIMIT=0 without explicit Lead approval in a future task.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none
note=save-path-repair --execute writes to live filesystem and qB fastresume
     files. Pilot of LIMIT=5 only. catalog.db mutations are expected.

allowed_commands=
- make save-path-repair-dry LIMIT=0
- make save-path-repair-apply LIMIT=5
- make client-drift-audit ANCHOR_SCAN=200000
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 "" Enter

forbidden_commands=
- make save-path-repair-apply LIMIT=0   (full batch — Lead approval required)
- make save-path-repair-apply LIMIT=<N> where N > 5
- hashall rehome (any subcommand)
- git add / git commit
- docker stop / docker restart (save-path-repair handles this internally)
- rm, mv, rsync (manual data movement)

execution_order=
1. Run dry-run: make save-path-repair-dry LIMIT=0
2. Review output — note any ambiguous or unexpected items
3. Stop if dry-run shows errors, ambiguous prefix matches, or bare-seeding-root targets
4. Run pilot: make save-path-repair-apply LIMIT=5
5. Run drift audit: make client-drift-audit ANCHOR_SCAN=200000
6. Report pilot results and drift change

required_artifacts=
- Full dry-run output (or summary if >100 lines — include first 20 and last 20)
- Full pilot execute output (all 5 items)
- Drift audit output post-pilot
- Extracted values:
    dry_run_candidates=
    dry_run_errors=
    pilot_applied=5
    pilot_errors=
    drift_before=4
    drift_after=

success_criteria=
- Dry-run exits 0 with candidate list
- Pilot applies exactly 5 items successfully
- Post-pilot drift audit exits 0
- drift_after <= drift_before (no regressions introduced)

stop_if=
- Dry-run shows "ambiguous prefix" errors (Bug B — do not proceed)
- Dry-run shows 0 candidates (unexpected — report and stop)
- Any pilot item errors with "fastresume not found" or "RT repoint failed"
- Post-pilot drift increases above 4 (regression)

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T05_class4-group-a-repair 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T05_class4-group-a-repair 🟪

status="done|blocked"
task_id="J03-T05"
task_type="implementation"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="live: 5 items moved + fastresumes patched + RT repointed"
validation="<one-line summary>"
artifacts="terminal output below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

dry_run_candidates=
dry_run_errors=
pilot_applied=5
pilot_errors=
drift_before=4
drift_after=

<dry-run output (first 20 + last 20 lines if long)>
<pilot execute output>
<post-pilot drift audit output>

🟪 task-log=J03-T05_class4-group-a-repair 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T05--class4-group-a-repair/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T05--class4-group-a-repair/TASK-LOG.md

3. Notify Lead (two sends):
   tmux send-keys -t %14 "🟪 J03-T05 done | candidates=<N> pilot_errors=<N> drift_after=<N>"
   tmux send-keys -t %14 "" Enter
