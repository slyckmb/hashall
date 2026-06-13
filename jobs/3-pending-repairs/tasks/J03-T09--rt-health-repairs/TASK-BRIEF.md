---
id: J03-T09
job: 3-pending-repairs
slug: rt-health-repairs
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T09 — RT Health Repairs

## Context

J03-T08 produced the full enrichment matrix. Operator has approved the following
repair actions. This task executes them.

## Approved Actions

### Action 1: Start 3 RT stoppedUP items (policy: stoppedUP → start immediately)

Hashes:
  5c86280a99d1007104452b2f72d0d686e092e2f8  Spider-Man Into the Spider-Verse
  4adbb5a7e4d1011ff8286de67c92f2467e81df5b  V for Vendetta
  87b6670c265ea58f0e837443516c0504e0c2537c  E.T. The Extra-Terrestrial

Command per hash:
  python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); print(s.d.start('<hash>'))"

### Action 2: Stop 2 qB bad-state items (policy: qB must never be stalledUP)

Hashes:
  8c3e841e16a48bde86a33b11a492063ec911379a  Love and Monsters  (qB=stalledUP)
  4adbb5a7e4d1011ff8286de67c92f2467e81df5b  V for Vendetta     (qB=stalledUP, same hash as Action 1)

qB stop command:
  curl -s -X POST http://localhost:9003/api/v2/torrents/stop \
    --data 'hashes=<hash>'

Or python3:
  python3 -c "import requests; r=requests.post('http://localhost:9003/api/v2/torrents/stop', data={'hashes':'<hash>'}); print(r.status_code, r.text)"

### Action 3: Force recheck 5 cross-seed items at 0% with data on disk

These were added by cross-seed (hardlinks exist) but RT never verified. Recheck
will discover the data and flip them to stalledUP/seeding.

Hashes:
  04aa5f3339d3ccfd1f14dd114db16c92aa87f74a  How.Its.Made.S23  (pausedDL, dir=YUSCENE (API))
  4e4a7bc1f4284da8b20ce3663b5be1847664f61c  Greenland (seedpool)  (stoppedDL, dir=YUSCENE (API), nlinks=5)
  e3f92c1c1d8dcde7042f0f849d15d13c1a480d2a  Greenland (darkpeers) (stoppedDL, dir=YUSCENE (API), nlinks=5)
  002e5db0ad4bee86419ccf244d212f6d1150d1e8  How.Its.Made.S24  (pausedDL, dir=OnlyEncodes (API))
  73d05a65527a9044f924b0b119810fbf46ff3081  Greenland (reelflix)  (stoppedDL, dir=YUSCENE (API), nlinks=5)

Command per hash:
  python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); print(s.d.check_hash('<hash>'))"

After all 5 rechecks are issued, wait 30 seconds, then verify each hash state:
  python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); print(s.d.get_state('<hash>'))"

### Action 4: Stop cross-seed violation

  145548eb360d03ffa6343f56ee94ba8ca7ea8f1c  How.Its.Made.S22 (downloading 47%, cross-seed violation)

Command:
  python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); print(s.d.stop('145548eb360d03ffa6343f56ee94ba8ca7ea8f1c'))"

### Action 5: Remove 2 empty-dir Class 4 items

These are in _rehome-unique/ with empty directories and zero data. Remove from
both clients and delete the empty directories.

Items:
  8e438130b072708877003225a5079040991de5d7  Muppet Christmas Carol
    RT dir: /pool/media/torrents/seeding/_rehome-unique/8e438130b0727088
    qB save: /pool/media/torrents/seeding/_rehome-unique/8e438130b0727088

  ef48a9203545aa798775fba7e9a3e7ca396032fe  Fly Me To The Moon
    RT dir: /data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79
    qB save: /data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79

Steps per item:
  1. Verify directory is actually empty: ls -la '<dir>'
  2. Remove from RT: python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); print(s.d.erase('<hash>'))"
  3. Remove from qB: curl -s -X POST http://localhost:9003/api/v2/torrents/delete --data 'hashes=<hash>&deleteFiles=false'
  4. Delete empty dir: rmdir '<dir>'

