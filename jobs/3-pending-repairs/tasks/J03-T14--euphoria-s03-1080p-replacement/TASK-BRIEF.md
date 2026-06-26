---
id: J03-T14
job: 3-pending-repairs
slug: euphoria-s03-1080p-replacement
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-13
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T14 — Euphoria S03: Remove 4K, Add 1080p Season Pack

## Background

T13 ran trk_warn-upgrade-packs and added a 2160p/4K season pack for Euphoria S03.
This is wrong — the system runs 1080p ONLY. 4K files must never be added.

**QUALITY RULE:** This system is 1080p only. Never add 2160p, 4K, HDR, or UHD
torrents. If only 4K is available on a tracker, report "no suitable replacement"
and do not add anything.

The 2160p pack has been stopped (state=0). It must be fully erased, and a proper
1080p season pack must be found and added instead.

## Current state

  hash=A39C355D (full: a39c355d...)  Euphoria.US.S03.2160p.AMZN.WEB-DL.DDP5.1.Atmos.H.265-Kitsune
  state=stopped  progress=~1.6%  data_downloaded=~small (stopped early, safe to delete files)
  rt_directory=TBD (get from d.directory before erasing)

## Step 1: Erase the 2160p torrent and its partial data

Get the directory first:
  python3 -c "
  import xmlrpc.client
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  items = s.d.multicall2('', 'main', 'd.hash=', 'd.name=', 'd.directory=')
  for i in items:
    if 'Euphoria' in i[1] and 'S03' in i[1] and '2160' in i[1]:
      print(f'hash={i[0]}  dir={i[2]}')
  "

