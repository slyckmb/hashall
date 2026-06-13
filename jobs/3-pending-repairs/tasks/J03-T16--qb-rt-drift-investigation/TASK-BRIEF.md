---
id: J03-T16
job: 3-pending-repairs
slug: qb-rt-drift-investigation
task_type: discovery
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-13
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T16 — qB/RT Drift Investigation

## Context

The operator sees qty=1 drift between qB and RT totals. The sync mechanism
is the `rt-qb-mirror-queue` — RT fires a hook when a torrent completes, which
enqueues the hash. Running `make rt-qb-mirror-queue-apply` processes the queue
and mirrors each seeding RT item into qB.

Current known state:
  RT total: 4883 items
  qB total: 4882 items
  RT-only (in RT not qB): 1 item — 406ff76c (Euphoria S03 1080p pack, recently added, still downloading)
  qB-only (in qB not RT): 0 items

The mirror queue has 4918 entries (far more than current RT/qB counts).

## Investigation Questions

### Q1: Is the queue backlogged with unprocessed items?

Check if the queue contains hashes that are in RT but not in qB:
  python3 -c "
  import json, os, xmlrpc.client
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  QUEUE_DIR = '/dump/docker/gluetun_qbit/rtorrent_vpn/rt-qb-mirror-queue'
  # Get all queue hashes
  queue_hashes = {f.replace('.json','').lower() for f in os.listdir(QUEUE_DIR) if f.endswith('.json')}
  # Get RT hashes
  rt_items = s.d.multicall2('', 'main', 'd.hash=', 'd.name=', 'd.complete=', 'd.state=')
  rt_hashes = {i[0].lower(): (i[1], i[2], i[3]) for i in rt_items}
  # Get qB hashes
  data = json.load(open(os.path.expanduser('~/.cache/silo-qb/torrents-info.json')))
  qb_hashes = {t['hash'].lower() for t in data}
  # Items in queue + RT but NOT in qB (should be synced)
  pending = [(h, rt_hashes[h]) for h in queue_hashes if h in rt_hashes and h not in qb_hashes]
  print(f'Queue size: {len(queue_hashes)}')
  print(f'RT size: {len(rt_hashes)}')
  print(f'qB size: {len(qb_hashes)}')
  print(f'In queue+RT but NOT qB (pending sync): {len(pending)}')
  for h, (name, complete, state) in pending[:10]:
    print(f'  {h[:8]}  complete={complete} state={state}  {name[:50]}')
  if len(pending) > 10:
    print(f'  ... and {len(pending)-10} more')
  # Items in queue but NOT in RT (removed from RT after queueing)
  queue_not_rt = queue_hashes - set(rt_hashes.keys())
  print(f'In queue but removed from RT (historical): {len(queue_not_rt)}')
  "

### Q2: Is the mirror queue stale (large backlog of already-processed items)?

Check queue entry timestamps:
  python3 -c "
  import json, os, time
  QUEUE_DIR = '/dump/docker/gluetun_qbit/rtorrent_vpn/rt-qb-mirror-queue'
  entries = []
  for f in os.listdir(QUEUE_DIR):
    if f.endswith('.json'):
      try:
        d = json.load(open(os.path.join(QUEUE_DIR, f)))
        entries.append(d)
      except: pass
  entries.sort(key=lambda x: x.get('last_seen', 0), reverse=True)
  now = time.time()
  print(f'Total entries: {len(entries)}')
  print('Most recent 5:')
  for e in entries[:5]:
    age = (now - e.get('last_seen', 0)) / 3600
    print(f'  {e[\"hash\"][:8]}  last_seen={age:.1f}h ago  source={e.get(\"source\",\"?\")}')
  print('Oldest 5:')
  for e in entries[-5:]:
    age = (now - e.get('last_seen', 0)) / 3600
    print(f'  {e[\"hash\"][:8]}  last_seen={age:.1f}h ago  source={e.get(\"source\",\"?\")}')
  "

