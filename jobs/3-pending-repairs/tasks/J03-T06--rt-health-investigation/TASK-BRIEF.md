---
id: J03-T06
job: 3-pending-repairs
slug: rt-health-investigation
task_type: discovery
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T06 — RT Health Investigation

## Context

RT is in an unhealthy state. Lead needs per-item data to make accurate repair
decisions. This is pure discovery — gather everything, mutate nothing.

Target state (from USER-NOTES.md):
  RT acceptable states: stoppedUP, stalledUP, uploading
  RT unacceptable:      stoppedDL, pausedDL, stalledDL (except 4 known zero-seed items)
                        downloading, checking (transient only)
  qB acceptable states: stoppedUP, stoppedDL (only if RT also incomplete), pausedDL (only if RT also incomplete)
  qB unacceptable:      uploading, stalledUP, forcedUP, error, downloading, pausedUP

Current RT status panel shows:
  DL:18  (active:1, stalled:6, paused:3, stopped:8)
  UL:4871 (active:0, idle:4868, stopped:3)
  tracker_issue:18 (deleted:11, auth_err:4, other:3)

Key rules:
  - Cross-seed items are ALWAYS hardlinked from existing data — they NEVER download
  - If a cross-seed item is actively downloading, its hardlink source is missing or moved
  - qB must NEVER actively upload (uploading/stalledUP in qB = wrong)

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
🟦 task-brief=J03-T06_rt-health-investigation 🟦

id=J03-T06
role=agent
task_type=discovery
goal=For every RT item in a DL state and every qB item in an uploading/stalledUP
     state, gather the complete set of data the Lead needs to make an accurate
     repair decision for each one. Also enumerate tracker issues. No mutations.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none

allowed_commands=
- cat ~/.cache/silo-rt/torrents.json | python3 -c "..."  (read-only)
- cat ~/.cache/silo-qb/torrents-info.json | python3 -c "..."  (read-only)
- python3 -c "import xmlrpc.client; s=xmlrpc.client.ServerProxy('http://127.0.0.1:18000/'); ..."
- stat <path>
- find <path> -maxdepth 2 -type f | head -5
- ls -la <path>
- find <path> -maxdepth 2 -type f -exec stat --format="%h %n" {} \; | head -5
- hashall qb fetch-cache
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 "" Enter

forbidden_commands=
- hashall qb pause / stop / remove (any mutation)
- hashall rt repoint / recheck (any mutation)
- rm, mv, rsync
- git add / git commit
- docker stop / docker restart
- Any --execute or --apply flag

required_artifacts=

SECTION 1 — RT DL ITEMS (18 expected)
For each item in stoppedDL, pausedDL, stalledDL, or downloading state in RT,
report ALL of the following:

  hash=
  name=
  state=            (downloading|stalledDL|pausedDL|stoppedDL)
  progress=         (0.0–1.0)
  size_bytes=
  directory=        (RT save path)
  label=            (RT label/category)
  tracker_url=      (from RT XMLRPC: d.tracker.url(hash))
  is_cross_seed=    (yes if category=cross-seed OR tracker_url matches known cross-seed pattern)
  data_on_disk=     (yes/no — does directory exist?)
  file_count=       (how many files in directory, 0 if missing)
  nlinks_sample=    (nlink count from stat on first file, or 0 if no files)
  qb_state=         (state from qB cache for same hash, or NOT_IN_QB)
  qb_save_path=     (qB save_path for same hash, or N/A)
  seeds_available=  (from RT XMLRPC: d.peers_complete(hash) — peer count)

SECTION 2 — qB BAD-STATE ITEMS
For each qB item in uploading, stalledUP, forcedUP, or queuedUP state:

  hash=
  name=
  qb_state=
  qb_save_path=
  qb_progress=
  rt_state=         (from RT cache for same hash, or NOT_IN_RT)

SECTION 3 — RT TRACKER ISSUES (18 expected)
For each RT item with tracker_issue (deleted, auth_err, other):

  hash=
  name=
  tracker_url=
  issue_type=       (deleted|auth_err|other)
  rt_state=
  rt_progress=

success_criteria=
- All 18 RT DL items enumerated with full per-item data
- All qB bad-state items enumerated
- All 18 tracker issue items enumerated
- tracker_url obtained for every item (via XMLRPC if not in cache)
- data_on_disk and nlinks_sample checked for every RT DL item
- seeds_available checked for every RT DL item in stalledDL state

stop_if=
- RT XMLRPC unreachable (cannot get tracker_url or seeds_available)
- qB cache stale > 1h (fetch fresh: hashall qb fetch-cache)
- RT cache stale > 1h

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T06_rt-health-investigation 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T06_rt-health-investigation 🟪

status="done|blocked"
task_id="J03-T06"
task_type="discovery"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="<one-line summary>"
artifacts="full per-item data below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

rt_dl_count=
qb_bad_state_count=
tracker_issue_count=

=== SECTION 1: RT DL ITEMS ===
<one block per item, all fields as specified above>

=== SECTION 2: qB BAD-STATE ITEMS ===
<one block per item>

=== SECTION 3: TRACKER ISSUES ===
<one block per item>

🟪 task-log=J03-T06_rt-health-investigation 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T06--rt-health-investigation/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T06--rt-health-investigation/TASK-LOG.md

3. Notify Lead (two sends):
   tmux send-keys -t %14 "🟪 J03-T06 done | rt_dl=<N> qb_bad=<N> tracker_issues=<N>"
   tmux send-keys -t %14 "" Enter
