---
id: J03-T13
job: 3-pending-repairs
slug: trk-warn-deleted
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-13
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T13 — Tracker Warning: Replace Deleted Items (Season Pack Upgrade + Individual)

## Context

11 RT items have `issue_type=deleted` — the tracker removed the torrent entry.
All items are still seeding fine (stalledUP), but they have no tracker relationship
for ratio credit or announce.

The trk_warn flow can:
  1. Find a season pack upgrade on Prowlarr (preferred) — erase the individual
     episode torrents and add the full season pack torrent instead
  2. Find individual episode replacements on Prowlarr — erase the deleted
     torrent and add the correct replacement

Operator has approved: run dry-run first, then execute.

## Items (11 deleted)

All from Section D of J03-T08:

  ccd12d54  Euphoria S03E08  aither.cc
  491f271e  Euphoria S03E07  aither.cc
  6aba5d7d  Euphoria S03E02  aither.cc
  6eb07c0e  War Machine 2026  aither.cc
  1c55faa7  Euphoria S03E05  aither.cc
  fa60c4f5  Euphoria S03E04  aither.cc
  8ae4283b  Euphoria S03E03  aither.cc
  6de6b6d9  Euphoria S03E01  aither.cc
  b60c32b2  Euphoria S03E06  aither.cc
  e08fbf38  SNL S51E18  aither.cc
  67dce701  Killers of the Flower Moon  darkpeers.org

## Execution Plan

### Step 1: Dry-run (read-only, no changes)

Run from the worktree root (Makefile is here):
  cd /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
  make trk-warn-dry BUCKET=deleted 2>&1 | tee /tmp/trk-warn-dry-j03t13.txt

Read the output carefully. Report:
  - Which items are candidates for season-pack upgrade
  - Which items can only get individual replacement
  - Which items have no replacement found
  - Any warnings or errors

### Step 2: Execute season pack upgrades (if dry-run shows candidates)

If dry-run identifies season pack upgrade candidates (e.g. Euphoria S03 → add full S03 pack):
  make trk-warn-upgrade-packs BUCKET=deleted 2>&1 | tee /tmp/trk-warn-upgrade-j03t13.txt

This will:
  - Erase the individual episode torrents (and sync removal to qB)
  - Add the season pack torrent via Prowlarr
  - The new torrent should verify immediately since episode data is already on disk

### Step 3: Execute individual replacements (for items with no pack upgrade)

If dry-run shows individual replacements for remaining items (War Machine, SNL S51E18,
Killers of the Flower Moon):
  make trk-warn-replace-individual BUCKET=deleted 2>&1 | tee /tmp/trk-warn-replace-j03t13.txt

### Step 4: Verify

After execution, check RT tracker issue count:
  make trk-warn BUCKET=deleted 2>&1 | head -20

Expected: deleted count should decrease by number of successfully replaced items.

## Bootstrap Context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
head=<current>
```

## Brief

```
🟦 task-brief=J03-T13_trk-warn-deleted 🟦

id=J03-T13
role=agent
task_type=implementation
goal=Run trk_warn flow for 11 deleted tracker items. Dry-run first to see what
     Prowlarr finds, then execute: season-pack upgrades where available (expected
     for Euphoria S03), individual replacements for remaining items. Report what
     was upgraded, replaced, and what had no replacement found.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=current

allowed_mutation=files+commits

allowed_commands=
- make trk-warn-dry BUCKET=deleted (dry-run, read-only)
- make trk-warn-upgrade-packs BUCKET=deleted (execute pack upgrades)
- make trk-warn-replace-individual BUCKET=deleted (execute individual replacements)
- make trk-warn BUCKET=deleted (verify final state)
- cat /tmp/trk-warn-*.txt (read saved output)
- git branch --show-current
- git status --short
- tmux send-keys -t %14 "<summary>" Enter

forbidden_commands=
- make trk-warn-cleanup (only removes, no replacements — not what we want)
- Any hashall/rehome mutation commands unrelated to trk-warn
- docker stop / docker restart

required_artifacts=
dry_run_output=      (full output from trk-warn-dry)
pack_upgrades=       (list: hash, name, pack_found, action_taken)
individual_replacements= (list: hash, name, replacement_found, action_taken)
no_replacement=      (list: hash, name, reason)
final_tracker_issue_count= (from trk-warn verification)

success_criteria=
- Dry-run completed and output reviewed before any execution
- All upgrade/replace commands run for items where Prowlarr found a match
- Final tracker issue count reported
- No execution if dry-run shows errors or unexpected state

stop_if=
- trk-warn-dry exits with error
- Dry-run shows unexpected items in scope (more than 11 deleted items)
- Any make target fails with non-zero exit

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T13_trk-warn-deleted 🟦
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T13--trk-warn-deleted/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T13--trk-warn-deleted/TASK-LOG.md

3. Notify Lead:
   tmux send-keys -t %14 "🟪 J03-T13 done | upgraded=<N> replaced=<N> no_match=<N> deleted_remaining=<N>"
   tmux send-keys -t %14 "" Enter
