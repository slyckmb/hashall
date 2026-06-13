---
id: J03-T12
job: 3-pending-repairs
slug: s23-s24-violation-repair
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T12 — How.Its.Made S23/S24 Cross-Seed Violation Repair

## Background

Two cross-seed items are actively downloading from their trackers — a policy
violation. Cross-seed items must NEVER download; they are hardlinked from
existing data only.

  hash=04aa5f3339d3ccfd1f14dd114db16c92aa87f74a  How.Its.Made.S23
    tracker=yuscene  rt_label=cross-seed
    rt_directory=/data/media/torrents/seeding/YUSCENE (API)/How.Its.Made.S23...
    last_known_state=downloading at 32.5%, 4 seeds

  hash=002e5db0ad4bee86419ccf244d212f6d1150d1e8  How.Its.Made.S24
    tracker=onlyencodes  rt_label=cross-seed
    rt_directory=/data/media/torrents/seeding/OnlyEncodes (API)/How.Its.Made.S24...
    last_known_state=downloading at 49.8%, 8 seeds

## Hashall DB Reference

  stash/media → files_fs_zfs_4624186565346049802  (mount: /stash/media)
  pool-media  → files_fs_zfs_4673783476987974510  (mount: /pool/media)
  pool-data   → files_fs_zfs_7422444370835627448  (mount: /pool/data)

  Note: /data/media/... in RT = /stash/media/... on host filesystem

## Step 1: Stop Both Immediately

  python3 -c "
  import xmlrpc.client
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  for h in [
    '04aa5f3339d3ccfd1f14dd114db16c92aa87f74a',
    '002e5db0ad4bee86419ccf244d212f6d1150d1e8',
  ]:
    result = s.d.stop(h)
    state = s.d.state(h)
    active = s.d.is_active(h)
    print(f'{h[:8]}: stop={result} state={state} active={active}')
  "

Verify both are stopped (active=0).

## Step 2: Inventory What Is Currently On Disk

For each torrent, get the full file list and check what exists at the RT path:

  python3 -c "
  import xmlrpc.client, os
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  for label, h in [('S23', '04aa5f3339d3ccfd1f14dd114db16c92aa87f74a'),
                   ('S24', '002e5db0ad4bee86419ccf244d212f6d1150d1e8')]:
    base_dir = s.d.directory(h)
    files = s.f.multicall(h, '',
      'f.path=', 'f.size_bytes=', 'f.completed_chunks=', 'f.size_chunks=')
    print(f'=== {label} base_dir={base_dir} ===')
    for f in files:
      path, size, done_chunks, total_chunks = f
      pct = done_chunks/total_chunks*100 if total_chunks > 0 else 0
      full_path = os.path.join(base_dir, path)
      on_disk = os.path.exists(full_path)
      nlinks = os.stat(full_path).st_nlink if on_disk else 0
      print(f'  {pct:.1f}%  nlinks={nlinks}  size={size}  {path}')
  "

Report: for each file, what % complete, is it on disk, nlinks.

## Step 3: Search Hashall DB for Complete Source Files