Erase from RT (use d.erase, not d.stop — it's already stopped):
  python3 -c "
  import xmlrpc.client
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  items = s.d.multicall2('', 'main', 'd.hash=', 'd.name=')
  for i in items:
    if 'Euphoria' in i[1] and 'S03' in i[1] and '2160' in i[1]:
      print(f'Erasing {i[0][:8]}...')
      s.d.erase(i[0])
  "

Remove from qB:
  python3 -c "
  import json, os, requests
  data = json.load(open(os.path.expanduser('~/.cache/silo-qb/torrents-info.json')))
  for t in data:
    if 'Euphoria' in t.get('name','') and 'S03' in t.get('name','') and '2160' in t.get('name',''):
      h = t['hash']
      print(f'Removing from qB: {h[:8]}')
      requests.post('http://localhost:9003/api/v2/torrents/delete',
                    data={'hashes': h, 'deleteFiles': 'false'})
  "

Delete the partial download directory (only ~1.6% was downloaded, safe to remove):
  # Get the RT directory from above, then:
  rm -rf '<rt_directory>/Euphoria.US.S03.2160p.AMZN.WEB-DL.DDP5.1.Atmos.H.265-Kitsune'
  # Use rm -rf ONLY for this specific 2160p partial download directory

## Step 2: Search Prowlarr for 1080p Euphoria S03 season pack

Use the trk_warn Prowlarr search, OR query Prowlarr API directly:

Option A — Use trk_warn dry-run to see available options:
  cd /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
  HASH=<one_of_the_original_euphoria_episode_hashes> make trk-warn-dry 2>&1

  Note: the original 8 episode hashes have already been erased from RT by T13.
  We need to search Prowlarr directly.

Option B — Query Prowlarr API for 1080p Euphoria S03 pack:
  python3 -c "
  import requests
  # Prowlarr search for Euphoria S03 season pack, 1080p only
  r = requests.get('http://localhost:9696/api/v1/search',
    params={'query': 'Euphoria S03', 'type': 'search', 'limit': 20},
    headers={'X-Api-Key': open('/home/michael/.config/prowlarr-api-key').read().strip()}
  )
  results = r.json()
  for item in results:
    title = item.get('title','')
    size = item.get('size', 0) / (1024**3)
    cats = item.get('categories', [])
    # Filter: 1080p only, season packs, skip 2160p/4K/UHD/HDR
    if '1080' in title and 'S03' in title and '2160' not in title and 'UHD' not in title:
      print(f'{size:.1f}GB  {title[:80]}')
  "

  Note: Check the correct Prowlarr API key location — it may be in a config file or env var.
  Try: grep -r 'prowlarr' /home/michael/dev/sys/docker/ --include='*.env' 2>/dev/null | grep -i 'api' | head -5

Option C — Use the trk_warn script directly with quality filter:
  Check if the script supports a quality/resolution filter flag:
  python3 ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py --help 2>&1 | grep -i '1080\|quality\|resol\|filter'

## Step 3: Add the 1080p season pack

Once a 1080p season pack is identified (verify the title contains '1080p' and does NOT
contain '2160p', 'UHD', '4K', 'HDR'):

Add via Prowlarr/qBittorrent add API, or via RT's `load.start` XMLRPC command with
the .torrent file downloaded from Prowlarr.

If using trk_warn replacement flow, it may support direct add.

## Step 4: Verify

Confirm:
- 2160p torrent is fully gone from RT and qB
- 1080p season pack is added and seeding/downloading
- RT tracker_issue count for Euphoria S03 is 0

## Bootstrap Context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
```

## Brief

```
🟦 task-brief=J03-T14_euphoria-s03-1080p-replacement 🟦

id=J03-T14
role=agent
task_type=implementation
goal=Remove the wrongly-added 2160p Euphoria S03 season pack (stopped, ~1.6% downloaded).
     Find and add a 1080p season pack for Euphoria S03 via Prowlarr instead.
     QUALITY RULE: 1080p only — never add 2160p/4K/UHD/HDR torrents.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=current

allowed_mutation=files+commits

allowed_commands=
- python3 -c "import xmlrpc.client; s.d.erase(...)" (erase 2160p torrent)
- python3 -c "import requests; requests.post(...api/v2/torrents/delete...)" (qB remove)
- rm -rf '<rt_directory>/Euphoria.US.S03.2160p.*' (remove partial download data ONLY)
- python3 -c "import requests; ..." (Prowlarr API search, read-only)
- python3 ~/dev/sys/docker/.../rt-tracker-manual-report.py --help (inspect tool flags)
- make trk-warn-dry (dry-run for Prowlarr search)
- make trk-warn-replace-individual BUCKET=deleted HASH=<hash> (if applicable)
- grep -r prowlarr ... (find API key)
- git branch --show-current
- tmux send-keys -t %14 "<summary>" Enter

forbidden_commands=
- Adding ANY 2160p/4K/UHD/HDR torrent (immediate stop if found)
- rm -rf on anything other than the specific 2160p partial download dir
- hashall/rehome mutation commands unrelated to this task

required_artifacts=
  step1_2160p_erased=yes/no
  step1_partial_data_removed=yes/no
  step2_1080p_pack_found=yes/no/title
  step2_pack_size_gb=
  step3_pack_added=yes/no
  step3_rt_state=
  step4_euphoria_tracker_issue_remaining=

success_criteria=
- 2160p torrent fully erased from RT and qB
- 1080p season pack found and added (or "no 1080p pack available" if not found)
- Verification run confirms 0 deleted Euphoria S03 items remaining (if pack found)

stop_if=
- Only 2160p/4K available on Prowlarr (do not add — report no suitable 1080p found)
- rm -rf would affect non-2160p data

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T14_euphoria-s03-1080p-replacement 🟦
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T14--euphoria-s03-1080p-replacement/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T14--euphoria-s03-1080p-replacement/TASK-LOG.md

3. Notify Lead:
   tmux send-keys -t %14 "🟪 J03-T14 done | 2160p_erased=<yes|no> 1080p_pack=<found|not_found> outcome=<ok|blocked>"
   tmux send-keys -t %14 "" Enter
