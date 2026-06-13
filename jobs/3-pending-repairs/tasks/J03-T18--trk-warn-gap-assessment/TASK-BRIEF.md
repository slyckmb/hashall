---
id: J03-T18
job: 3-pending-repairs
slug: trk-warn-gap-assessment
task_type: discovery
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-13
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T18 — trk-warn vs rt-status gap assessment

## Problem

rt-status panel shows 6 tracker issues (4 auth_err, 1 deleted, 1 other).
`make trk-warn` shows only 2 (1 deleted, 1 auth_err).

Root cause is already identified by lead: the two tools use different filters.

**rt-cache-summary.py** (rt-status source) counts tracker issues for items in states:
  `error`, `stalledUP`, `uploading`, `stoppedUP`
  — no `complete=1` check; uses `d.message` directly from cache

**rt-tracker-manual-report.py** (trk-warn source) only processes items where:
  `d.complete == 1`  AND  message matches a BUCKET_PATTERNS regex

This means items with tracker errors that are NOT `complete=1` are counted by rt-status
but silently dropped by trk-warn. The new `--include-incomplete` flag (T17) was intended
to address this — but it may not be fully wired up yet, or the state filter differs.

## Task scope

1. **Identify the 4 hidden items** — find the specific hashes/names that rt-status counts
   but trk-warn doesn't show. Confirm their `complete` value and `state`.

2. **Confirm the state filter gap** — verify that `rt-cache-summary.py` includes `stoppedUP`
   in its tracker issue counting, but `rt-tracker-manual-report.py` does NOT include `stoppedUP`
   items (because they may have `complete=0`).

3. **Verify `--include-incomplete` covers the gap** — run trk-warn with `--include-incomplete`
   and confirm the 4 missing items now appear.

4. **If --include-incomplete does NOT cover them** — identify why and report the exact fix needed
   in trk-warn's filter logic.

5. **Check bucket alignment** — rt-status shows 1 `other`. trk-warn shows 0 `other`.
   Identify that item and why it's missing from trk-warn output.

## Investigation commands

### Step 1: Get the full RT tracker-issue inventory from rt-cache-summary

```bash
python3 ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-cache-summary.py --json 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('tracker_issue_by_kind',{}), indent=2))"
```

Or read the cached summary file directly:
```bash
cat ~/.cache/silo-rt/summary.json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('tracker_issue_total:', d.get('tracker_issue_total'))
print('by_kind:', d.get('tracker_issue_by_kind'))
"
```

### Step 2: Find items with tracker messages regardless of complete status

```bash
python3 -c "
import xmlrpc.client, re
s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
rows = s.d.multicall2('', 'main', 'd.hash=', 'd.name=', 'd.complete=', 'd.message=', 'd.state=')
for h, name, complete, msg, state in rows:
    if msg and msg.strip():
        print(f'hash={h[:8]} complete={complete} state={state}')
        print(f'  msg={msg[:100]}')
        print(f'  name={name[:60]}')
        print()
" 2>&1
```

### Step 3: Run trk-warn with --include-incomplete and compare

```bash
python3 ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py \
  --include-incomplete 2>&1
```

Compare against the standard run:
```bash
python3 ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py 2>&1
```

### Step 4: Check state filter in rt-tracker-manual-report.py

Read lines around `build_rows()` in the script, specifically:
- The `complete` check condition
- Whether `stoppedUP` items with `complete=0` are handled

File: `~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py`

## Required artifacts

```
rt_status_count=6   (from panel)
trk_warn_count=2    (from make trk-warn)
gap=4               (items counted by rt-status but not trk-warn)

hidden_items=
  - hash= complete= state= bucket= message=
  - (one line per hidden item)

gap_cause=
  (explain the exact filter difference)

include_incomplete_fixes_gap=yes/no/partial
  (run --include-incomplete and check if count rises to 6)

remaining_fix_needed=
  (if --include-incomplete doesn't fully fix: describe exact code change needed)
```

## Success criteria

- All 6 rt-status tracker issues identified by hash
- All 4 hidden items explained (complete=0? wrong state? message not matching BUCKET_PATTERNS?)
- Clear verdict on whether T17's --include-incomplete is sufficient or a follow-up fix is needed
- No mutations — discovery only

## Bootstrap context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
```

## Brief

```
🟦 task-brief=J03-T18_trk-warn-gap-assessment 🟦

id=J03-T18
role=agent
task_type=discovery
goal=Identify the 4 tracker-issue items that rt-status counts but make trk-warn
     does not show. Confirm the exact filter gap (complete=1 vs state-based).
     Verify whether --include-incomplete (T17) covers the gap or a further fix is needed.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=current
allowed_mutation=none

allowed_commands=
- python3 -c "..." (read-only RT API queries)
- python3 rt-tracker-manual-report.py (read-only, no --cleanup)
- python3 rt-cache-summary.py --json (read-only)
- cat ~/.cache/silo-rt/summary.json
- Read file (rt-tracker-manual-report.py, rt-cache-summary.py)
- git branch --show-current

forbidden_commands=
- make trk-warn-cleanup / --cleanup / --repair (destructive)
- Any write or commit

required_artifacts=
  rt_status_count=6
  trk_warn_count=
  gap=
  hidden_items=
  gap_cause=
  include_incomplete_fixes_gap=yes/no/partial
  remaining_fix_needed=

success_criteria=
- All 6 rt-status tracker issues identified by hash+name+state+complete
- Gap cause confirmed
- --include-incomplete verdict delivered
- No mutations

stop_if=
- RT API unavailable

final_output_required=true
worktree_mirror_required=false

🟦 task-brief=J03-T18_trk-warn-gap-assessment 🟦
```

## After completing this task

1. Write TASK-LOG.md to this directory.
2. Notify Lead:
   `tmux send-keys -t %14 "🟪 J03-T18 done | gap=<N> cause=<brief> include_incomplete=<yes/no/partial>" Enter`