## No-Action Items (do NOT touch these)

stalledDL with 0 seeds (LEAVE):
  127c3834  River Monsters S07     (99.9%, 16MB remaining)
  245f2bce  Dexter S02             (~100%, 2MB remaining)
  e36553b1  Dexter S07             (~100%, 2MB remaining)
  96d896ca  Transformers.Rise      (~100%, 2MB remaining)
  5caca88d  Diary Teenage Girl     (98.4%)
  2d4016de  NOVA.S50               (0%, data present, stalledDL)

No data, stopped, 0 seeds (LEAVE — no action possible without seeds):
  6b6043ca  Hunter's Code Book 4
  282ec595  The Conjuring
  f0bc85ee  Magic City S01
  815e28c8  Smart Brevity

Tracker issues (LEAVE — RT already seeding at stalledUP, no state change needed):
  All 18 items in Section D of T08 log

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
🟦 task-brief=J03-T09_rt-health-repairs 🟦

id=J03-T09
role=agent
task_type=implementation
goal=Execute 5 approved repair actions to get RT healthy: start 3 stoppedUP items,
     stop 2 qB bad-state items, recheck 5 cross-seed items at 0% with data on disk,
     stop the cross-seed downloading violation, remove 2 empty-dir Class 4 items.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=files+commits

allowed_commands=
- python3 -c "import xmlrpc.client; ..." (d.start, d.stop, d.check_hash, d.get_state, d.erase)
- curl -X POST http://localhost:9003/api/v2/torrents/stop (qB stop)
- curl -X POST http://localhost:9003/api/v2/torrents/delete (qB remove, deleteFiles=false only)
- ls -la <dir> (verify empty before rmdir)
- rmdir <dir> (empty dirs only, never rm -rf)
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>" Enter

forbidden_commands=
- rm -rf (never)
- hashall / rehome mutation commands
- Any action on no-action items (stalledDL 0-seeds, no-data stopped, tracker issues)
- docker stop / docker restart

required_artifacts=
For each action group, report:
  action=<start|stop|recheck|remove>
  hash=<hash>
  name=<name>
  before_state=<state before action>
  command_issued=<exact command run>
  result=<command output>
  after_state=<state after verification>
  outcome=<ok|failed|unexpected>

success_criteria=
- Action 1: all 3 stoppedUP items started (verify state changed to stalledUP or uploading)
- Action 2: both qB items stopped (verify qB state = stoppedUP)
- Action 3: all 5 rechecks issued, post-wait states reported
- Action 4: cross-seed violation stopped
- Action 5: both empty-dir items removed from RT, removed from qB, dirs deleted
- No no-action items touched

stop_if=
- RT XMLRPC unreachable
- qB API unreachable
- Directory not empty when attempting rmdir (report, do not proceed with rm)
- Any unexpected state before action (report, skip that item)

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T09_rt-health-repairs 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T09_rt-health-repairs 🟪

status="done|partial|blocked"
task_id="J03-T09"
task_type="implementation"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none (XMLRPC/API mutations only)"
mutations="RT: d.start x3, d.stop x1, d.check_hash x5, d.erase x2 | qB: stop x2, delete x2"
validation="<post-action state verification>"
artifacts="action results below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

=== ACTION 1: RT stoppedUP STARTS ===
<one block per hash>

=== ACTION 2: qB STOPS ===
<one block per hash>

=== ACTION 3: CROSS-SEED RECHECKS ===
<one block per hash, including post-wait states>

=== ACTION 4: CROSS-SEED VIOLATION STOP ===
<one block>

=== ACTION 5: EMPTY-DIR REMOVALS ===
<one block per hash>

🟪 task-log=J03-T09_rt-health-repairs 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T09--rt-health-repairs/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T09--rt-health-repairs/TASK-LOG.md

3. Notify Lead:
   tmux send-keys -t %14 "🟪 J03-T09 done | starts=3 qb_stops=2 rechecks=5 violation_stopped=1 removed=2"
   tmux send-keys -t %14 "" Enter
