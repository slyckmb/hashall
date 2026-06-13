---
id: J03-T11
job: 3-pending-repairs
slug: rt-dl-data-investigation
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T11 — RT DL Data Investigation and Repair

## Policy

Per RT-QB-STATE-POLICY.md v1.1.0 §6 Step 0:

> For ANY RT item not seeding at 100%, ALWAYS search the hashall DB for
> payload data before treating as unresolvable. Zero tracker seeds does
> not mean zero local data. If data found → hardlink + repoint + recheck.

## Hashall DB Reference

Three filesystems to query (all scanned 2026-06-12):

  stash/media → /stash/media  → files_fs_zfs_4624186565346049802
  pool-media  → /pool/media   → files_fs_zfs_4673783476987974510
  pool-data   → /pool/data    → files_fs_zfs_7422444370835627448

Note: RT reports paths as /data/media/... which maps to /stash/media/...
(bind mount). DB paths under stash table are RELATIVE to /stash/media/.

DB query pattern (search by filename):
  sqlite3 ~/.hashall/catalog.db \
    "SELECT path, size FROM files_fs_zfs_4624186565346049802
     WHERE path LIKE '%<filename>%' AND size > 0
     ORDER BY size DESC;"

For multi-file torrents, get the file list first via XMLRPC:
  python3 -c "
  import xmlrpc.client
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  files = s.f.multicall('<hash>', '',
    'f.path=', 'f.size_bytes=', 'f.completed_chunks=', 'f.size_chunks=')
  for f in files:
    pct = (f[2]/f[3]*100) if f[3] > 0 else 0
    print(f'{pct:.1f}%  {f[1]}B  {f[0]}')
  "

## Part A: Identify 2 Unknown Active DL Items

The dashboard shows DL: active=2, but our T06 inventory only accounts for
stalled and stopped items. These 2 active downloaders are unknown.

Step A1: Enumerate all RT DL items and find the 2 active ones:
  python3 -c "
  import xmlrpc.client
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  items = s.d.multicall2('', 'DL',
    'd.hash=', 'd.name=', 'd.state=', 'd.is_active=',
    'd.bytes_done=', 'd.size_bytes=', 'd.peers_complete=',
    'd.label=')
  for i in items:
    h, name, state, active, done, size, seeds, label = i
    pct = done/size*100 if size > 0 else 0
    print(f'{h[:8]}  active={active}  {pct:.1f}%  seeds={seeds}  [{label}]  {name[:60]}')
  "

Report the full list. Identify the 2 with active=1.

## Part B: Local Data Investigation for 10 Remaining RT DL Items

For EACH item below, follow this procedure:

  1. Get file list via XMLRPC (f.multicall as above)
  2. For each file in the torrent: search all 3 DB tables for that filename at full size
  3. Report findings: found_at, size, nlinks estimate
  4. If ALL files found at full size on same filesystem → proceed to repair (Part D)
  5. If PARTIALLY found → report which files are missing
  6. If NONE found → confirm as data-absent

### Item 1: River Monsters S07
  hash=127c3838342cfedaf4016b8079be13c5f7883b9cfe
  name=River Monsters S07 1080p AMZN WEB-DL DDP2 0 H 264-NTb
  rt_state=stalledDL  rt_progress=99.9%  bytes_missing=16777216 (16MB = ~1 piece)
  rt_label=torrentday  rt_directory=/data/media/torrents/seeding/TorrentDay/River Monsters S07...
  tracker=torrentday  seeds=0  nlinks_sample=12

### Item 2: Dexter S02
  hash=245f2bce6afaf96b0a48ad216366c4281fdd864f
  name=Dexter.S02.720p.x265-ZMNT
  rt_state=stalledDL  rt_progress=~100%  bytes_missing=2097152 (2MB = 1 piece)
  rt_label=speedcc  rt_directory=/data/media/torrents/seeding/TorrentLeech/Dexter.S02...
  tracker=speedcd  seeds=0  nlinks_sample=3

### Item 3: Dexter S07
  hash=e36553b12dc118d8c52575a1d6711532882ae1c3
  name=Dexter.S07.720p.x265-ZMNT
  rt_state=stalledDL  rt_progress=~100%  bytes_missing=2097152 (2MB = 1 piece)
  rt_label=speedcc  rt_directory=/pool/media/torrents/seeding/speedcd/Dexter.S07...
  tracker=speedcd  seeds=0  nlinks_sample=1

### Item 4: Transformers Rise of the Beasts
  hash=96d896ca35f42d93e4a4bdee92e8ac90adc34b54
  name=Transformers.Rise.of.the.Beasts.2023.1080p.BluRay.x265.10bit.TrueHD.7.1.Atmos-TORRENTLEECHENC0DE
  rt_state=stalledDL  rt_progress=~100%  bytes_missing=1959802 (2MB = 1 piece)
  rt_label=digitalcore  rt_directory=/data/media/torrents/seeding/DigitalCore (API)/Transformers...
  tracker=digitalcore  seeds=0  nlinks_sample=4

