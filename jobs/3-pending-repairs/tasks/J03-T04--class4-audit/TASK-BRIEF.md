---
id: J03-T04
job: 3-pending-repairs
slug: class4-audit
task_type: discovery
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T04 — Class 4 Audit (_rehome-unique items)

## Context

J02-T03 found 64 Class 4 items (_rehome-unique/<hash>/) — significantly higher
than the May 2026 baseline of 12, even after Slice 12a deleted 376 dirs.
J03-T02b identified 2 of these as the stoppedDL 0% hashes (ef48a920, 8e438130).

The 64 items need categorising into the three groups before any repair:
  Group A — data physically in _rehome-unique/<hash>/  (requires mv + repoint)
  Group B — _rehome-unique/<hash>/ dir is empty        (safe to delete + repoint)
  Group C — nested _rehome-unique/ under cross-seed/<tracker>/  (manual only)

This is discovery only — no mutations. The goal is to understand the population
so Lead can decide repair scope and sequence.

Known Class 4 hashes from J03-T02b (2 of the 64):
  ef48a9203545aa798775fba7e9a3e7ca396032fe  stash _rehome-unique
  8e438130b072708877003225a5079040991de5d7  pool  _rehome-unique

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
🟦 task-brief=J03-T04_class4-audit 🟦

id=J03-T04
role=agent
task_type=discovery
goal=Enumerate all _rehome-unique/<hash>/ directories on stash and pool seeding
     roots. Categorise each as Group A (has data), Group B (empty), or Group C
     (nested). Report counts and sample paths. No mutations.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none

allowed_commands=
- find /data/media/torrents/seeding/_rehome-unique -maxdepth 1 -mindepth 1 -type d 2>/dev/null
- find /stash/media/torrents/seeding/_rehome-unique -maxdepth 1 -mindepth 1 -type d 2>/dev/null
- find /pool/media/torrents/seeding/_rehome-unique -maxdepth 1 -mindepth 1 -type d 2>/dev/null
- find /data/media/torrents/seeding/cross-seed -name "_rehome-unique" -type d 2>/dev/null
- find /pool/media/torrents/seeding/cross-seed -name "_rehome-unique" -type d 2>/dev/null
- ls -la <path>
- du -sh <path>
- find <hash-dir> -type f | head -5  (check if dir has real content)
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 "" Enter

forbidden_commands=
- rm, mv, rsync (any mutation)
- hashall payload save-path-repair --execute
- Any --execute or --apply flag
- git add / git commit
- docker stop / docker restart

required_artifacts=
- Total count of _rehome-unique/<hash>/ dirs found across all roots
- Count per group (A/B/C)
- Sample paths (up to 5) for each group
- The 2 known hashes from J03-T02b confirmed present and classified
- Extracted values:
    total_class4=
    group_a_count=   (has real files)
    group_b_count=   (empty dir)
    group_c_count=   (nested under cross-seed/)
    stash_count=
    pool_count=

success_criteria=
- All _rehome-unique dirs enumerated across stash and pool
- Each dir classified as A, B, or C
- total_class4 reported (expect ~64 per J02-T03)
- No mutations performed

stop_if=
- find command errors on all seeding roots (permission or path issue)
- total_class4 > 200 (unexpected — stop and report before classifying)

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T04_class4-audit 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T04_class4-audit 🟪

status="done|blocked"
task_id="J03-T04"
task_type="discovery"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="<one-line summary>"
artifacts="enumeration below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

total_class4=
group_a_count=
group_b_count=
group_c_count=
stash_count=
pool_count=

<enumeration of all dirs with group classification>

🟪 task-log=J03-T04_class4-audit 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T04--class4-audit/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T04--class4-audit/TASK-LOG.md

3. Notify Lead (two sends):
   tmux send-keys -t %14 "🟪 J03-T04 done | total=<N> group_a=<N> group_b=<N> group_c=<N>"
   tmux send-keys -t %14 "" Enter