### Q3: What does make rt-qb-mirror-queue-apply do and when was it last run?

  # Check the make target
  cd /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
  grep -A5 "rt-qb-mirror-queue-apply" Makefile

  # Check if there's a log or last-run indicator
  find /dump/docker/gluetun_qbit/rtorrent_vpn -name "*.log" -newer /dump/docker/gluetun_qbit/rtorrent_vpn/rt-qb-mirror-queue/ 2>/dev/null | head -5

### Q4: Is the 1 drift item (Euphoria pack) expected to self-resolve?

  python3 -c "
  import xmlrpc.client
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  h = '406ff76c'
  items = s.d.multicall2('', 'main', 'd.hash=', 'd.name=', 'd.state=', 'd.complete=', 'd.bytes_done=', 'd.size_bytes=')
  pack = [i for i in items if '406ff76c' in i[0].lower()]
  for i in pack:
    h, name, state, complete, done, size = i
    pct = done/size*100 if size > 0 else 0
    print(f'{h[:8]}  state={state} complete={complete} {pct:.1f}%  {name[:60]}')
  "
  This item will self-resolve: when it finishes downloading, the RT completion hook
  fires and enqueues it. Running rt-qb-mirror-queue-apply then adds it to qB.

### Q5: Are there any OTHER items that should be in qB but aren't?

Check if there are RT seeding items that have no qB counterpart (beyond the Euphoria pack):
  python3 -c "
  import json, os, xmlrpc.client
  s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
  rt_seeding = s.d.multicall2('', 'seeding', 'd.hash=', 'd.name=')
  data = json.load(open(os.path.expanduser('~/.cache/silo-qb/torrents-info.json')))
  qb_hashes = {t['hash'].lower() for t in data}
  missing = [(h.lower(), name) for h, name in rt_seeding if h.lower() not in qb_hashes]
  print(f'RT seeding but not in qB: {len(missing)}')
  for h, name in missing[:10]:
    print(f'  {h[:8]}  {name[:60]}')
  "

## Bootstrap Context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
```

## Brief

```
🟦 task-brief=J03-T16_qb-rt-drift-investigation 🟦

id=J03-T16
role=agent
task_type=discovery
goal=Investigate the qB/RT inventory drift. Answer: Is the sync tooling
     (rt-qb-mirror-queue) healthy? Is the 1-item drift expected and self-resolving?
     Are there any other RT seeding items missing from qB? What is the queue
     processing state?

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=current
allowed_mutation=none

allowed_commands=
- python3 -c "import json, os, xmlrpc.client; ..." (read-only inventory checks)
- cat / ls / find on queue dir (read-only)
- grep Makefile (read-only)
- git branch --show-current
- tmux send-keys -t %14 "<summary>" Enter

forbidden_commands=
- make rt-qb-mirror-queue-apply (do NOT run without operator approval — may modify qB)
- Any write, edit, or mutation command
- git add / git commit

required_artifacts=
  queue_size=
  queue_backlog_pending_items=   (in queue+RT but not qB, excluding expected downloads)
  queue_historical_items=        (in queue but removed from RT — just a count)
  rt_seeding_not_in_qb=         (count + list)
  drift_item_status=             (Euphoria pack: current state, expected resolution)
  sync_mechanism_health=         (healthy/degraded/broken — with reasoning)
  recommended_action=            (none/run-queue-apply/investigate-further)

success_criteria=
- All 5 investigation questions answered
- Clear verdict on sync health
- Recommended next action stated

final_output_required=true
worktree_mirror_required=false

🟦 task-brief=J03-T16_qb-rt-drift-investigation 🟦
```

## After completing this task

1. Write TASK-LOG.md to:
   .../tasks/J03-T16--qb-rt-drift-investigation/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T16--qb-rt-drift-investigation/TASK-LOG.md

3. Notify Lead:
   tmux send-keys -t %14 "🟪 J03-T16 done | drift=<N> sync_health=<healthy|degraded|broken> action=<none|run-queue-apply>"
   tmux send-keys -t %14 "" Enter
