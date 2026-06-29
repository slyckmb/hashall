🟦 task-brief=j47-t05_gate3-pilot 🟦
id=j47-t05
role=agent
task_type=verification
goal=Gate 3: execute a single fix_path_only item live; record exact pre/post RT+qB state; wait 60s and re-check for spontaneous transitions; write docs/CANONICALIZE-GATE3-PILOT.md; PASS required before Gate 4
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j47
expected_branch=cr/hashall-20260626-151456__j47
expected_head=set_at_dispatch
allowed_mutation=files-only
allowed_commands=grep,find,cat,head,tail,python3,pip show,git log,git status,wc,ls,hashall
forbidden_commands=git commit,git push,pip install,opencode,chatrap job,rm -rf,make
success_criteria=
  - Gate 2 manifest (docs/CANONICALIZE-REPAIR-MANIFEST.md) confirmed PASS before proceeding — if FAIL, emit status=blocked
  - Exactly 1 fix_path_only item selected from the manifest (smallest payload, single-file or small multi-file preferred)
  - Pre-state fully recorded: RT d.directory, qB save_path, qB state, RT complete, RT down_rate
  - `hashall canonicalize-apply <hash> --force` executed with output captured
  - Post-state recorded immediately: same fields as pre-state
  - 60-second wait, then re-check state — no spontaneous transitions
  - PASS criteria all confirmed (see below) OR immediate abort with FAIL report
  - `docs/CANONICALIZE-GATE3-PILOT.md` written with full evidence
  - task-log emitted with status=done (even on FAIL — report the failure clearly)
final_output_required=true
worktree_mirror_required=false
brief_hash="none"
agent_start_timestamp="set by agent at start — brief frozen after"
brief_freeze_violation="false"
🟦 task-brief=j47-t05_gate3-pilot 🟦

---

## Context

Read `docs/4-GATE-MUTATION-PROTOCOL.md` for the full Gate 3 definition and abort conditions.
Read `docs/CANONICALIZE-REPAIR-MANIFEST.md` — must show Gate 2 PASS before proceeding.

This is a LIVE MUTATION task. The `--force` flag is authorized for exactly 1 item.

## Item Selection

From `docs/CANONICALIZE-REPAIR-MANIFEST.md`, select the single safest fix_path_only item:
- plan_type MUST be fix_path_only (no data movement)
- Prefer single-file payload over multi-file
- Prefer smallest payload by disk size
- Must NOT be in any staging dir
- Must NOT have external consumers (would be plan_type=blocked if detected correctly)
- Record the selected hash and rationale in the pilot doc

## Pre-State Capture

Before executing, capture and record:
```bash
# RT state for this torrent
hashall payload info <hash> 2>/dev/null
# qB state for this torrent  
hashall payload status --hash <hash> 2>/dev/null
```

Record: RT d.directory, qB save_path, qB state (must be stoppedUP), RT complete (must be 1), RT down_rate (must be 0).

If qB state is NOT stoppedUP before execution: abort. Do not execute on a torrent that is actively downloading or in an unknown state.

## Execution

```bash
hashall canonicalize-apply <hash> --force 2>&1 | tee /tmp/j47-t05-pilot-execute.log
```

Capture full output. Check exit code.

## Immediate Post-State Check

Immediately after execution:
```bash
hashall payload info <hash> 2>/dev/null
hashall payload status --hash <hash> 2>/dev/null
```

Also check overall state summary for any new stoppedDL:
```bash
hashall payload status --state-summary 2>/dev/null
```

## 60-Second Re-Check

```bash
sleep 60
hashall payload info <hash> 2>/dev/null
hashall payload status --state-summary 2>/dev/null
```

## Pass Criteria (ALL must be true)

1. qB state after execution: `stoppedUP` (not stoppedDL, not checkingUP, not stalledUP)
2. RT d.directory after execution: matches canonical_path from RepairPlan
3. qB save_path after execution: matches canonical_seeding_root from RepairPlan
4. RT complete=1, down_rate=0 (still seeding)
5. Overall stoppedDL count: unchanged from Gate 1 baseline
6. Overall stalledUP count: 0
7. Overall checkingUP count: 0
8. 60s re-check: all of the above still true (no spontaneous transition)

## Abort Criteria (ANY triggers immediate stop)

- qB transitions to stoppedDL after execution → ABORT
- RT or qB repoint returns error → ABORT (check if rename was partially applied)
- stalledUP count increases → ABORT
- checkingUP count > 0 → ABORT (do NOT mass-pause — let complete naturally, then report)
- Execution exit code non-zero → ABORT

On abort:
1. Record exact state in pilot doc
2. Do NOT attempt to fix or retry
3. Do NOT mass-pause any torrents
4. Emit task-log with status=done, FAIL verdict in pilot doc
5. Lead will diagnose and escalate

## Output: docs/CANONICALIZE-GATE3-PILOT.md

```markdown
# Gate 3 Pilot Report
Date: <timestamp>
Agent: j47-t05
Selected hash: <hash>
Selection rationale: <why this item>
plan_type: fix_path_only

## Pre-State
| Field | Value |
|-------|-------|
| RT d.directory | <path> |
| qB save_path | <path> |
| qB state | stoppedUP |
| RT complete | 1 |
| RT down_rate | 0 |
| Global stoppedDL | N |
| Global stalledUP | 0 |
| Global checkingUP | 0 |

## Execution
Command: `hashall canonicalize-apply <hash> --force`
Exit code: N
Output:
<captured output>

## Post-State (immediate)
<same fields as pre-state>

## Post-State (60s re-check)
<same fields as pre-state>

## Pass Criteria Check
| Criterion | Value | Verdict |
|-----------|-------|---------|
| qB state = stoppedUP | <value> | ✅/❌ |
| RT directory = canonical | <value> | ✅/❌ |
| qB save_path = canonical seeding root | <value> | ✅/❌ |
| RT complete=1, down_rate=0 | <value> | ✅/❌ |
| stoppedDL unchanged | <value> | ✅/❌ |
| stalledUP=0 | <value> | ✅/❌ |
| checkingUP=0 | <value> | ✅/❌ |
| 60s re-check stable | <value> | ✅/❌ |

## Gate 3 Verdict: PASS / FAIL

<If PASS: ready for Gate 4 dispatch by lead after operator review>
<If FAIL: exact failure description, abort actions taken, do not proceed>
```
