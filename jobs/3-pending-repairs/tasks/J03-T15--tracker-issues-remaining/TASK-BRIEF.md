---
id: J03-T15
job: 3-pending-repairs
slug: tracker-issues-remaining
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-13
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T15 — Remaining RT Tracker Issues

## Current Tracker Issue Inventory (8 items)

### Unregistered — can attempt replacement via trk_warn (2 items)
  9e403665  How.Its.Made.S32.1080p.AMZN.WEB-DL.DDP2.0.H.264-NTb  TorrentLeech
  07828500  Legion.S03.1080p.AMZN.WEB-DL.DDP5.1.H.264-playWEB    FileList.io

### Auth error — operator must renew credentials (4 items, cannot automate)
  61c3c314  Saturday.Night.Live.S51E04  onlyencodes.cc  "InfoHash not found"
  05f8d888  Saturday.Night.Live.S51E02  onlyencodes.cc  "InfoHash not found"
  6d6d0735  Saturday.Night.Live.S51E06  onlyencodes.cc  "InfoHash not found"
  130b442d  Saturday.Night.Live.S51E03  onlyencodes.cc  "InfoHash not found"

### Passkey not found — operator must renew (1 item, cannot automate)
  8f18b392  Saturday.Night.Live.S51E11  nebulance.io  "Passkey not found"

### Deleted, no replacement found (1 item)
  e08fbf38  Saturday.Night.Live.S51E18  aither.cc  "Torrent has been deleted"

## Task Scope

Run trk_warn for the `other` bucket (unregistered items) only.
Report findings for operator action on auth_err and passkey items.
Check if SNL S51E18 (deleted) has any new Prowlarr hits since T13.

## Step 1: Dry-run trk_warn for unregistered items

  cd /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
  make trk-warn-dry BUCKET=other 2>&1 | tee /tmp/trk-warn-other-dry-j03t15.txt

Review output carefully:
- How.Its.Made.S32: look for 1080p replacement on TorrentLeech
- Legion.S03: look for 1080p replacement on FileList.io
- QUALITY RULE: 1080p only. Do NOT add any 2160p/4K/UHD result.

## Step 2: Execute if dry-run finds valid 1080p replacements

If individual replacements found (not season packs — these are complete seasons already):
  make trk-warn-replace-individual BUCKET=other 2>&1 | tee /tmp/trk-warn-other-replace-j03t15.txt

If season pack upgrades are a better fit:
  make trk-warn-upgrade-packs BUCKET=other 2>&1 | tee /tmp/trk-warn-other-upgrade-j03t15.txt

## Step 3: Re-check SNL S51E18 (previously no replacement found)

Run a targeted Prowlarr search for this specific episode:
  HASH=e08fbf38bef3a0bb3a7a5a1cc0a3a6aff8898abd make trk-warn-dry 2>&1 | tail -20

Report: is a 1080p replacement now available, or still nothing?

## Step 4: Report operator actions needed

For auth_err items (OnlyEncodes x4 + Nebulance x1), report what the operator needs to do:
  - OnlyEncodes: log in at onlyencodes.cc, regenerate passkey/API key, update in RT
    tracker config (typically in the announce URL or a separate passkey env file)
  - Nebulance: log in at nebulance.io, regenerate passkey, update RT tracker config
  - Check if there's a passkey file or env var for these trackers:
    grep -r "onlyencodes\|nebulance" /mnt/config/secrets/ 2>/dev/null | head -10

## Bootstrap Context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
```

## Brief

```
🟦 task-brief=J03-T15_tracker-issues-remaining 🟦

id=J03-T15
role=agent
task_type=implementation
goal=Run trk_warn for the 'other' bucket (2 unregistered items). Execute replacements
     if 1080p matches found. Re-check SNL S51E18 deleted item. Report passkey/auth_err
     items with operator instructions for manual credential renewal.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=current
allowed_mutation=files+commits

allowed_commands=
- make trk-warn-dry BUCKET=other
- make trk-warn-replace-individual BUCKET=other
- make trk-warn-upgrade-packs BUCKET=other
- make trk-warn-dry HASH=<hash> (targeted search for SNL S51E18)
- grep -r "onlyencodes\|nebulance" /mnt/config/secrets/ (read-only)
- cat /tmp/trk-warn-*.txt
- git branch --show-current
- tmux send-keys -t %14 "<summary>" Enter

forbidden_commands=
- Adding any 2160p/4K/UHD torrent (immediate stop)
- make trk-warn-cleanup (removes without replacing)
- hashall/rehome mutation commands

required_artifacts=
  step1_dry_run_output=
  how_its_made_s32_replacement=found_1080p/found_4k_skipped/not_found
  legion_s03_replacement=found_1080p/found_4k_skipped/not_found
  snl_s51e18_status=replacement_found/still_no_match
  auth_err_operator_instructions=<what operator needs to do for OnlyEncodes+Nebulance>
  tracker_issue_count_after=

success_criteria=
- trk_warn-dry run and output reviewed
- 1080p replacements added for any unregistered items where found
- SNL S51E18 re-checked
- Operator instructions documented for auth_err/passkey items
- No 4K/UHD torrents added

stop_if=
- trk-warn-dry exits with error
- Only 4K replacements available (do not add — report no suitable 1080p)

final_output_required=true
worktree_mirror_required=false

🟦 task-brief=J03-T15_tracker-issues-remaining 🟦
```

## After completing this task

1. Write TASK-LOG.md to:
   .../tasks/J03-T15--tracker-issues-remaining/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T15--tracker-issues-remaining/TASK-LOG.md

3. Notify Lead:
   tmux send-keys -t %14 "🟪 J03-T15 done | replaced=<N> no_match=<N> operator_needed=<N> remaining_issues=<N>"
   tmux send-keys -t %14 "" Enter
