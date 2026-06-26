---
id: J03-T01
job: 3-pending-repairs
slug: repoint-drift-high
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T01 — Repoint 8 High-Priority Drift Items (qB → RT)

## Context

J02-T02 identified 8 high-priority path drift items where qB and RT disagree
but RT is already on the correct placement. All 8 are classified
`repoint_qb_to_rt_path` — RT is authoritative, no data movement required.
Dry-run first, then batch apply all 8.

## Target Hashes

| Hash | Item | Action |
|---|---|---|
| 446e3365be6f0b73 | Twin Peaks S01 1080p | qB stash:onlyencodes → pool:onlyencodes |
| 4bf5c39fea1a3341 | English Grammar Boot Camp | qB stash:DocsPedia → pool:DocsPedia |
| 63ce041b654eff04 | Brave New World S01 | qB stash:aither → pool:aither |
| 64ef4b90fda1d92a | NOVA S50 | qB stash:DigitalCore → pool:DigitalCore |
| 691f3d9453c501ed | His Three Daughters | qB pool:FileList.io → pool:cross-seed |
| 7842a0fe614c039b | Snowfall S03 | qB stash:Aither(API) → stash:Aither(API)/Snowfall... |
| c4acb67f41213201 | How It's Made S32 | qB stash:Aither(API) → stash:tv |
| e1a2a9368f5c2066 | Magic City S01 | qB stash:aither → pool:aither |

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
🟦 task-brief=J03-T01_repoint-drift-high 🟦

id=J03-T01
role=agent
task_type=implementation
goal=Dry-run then apply all 8 high-priority qB→RT repoints from J02-T02 drift
     audit. RT is authoritative for all 8. No data movement required.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none
note=qB fastresume patches and RT repoints are expected live-system side-effects,
     not tracked file mutations. No git commits in this task.

allowed_commands=
- make client-drift-audit ANCHOR_SCAN=200000
- make client-drift-qb-to-rt-dry HASH=<hash>
- make client-drift-qb-to-rt-apply HASH=<hash>
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 ""

forbidden_commands=
- hashall rehome (any subcommand)
- hashall payload save-path-repair --execute
- make client-drift-*-apply without prior dry-run for that hash
- git add / git commit
- Any rm, mv, rsync --delete

execution_order=
1. Run dry-run for all 8 hashes first — review output before any apply
2. Stop if any dry-run shows unexpected result (wrong path, missing data, error)
3. Apply hashes one at a time — verify drift count drops after each
4. Run final drift audit to confirm drift reduced from 12 to 4

required_artifacts=
- Dry-run output for all 8 hashes
- Apply output for each hash (or blocked reason if any)
- Final drift audit showing new counts
- Extracted values:
    hashes_attempted=
    hashes_applied=
    hashes_blocked=
    drift_before=12
    drift_after=
    errors=

success_criteria=
- All 8 hashes dry-run clean (no unexpected paths or errors)
- All 8 applied successfully (or blocked count explained)
- Final drift_after = 4 (the 4 low/manual-review items remain)
- Final drift audit exits 0

stop_if=
- Any dry-run shows unexpected path or data-missing error
- Any apply changes more files than expected
- qB or RT daemon becomes unreachable mid-run
- drift_after > 6 after all applies (something went wrong)

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T01_repoint-drift-high 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T01_repoint-drift-high 🟪

status="done|blocked"
task_id="J03-T01"
task_type="implementation"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="live: qB fastresumes patched, RT repointed for N hashes"
validation="<one-line summary>"
artifacts="terminal output below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

hashes_attempted=
hashes_applied=
hashes_blocked=
drift_before=12
drift_after=
errors=

<paste dry-run output for all 8 hashes>
<paste apply output for each hash>
<paste final drift audit output>

🟪 task-log=J03-T01_repoint-drift-high 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T01--repoint-drift-high/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T01--repoint-drift-high/TASK-LOG.md

3. Notify Lead tmux pane (two sends):
   tmux send-keys -t %14 "🟪 J03-T01 done | applied=<N> blocked=<N> drift_after=<N>"
   tmux send-keys -t %14 ""