### Item 5: Diary of a Teenage Girl
  hash=5caca88d29e64de495a47b53a466f7cadcb3ce02
  name=The.Diary.of.a.Teenage.Girl.2015.REMUX.1080p.BluRay.AVC.DTS-HD.MA.5.1-CDB
  rt_state=stalledDL  rt_progress=98.4%  bytes_missing=388062872 (388MB)
  rt_label=torrentleech  rt_directory=/data/media/torrents/seeding/TorrentLeech/The.Diary...
  tracker=torrentleech  seeds=0  nlinks_sample=3

### Item 6: NOVA S50
  hash=2d4016de430ff7348872a5f328245a667b3f3360
  name=NOVA.S50.1080p.x265-ELiTE
  rt_state=stalledDL  rt_progress=0%  bytes_done=0  bytes_missing=17969434946
  rt_label=cross-seed  rt_directory=/pool/media/torrents/seeding/DigitalCore (API)/NOVA.S50...
  tracker=speedcd  seeds=0  data_on_disk=yes  nlinks_sample=1
  Note: data_on_disk=yes but 0% — likely same pattern as Greenland/How.Its.Made.
        The directory exists but files may be at a different path than RT expects.

### Item 7: Hunter's Code Book 4
  hash=6b6043cacaada917da6d05cc551765f4530ca55a
  name=Hunter's Code Book 4
  rt_state=stoppedDL  rt_progress=0%  bytes_missing=550477747 (550MB)
  rt_label=cross-seed  rt_directory=/data/media/torrents/seeding/abtorrents/Hunter's Code Book 4
  tracker=myanonamouse  seeds=0  data_on_disk=no

### Item 8: The Conjuring
  hash=282ec595d866745c115d5a418c028a2bb939f603
  name=The.Conjuring.2013.1080p.Blu-Ray.ReMuX.AVC.DTS-HDMA.5.1-R2D2.mkv
  rt_state=stoppedDL  rt_progress=0%  bytes_missing=23787379307 (23.8GB)
  rt_label=cross-seed  rt_directory=/data/media/torrents/seeding/movies/The.Conjuring...
  tracker=onlyencodes  seeds=0  data_on_disk=no

### Item 9: Magic City S01
  hash=f0bc85eedb5050da831a3c54a509d8f90a1fac2f
  name=Magic.City.S01.1080p.BluRay.REMUX.AVC.TrueHD.5.1-PrivateHD
  rt_state=pausedDL  rt_progress=0%  bytes_missing=106474639951 (106GB)
  rt_label=yuscene  rt_directory=/pool/media/torrents/seeding/other/Magic.City.S01...
  tracker=yuscene  seeds=0  data_on_disk=no

### Item 10: Smart Brevity
  hash=815e28c8cce2ef07ace15529485442046f39fffa
  name=Jim VandeHei and Mike Allen Roy Schwartz - Smart Brevity (2022)
  rt_state=stoppedDL  rt_progress=0%  bytes_missing=177613878 (178MB)
  rt_label=abtorrents  rt_directory=/data/media/torrents/seeding/MaM/Jim VandeHei...
  tracker=myanonamouse  seeds=0  data_on_disk=no

## Part C: qB stoppedDL:32 Cleanup

Dashboard shows 32 qB stoppedDL. We expect only 12 (matching RT-incomplete items).
The excess ~20 are items where RT is now seeding but qB still has stale stoppedDL state.

Step C1: Get all qB stoppedDL items:
  python3 -c "
  import json
  data = json.load(open(os.path.expanduser('~/.cache/silo-qb/torrents-info.json')))
  stopped_dl = [t for t in data if t.get('state','').lower() in ('stoppeddl','pauseddl')]
  for t in stopped_dl:
    print(t['hash'][:8], t.get('state'), t.get('name','')[:60])
  print(f'Total: {len(stopped_dl)}')
  " 2>/dev/null
  # Or directly:
  python3 -c "
  import json, os
  data = json.load(open(os.path.expanduser('~/.cache/silo-qb/torrents-info.json')))
  stopped_dl = [(t['hash'], t.get('state'), t.get('name','')) for t in data
                if t.get('state','').lower() in ('stoppeddl','pauseddl','checkingdl')]
  for h,s,n in stopped_dl:
    print(f'{h[:8]}  {s}  {n[:60]}')
  print(f'Total: {len(stopped_dl)}')
  "

Step C2: For each qB stoppedDL hash, check RT state:
  python3 -c "
  import xmlrpc.client, json, os
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  data = json.load(open(os.path.expanduser('~/.cache/silo-qb/torrents-info.json')))
  stopped_dl = [(t['hash'], t.get('name','')) for t in data
                if t.get('state','').lower() in ('stoppeddl','pauseddl')]
  print('hash      qb_state   rt_state   rt_pct   name')
  for h, name in stopped_dl:
    try:
      rt_state = s.d.state(h)
      rt_done = s.d.bytes_done(h)
      rt_size = s.d.size_bytes(h)
      rt_pct = rt_done/rt_size*100 if rt_size > 0 else 0
      print(f'{h[:8]}  stoppedDL  {rt_state:<12} {rt_pct:.1f}%  {name[:50]}')
    except:
      print(f'{h[:8]}  stoppedDL  RT_NOT_FOUND       {name[:50]}')
  "

