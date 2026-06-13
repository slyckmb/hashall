---
id: J03-T08
job: 3-pending-repairs
slug: health-item-enrichment
task_type: discovery
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T08 — Health Item Enrichment (Full Decision Matrix)

## Context

J03-T06 enumerated 18 RT DL items, 2 qB bad-state items, and 18 tracker issues.
The Lead cannot make accurate repair decisions without knowing:
  - Whether the tracker is still active, dead, archived, or merged
  - The canonical tracker_key from the traktor registry
  - Whether the RT label matches the canonical tracker_key
  - For cross-seed items: hardlink count and source data context
  - For near-complete items: exactly how many bytes/pieces are missing
  - Peer/seed counts from live RT XMLRPC

The traktor registry is the authoritative source for tracker status:
  /home/michael/dev/tools/traktor/config/tracker-registry.yml

## All Items to Enrich (from J03-T06)

### RT DL Items (18):
  6b6043ca  Hunter's Code Book 4           cross-seed  stoppedDL  0%    MAM tracker
  127c3834  River Monsters S07             torrentday  stalledDL  99.9% TorrentDay
  04aa5f33  How.Its.Made.S23               cross-seed  pausedDL   0%    YUSCENE
  4e4a7bc1  Greenland (seedpool)           cross-seed  stoppedDL  0%    seedpool.org
  2d4016de  NOVA.S50                       cross-seed  stalledDL  0%    speed.connecting.center
  e3f92c1c  Greenland (darkpeers)          cross-seed  stoppedDL  0%    darkpeers.org
  002e5db0  How.Its.Made.S24               cross-seed  pausedDL   0%    onlyencodes.cc
  145548eb  How.Its.Made.S22 (VIOLATION)   cross-seed  downloading 45%  TorrentDay
  8e438130  Muppet Christmas Carol         -           stoppedDL  0%    reelflix.cc
  245f2bce  Dexter S02                     speedcc     stalledDL  99.97% speed.connecting.center
  e36553b1  Dexter S07                     speedcc     stalledDL  99.96% speed.connecting.center
  282ec595  The Conjuring                  cross-seed  stoppedDL  0%    onlyencodes.cc
  73d05a65  Greenland (movies/reelflix)    movies      stoppedDL  0%    reelflix.xyz
  96d896ca  Transformers.Rise.Beasts       digitalcore stalledDL  99.99% digitalcore.club
  f0bc85ee  Magic City S01                 yuscene     pausedDL   0%    yu-scene.net
  5caca88d  Diary.Teenage.Girl             torrentleech stalledDL  98.4% torrentleech.org
  815e28c8  Smart Brevity                  abtorrents  stoppedDL  0%    usefultrash.net
  ef48a920  Fly Me To The Moon             -           stoppedDL  0%    aither.cc

### RT stoppedUP items (3, need hash lookup):
  Need to enumerate from RT cache — these are not in DL list above.

### qB bad-state items (2):
  8c3e841e  Love and Monsters              cross-seed  qb=stalledUP  rt=stalledUP
  4adbb5a7  V for Vendetta                 cross-seed  qb=stalledUP  rt=stoppedUP

### Tracker issues (18):
  ccd12d54  Euphoria S03E08    aither.cc  deleted
  491f271e  Euphoria S03E07    aither.cc  deleted
  6aba5d7d  Euphoria S03E02    aither.cc  deleted
  6eb07c0e  War Machine        aither.cc  deleted
  1c55faa7  Euphoria S03E05    aither.cc  deleted
  fa60c4f5  Euphoria S03E04    aither.cc  deleted
  8ae4283b  Euphoria S03E03    aither.cc  deleted
  6de6b6d9  Euphoria S03E01    aither.cc  deleted
  b60c32b2  Euphoria S03E06    aither.cc  deleted
  e08fbf38  SNL S51E18         aither.cc  deleted
  67dce701  Killers Flower Moon darkpeers.org deleted
  61c3c314  SNL S51E04         onlyencodes.cc  auth_err (InfoHash not found)
  05f8d888  SNL S51E02         onlyencodes.cc  auth_err
  6d6d0735  SNL S51E06         onlyencodes.cc  auth_err
  130b442d  SNL S51E03         onlyencodes.cc  auth_err
  9e403665  How Its Made S32   torrentleech.org  unregistered
  07828500  Legion S03         filelist.io  unregistered
  8f18b392  SNL S51E11         nebulance.io  passkey not found

