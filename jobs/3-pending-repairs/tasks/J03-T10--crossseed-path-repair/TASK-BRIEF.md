---
id: J03-T10
job: 3-pending-repairs
slug: crossseed-path-repair
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T10 — Cross-Seed Path Repair (Rogue Code Damage)

## Background

Early hashall rehome code was rogue and damaged thousands of items' seeding paths.
Cross-seed items were left pointing to vacated directories. Cross-seed items must
NEVER download from trackers — they get data exclusively via hardlinks from existing
content on disk.

When a cross-seed item has:
- An empty subdirectory at its RT path (file was moved away by rogue code)
- Active downloading (violation — source hardlink was destroyed)
- nlinks > 1 (means the actual file IS on disk somewhere else)

...the correct repair is:
1. FIND the actual file on disk
2. DETERMINE the canonical path per spec: <seeding-root>/<tracker-key>/<payload-name>
3. REPOINT the RT torrent to the correct path (d.set_directory)
4. RECHECK (d.check_hash) and verify seeding

## Items to Investigate and Repair

### GROUP A: 3 Greenland cross-seed items (recheck failed — empty subdir at YUSCENE path)

All 3 point to `/data/media/torrents/seeding/YUSCENE (API)` in RT.
The filename exists there as an empty subdirectory, not the actual file.
T08 showed nlinks=5 — the actual 37GB file IS on disk somewhere.

  hash=4e4a7bc1f4284da8b20ce3663b5be1847664f61c  Greenland (seedpool)
    rt_directory=/data/media/torrents/seeding/YUSCENE (API)
    filename=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
    tracker=seedpool.org  registry_key=seedpool

  hash=e3f92c1c1d8dcde7042f0f849d15d13c1a480d2a  Greenland (darkpeers)
    rt_directory=/data/media/torrents/seeding/YUSCENE (API)
    filename=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
    tracker=darkpeers.org  registry_key=darkpeers

  hash=73d05a65527a9044f924b0b119810fbf46ff3081  Greenland (reelflix)
    rt_directory=/data/media/torrents/seeding/YUSCENE (API)
    filename=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
    tracker=reelflix.xyz  registry_key=reelflix

### GROUP B: 1 How.Its.Made.S22 (stopped cross-seed violation — source data status unknown)

Was actively downloading at 47% with 1 seeder. Stopped in T09.
nlinks=1 means the partial download is the only copy at that path.
Source data for a cross-seed should be the existing How.Its.Made.S22 ARR import.

  hash=145548eb360d03ffa6343f56ee94ba8ca7ea8f1c  How.Its.Made.S22
    rt_directory=/data/media/torrents/seeding/TorrentDay/How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
    tracker=td.jumbohostpro.eu  registry_key=torrentday
    current_state=stoppedDL at 47% (stopped by T09)

## Investigation Steps

### Step 1: Locate the Greenland file

```bash
find /data/media /pool/media /stash/media -name "Greenland.2020.Repack*.mkv" 2>/dev/null
```

Record every path found and its nlinks:
```bash
find /data/media /pool/media /stash/media -name "Greenland.2020.Repack*.mkv" -exec stat --format="%n nlinks=%h size=%s" {} \; 2>/dev/null
```

Also check the empty subdir issue:
```bash
ls -la "/data/media/torrents/seeding/YUSCENE (API)/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv"
```

### Step 2: Locate the How.Its.Made.S22 source data

Cross-seed source would be the ARR-imported copy. Look for it:
```bash
find /data/media /pool/media /stash/media -name "How.Its.Made.S22*" -type f 2>/dev/null | head -20
find /data/media /pool/media /stash/media -name "How.Its.Made.S22*" -type d 2>/dev/null | head -20
```

Also check the partial download directory for what files exist:
```bash
ls -la "/data/media/torrents/seeding/TorrentDay/How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG/"
```

### Step 3: Determine canonical paths

Per canonical path spec: `<seeding-root>/<tracker-key>/<payload-name>`