Step C3: For each qB stoppedDL where RT state is stalledUP/uploading (RT complete):
  → qB recheck: curl -s -X POST http://localhost:9003/api/v2/torrents/recheck
                  --data 'hashes=<hash>'
  → After recheck completes (~30s), qB should auto-stop (it's passive).
  → Verify: qB state should become stoppedUP.
  → If qB doesn't auto-stop after recheck: manually stop it.

## Part D: Repair Procedure (for items where data IS found in Step B)

For each item where data is confirmed found at full size:

  1. For multi-file torrents — hardlink each missing/partial file:
     For each file in torrent:
       if file not at RT path OR file at RT path has nlinks=1 (partial download):
         SOURCE=$(find all DB hits for that filename at full size)
         ln -f '<source_path>' '<rt_directory>/<file_path>'

  2. Repoint RT if directory changed:
     python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/');
       s.d.set_directory('<hash>', '<correct_dir>'); print('repointed')"

  3. Recheck:
     python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/');
       s.d.check_hash('<hash>'); s.d.start('<hash>'); print('recheck+start issued')"

  4. Verify after 60s:
     python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/');
       print(s.d.state('<hash>'), s.d.bytes_done('<hash>')/s.d.size_bytes('<hash>')*100)"

  Expected outcome: state=1 (active), progress=100%, should be seeding.

## Part E: Update Policy Doc

After investigation, update docs/RT-QB-STATE-POLICY.md §8.1 with confirmed
residual items (data absent, seeds absent — genuinely unresolvable for now).

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
🟦 task-brief=J03-T11_rt-dl-data-investigation 🟦

id=J03-T11
role=agent
task_type=implementation
goal=For all remaining RT DL items: search hashall DB for payload data on disk.
     If found: hardlink to canonical path, repoint RT, recheck, verify seeding.
     Also identify 2 unknown active DL items. Fix qB stoppedDL:32 excess by
     rechecking items where RT is now seeding. Update §8.1 with confirmed residuals.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=files+commits

allowed_commands=
- sqlite3 ~/.hashall/catalog.db "<query>" (read-only)
- python3 -c "import xmlrpc.client; ..." (d.multicall2, f.multicall, d.state,
  d.bytes_done, d.size_bytes, d.check_hash, d.start, d.set_directory)
- python3 -c "import json, os; ..." (read qB/RT cache files)
- find /data/media /pool/media /stash/media -name "<pattern>" (read-only fallback)
- stat --format=... (read-only)
- ls -la (read-only)
- mkdir -p (canonical dirs only)
- ln -f (hardlink only — NEVER cp or mv)
- rmdir (empty dirs only — NEVER rm -rf)
- curl -X POST http://localhost:9003/api/v2/torrents/recheck (qB recheck)
- curl -X POST http://localhost:9003/api/v2/torrents/stop (qB stop)
- git branch --show-current
- tmux send-keys -t %14 "<summary>" Enter

forbidden_commands=
- rm -rf (never)
- mv (never move data files)
- cp (never copy — hardlink only)
- Any action on tracker_issue items (Section D from T08) — those are seeding fine
- hashall / rehome mutation commands
- docker stop / docker restart

required_artifacts=

PART A: Unknown active DL items
  List all RT DL items with active=1. Identify the 2 unknowns.
  For each: hash, name, state, progress, label, tracker.

PART B: Per-item investigation results (10 items)
  For each item:
    hash=
    name=
    files_in_torrent=       (count from f.multicall)
    db_search_results=      (found/not_found per file, path, size)
    data_found=             (yes/partial/no)
    found_at=               (path(s) or N/A)
    repair_action=          (hardlinked+repointed+rechecked / no_data_confirmed / partial)
    post_repair_state=      (RT state after repair, or N/A)
    outcome=                (resolved/residual/partial)

PART C: qB stoppedDL cleanup
  total_qb_stoppeddl=
  rt_seeding_but_qb_stoppeddl=  (count where RT=stalledUP but qB=stoppedDL)
  qb_rechecked=
  qb_stopped_after_recheck=
  qb_stoppeddl_remaining=       (should = RT-incomplete count)

PART E: Policy doc update
  §8.1 updated with confirmed residual hashes (yes/no)

success_criteria=
- All 10 items investigated via hashall DB
- 2 unknown active DL items identified
- Any item with data found on disk: repaired and seeding
- qB stoppedDL count reduced to match RT-incomplete count (≤12)
- §8.1 updated with confirmed residual items

stop_if=
- RT XMLRPC unreachable
- hashall DB not found at ~/.hashall/catalog.db
- A target directory is NOT empty when attempting rmdir

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T11_rt-dl-data-investigation 🟦
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T11--rt-dl-data-investigation/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T11--rt-dl-data-investigation/TASK-LOG.md

3. Notify Lead:
   tmux send-keys -t %14 "🟪 J03-T11 done | resolved=<N> residual=<N> qb_fixed=<N>"
   tmux send-keys -t %14 "" Enter