## Bootstrap Context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
head=c92d2b9530218f38db01cb91f5f649757188b4be
goal=Pending repairs: resolve drift, recheck missingFiles, clean staging paths
```

## Brief

```
🟦 task-brief=J03-T08_health-item-enrichment 🟦

id=J03-T08
role=agent
task_type=discovery
goal=For every item from J03-T06, enrich with traktor registry data (tracker
     status, canonical tracker_key), live XMLRPC data (peer/seed counts, bytes
     missing), and hardlink context. Output a complete decision matrix the Lead
     can use to make final repair decisions.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none

allowed_commands=
- cat /home/michael/dev/tools/traktor/config/tracker-registry.yml
- grep -A10 "<tracker_key_or_domain>" /home/michael/dev/tools/traktor/config/tracker-registry.yml
- python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); ..."
  (for seeds, peers, bytes_missing, bytes_done per hash)
- cat ~/.cache/silo-rt/torrents.json | python3 -c "..." (read-only)
- cat ~/.cache/silo-qb/torrents-info.json | python3 -c "..." (read-only)
- stat / ls / find on seeding paths (read-only)
- git branch --show-current
- git rev-parse HEAD
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 "" Enter

forbidden_commands=
- Any file write or edit
- git add / git commit
- Any --execute or --apply flag
- hashall / rehome mutation commands
- docker stop / docker restart

required_artifacts=

For EACH item produce ONE enriched block in this exact format:

  hash=
  name=
  rt_state=
  rt_progress_pct=        (0-100)
  rt_bytes_done=
  rt_bytes_missing=       (from XMLRPC: d.size_bytes - d.bytes_done)
  rt_seeds=               (d.peers_complete from XMLRPC)
  rt_peers=               (d.peers_accounted from XMLRPC)
  rt_label=               (RT label/category)
  rt_directory=
  data_on_disk=           (yes/no/empty_dir)
  nlinks_sample=
  tracker_url=
  tracker_domain=         (extracted domain from tracker_url)
  registry_tracker_key=   (from traktor registry, or NOT_FOUND)
  registry_tracker_status= (active/dead/merged/unknown — from registry notes field or absence)
  registry_notes=         (any notes from registry about this tracker)
  label_matches_registry= (yes/no — does RT label match registry tracker_key?)
  qb_state=
  qb_save_path=
  issue_type=             (none/deleted/auth_err/unregistered/cross_seed_downloading/stoppedUP/stalledUP_qb)
  operator_decision=      (LEAVE BLANK — operator fills in)

For RT stoppedUP items: enumerate them from RT cache first, then enrich same way.

success_criteria=
- All 18 RT DL items enriched
- All 3 RT stoppedUP items enumerated and enriched
- All 2 qB bad-state items enriched
- All 18 tracker issue items enriched
- traktor registry consulted for every tracker domain
- XMLRPC bytes_missing and seeds queried for every item
- operator_decision field left blank on every item

stop_if=
- traktor registry file not found at expected path
- RT XMLRPC unreachable

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T08_health-item-enrichment 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T08_health-item-enrichment 🟪

status="done|blocked"
task_id="J03-T08"
task_type="discovery"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="<one-line summary>"
artifacts="full enriched decision matrix below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

items_enriched=
registry_lookups=
registry_not_found=

=== SECTION A: RT DL ITEMS (18) ===
<one enriched block per item>

=== SECTION B: RT stoppedUP ITEMS ===
<enumerate then enrich>

=== SECTION C: qB BAD-STATE ITEMS (2) ===
<one enriched block per item>

=== SECTION D: TRACKER ISSUE ITEMS (18) ===
<one enriched block per item>

🟪 task-log=J03-T08_health-item-enrichment 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T08--health-item-enrichment/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T08--health-item-enrichment/TASK-LOG.md

3. Notify Lead (two sends):
   tmux send-keys -t %14 "🟪 J03-T08 done | items=<N> registry_found=<N> registry_not_found=<N>"
   tmux send-keys -t %14 "" Enter