For Greenland items:
  - seedpool torrent → canonical: `<seeding-root>/seedpool/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv`
  - darkpeers torrent → canonical: `<seeding-root>/darkpeers/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv`
  - reelflix torrent → canonical: `<seeding-root>/reelflix/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv`

The seeding root for each item should be the same filesystem as the existing file.

For How.Its.Made.S22:
  - torrentday torrent → canonical: `<seeding-root>/TorrentDay/How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG/`
  - If source ARR data exists: hardlink each episode file to the canonical path

### Step 4: Repair

For each Greenland item where the actual file IS found:
  a. Create canonical directory if needed: mkdir -p '<seeding-root>/<tracker-key>/'
  b. Hardlink the file to canonical path:
     ln '<actual-file-path>' '<seeding-root>/<tracker-key>/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv'
  c. Remove empty subdir artifact: rmdir '<old-empty-dir>'
  d. Repoint RT: python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); print(s.d.set_directory('<hash>', '<seeding-root>/<tracker-key>'))"
  e. Recheck: python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); print(s.d.check_hash('<hash>'))"
  f. Verify state after 30s

For How.Its.Made.S22:
  - If source ARR data found: hardlink episodes to canonical TorrentDay path, repoint, recheck
  - If source data NOT found: report to Lead — torrent must remain stopped pending operator decision

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
🟦 task-brief=J03-T10_crossseed-path-repair 🟦

id=J03-T10
role=agent
task_type=implementation
goal=Locate actual data files for 4 cross-seed items damaged by rogue hashall code.
     For Greenland x3: find the actual 37GB mkv, hardlink to canonical tracker paths,
     remove empty subdir artifacts, repoint RT, recheck. For How.Its.Made.S22: locate
     ARR source data; if found hardlink+repoint+recheck; if not found report blocked.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=files+commits

allowed_commands=
- find /data/media /pool/media /stash/media -name "<pattern>" (read-only search)
- stat --format=... (read-only)
- ls -la (read-only)
- mkdir -p (create canonical dirs only)
- ln (hardlink only — never cp or mv)
- rmdir (empty dirs only — NEVER rm -rf)
- python3 -c "import xmlrpc.client; s.d.set_directory(...)" (repoint)
- python3 -c "import xmlrpc.client; s.d.check_hash(...)" (recheck)
- python3 -c "import xmlrpc.client; s.d.get_state(...)" (verify)
- git branch --show-current
- tmux send-keys -t %14 "<summary>" Enter

forbidden_commands=
- rm -rf (never)
- mv (never move files — hardlink only)
- cp (never copy — hardlink only)
- Any action on items not listed in this brief
- hashall / rehome mutation commands
- docker stop / docker restart

required_artifacts=
For each item:
  hash=
  name=
  file_found=yes/no
  file_found_at=<path or N/A>
  file_nlinks=
  canonical_path=
  hardlink_created=yes/no/already_exists
  empty_dir_removed=yes/no/N/A
  rt_repointed=yes/no
  rt_repoint_path=
  recheck_issued=yes/no
  post_recheck_state=
  outcome=ok/blocked/failed

success_criteria=
- All 3 Greenland items: file found, hardlinked to canonical path, RT repointed, recheck issued
- How.Its.Made.S22: source data found and hardlinked OR blocked report with location details
- No rm -rf used anywhere
- Empty subdir artifacts removed with rmdir (not rm)

stop_if=
- RT XMLRPC unreachable
- A target directory is NOT empty when attempting rmdir (report, abort that step)
- Actual file not found after thorough search (report blocked for that item, continue others)

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T10_crossseed-path-repair 🟦
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T10--crossseed-path-repair/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T10--crossseed-path-repair/TASK-LOG.md

3. Notify Lead:
   tmux send-keys -t %14 "🟪 J03-T10 done | greenland_repaired=<N>/3 s22_outcome=<ok|blocked>"
   tmux send-keys -t %14 "" Enter