For each episode file in S23 and S24, search all 3 DB tables for the filename
at FULL size (size must match exactly — partial downloads don't count):

  sqlite3 ~/.hashall/catalog.db "
  SELECT 'stash', path, size FROM files_fs_zfs_4624186565346049802
  WHERE path LIKE '%How.Its.Made.S23%' AND size > 1000000
  UNION ALL
  SELECT 'pool-media', path, size FROM files_fs_zfs_4673783476987974510
  WHERE path LIKE '%How.Its.Made.S23%' AND size > 1000000
  UNION ALL
  SELECT 'pool-data', path, size FROM files_fs_zfs_7422444370835627448
  WHERE path LIKE '%How.Its.Made.S23%' AND size > 1000000
  ORDER BY 1, 2;" 2>/dev/null

  sqlite3 ~/.hashall/catalog.db "
  SELECT 'stash', path, size FROM files_fs_zfs_4624186565346049802
  WHERE path LIKE '%How.Its.Made.S24%' AND size > 1000000
  UNION ALL
  SELECT 'pool-media', path, size FROM files_fs_zfs_4673783476987974510
  WHERE path LIKE '%How.Its.Made.S24%' AND size > 1000000
  UNION ALL
  SELECT 'pool-data', path, size FROM files_fs_zfs_7422444370835627448
  WHERE path LIKE '%How.Its.Made.S24%' AND size > 1000000
  ORDER BY 1, 2;" 2>/dev/null

## Step 4: Repair (if source data found)

For each season (S23, S24):

  a. Remove any partial download files (nlinks=1, partially downloaded):
     These are bytes downloaded from the tracker — not hardlinked originals.
     For each file at RT path with nlinks=1 AND pct < 100%:
       rm '<rt_path>/<file>'

  b. For each episode file: hardlink from source to RT path:
       ln -f '<source_path>/<episode_file>' '<rt_path>/<episode_file>'

  c. Repoint RT to canonical path per spec:
     Canonical path for cross-seed items: <seeding-root>/cross-seed/<prowlarr-tracker-name>/<payload-name>
     For S23 (yuscene tracker):    /data/media/torrents/seeding/YUSCENE (API)/How.Its.Made.S23...
     For S24 (onlyencodes tracker): /data/media/torrents/seeding/OnlyEncodes (API)/How.Its.Made.S24...
     (These may already be canonical — verify before repointing)

  d. Recheck: s.d.check_hash('<hash>')
  e. Start:   s.d.start('<hash>')
  f. Verify after 60s: should be stalledUP or uploading at 100%

## Step 5: If Source Data NOT Found

  - Leave both stopped
  - Report which files are missing
  - Do NOT remove without operator approval
  - Operator decision: remove dead cross-seed, restore from backup, or leave

## Bootstrap Context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
head=c92d2b9530218f38db01cb91f5f649757188b4be
```

## Brief

```
🟦 task-brief=J03-T12_s23-s24-violation-repair 🟦

id=J03-T12
role=agent
task_type=implementation
goal=Stop cross-seed violations on How.Its.Made.S23 and S24 (actively downloading).
     Inventory what is currently on disk. Search hashall DB for complete source files.
     If found: replace partial downloads with hardlinks, recheck, verify seeding.
     If not found: leave stopped and report.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=files+commits

allowed_commands=
- python3 -c "import xmlrpc.client; s.d.stop(...), s.d.state(...), s.d.is_active(...)" (stop only)
- python3 -c "import xmlrpc.client; s.f.multicall(...)" (file inventory)
- python3 -c "import xmlrpc.client; s.d.check_hash(...), s.d.start(...)" (after repair)
- python3 -c "os.path.exists(...), os.stat(...).st_nlink" (disk checks)
- sqlite3 ~/.hashall/catalog.db "..." (read-only DB queries)
- rm '<file>' (partial download files only — nlinks=1, incomplete — NEVER rm -rf)
- ln -f (hardlink from source to RT path)
- mkdir -p (canonical dirs only if needed)
- git branch --show-current
- tmux send-keys -t %14 "<summary>" Enter

forbidden_commands=
- rm -rf (never)
- mv (never move data files)
- Any action on items other than S23 and S24
- hashall / rehome mutation commands

required_artifacts=
For each item (S23, S24):
  hash=
  name=
  stopped_ok=           (yes/no)
  files_on_disk=        (list: filename, pct_complete, nlinks, size)
  source_data_found=    (yes/partial/no)
  source_locations=     (DB paths)
  partial_files_removed= (count)
  hardlinks_created=    (count)
  recheck_issued=       (yes/no)
  post_recheck_state=   (state after verification)
  outcome=              (resolved/partial/blocked)

success_criteria=
- Both S23 and S24 stopped immediately
- hashall DB searched for all episode files
- If data found: hardlinks replace partials, recheck passes at 100%, seeding
- If data not found: stopped and blocked report with file inventory

stop_if=
- RT XMLRPC unreachable
- d.stop() fails (report immediately)

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T12_s23-s24-violation-repair 🟦
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T12--s23-s24-violation-repair/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T12--s23-s24-violation-repair/TASK-LOG.md

3. Notify Lead:
   tmux send-keys -t %14 "🟪 J03-T12 done | s23=<ok|blocked> s24=<ok|blocked>"
   tmux send-keys -t %14 "" Enter
