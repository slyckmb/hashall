🟦 task-brief=j47-t03_gate0-gate1-preflight 🟦
id=j47-t03
role=agent
task_type=verification
goal=Run Gate 0 (stoppedDL baseline audit) and Gate 1 (pre-flight checklist) per docs/4-GATE-MUTATION-PROTOCOL.md; write docs/CANONICALIZE-PREFLIGHT.md; PASS required before Gate 2 brief is dispatched
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j47
expected_branch=cr/hashall-20260626-151456__j47
expected_head=set_at_dispatch
allowed_mutation=files-only
allowed_commands=grep,find,cat,head,tail,python3,pip show,git log,git status,git worktree list,wc,ls,pytest,hashall
forbidden_commands=git commit,git push,pip install,opencode,chatrap job,rm -rf,make,hashall canonicalize-apply
success_criteria=
  - Gate 0 stoppedDL audit complete: count, classify (HEALTHY/MISSING_DATA/RT_INCOMPLETE), compare to known baseline (≤6 pre-existing)
  - Gate 1 editable install check: pth file confirmed pointing to CR worktree (not a __jNN worktree)
  - Gate 1 orphan worktree check: `git worktree list` shows no __jNN entries
  - Gate 1 test suite: `pytest tests/ -x` exits 0 (all tests pass)
  - Gate 1 qB state snapshot: all state counts captured (stoppedUP, stoppedDL, stalledUP, checkingUP, others)
  - Gate 1 clean state: stalledUP=0, checkingUP=0 confirmed
  - Gate 1 j46 LIFT verdict: docs/CANONICALIZE-PILOT-RESULTS.md exists and contains "LIFT" recommendation
  - `docs/CANONICALIZE-PREFLIGHT.md` written with checklist table (✅/❌ per item) and state snapshot
  - Overall verdict in doc: PASS (all green) or FAIL (blocked items listed)
  - task-log emitted with status=done (even if gate verdict is FAIL — report the failure, do not halt task-log)
final_output_required=true
worktree_mirror_required=false
brief_hash="none"
agent_start_timestamp="set by agent at start — brief frozen after"
brief_freeze_violation="false"
🟦 task-brief=j47-t03_gate0-gate1-preflight 🟦

---

## Context

Read `docs/4-GATE-MUTATION-PROTOCOL.md` first — it defines exactly what each gate checks and the pass/fail criteria.

This task is READ-ONLY. No mutations to RT, qB, or filesystem. The only allowed file write is `docs/CANONICALIZE-PREFLIGHT.md`.

The `hashall canonicalize-apply` command (from j47-t02) must NOT be run during this task.

## Gate 0 — Baseline stoppedDL Audit

```bash
# Get current stoppedDL count and states from RT
# Use hashall CLI or python directly — do not use hashall canonicalize-apply
hashall payload status --stopped 2>/dev/null | head -50
# or equivalent
```

Expected baseline: ≤6 stoppedDL (5 RT_INCOMPLETE + 1 MISSING_DATA pre-existing from the j20 Gate 0 recovery in June 2026). If count > 6, classify all new items and flag as Gate 0 FAIL.

Note the 4 items from OP-43 that were at 99.9x% as of 2026-06-25 — check if these have now reached complete=1.

## Gate 1 — Pre-flight Checklist

### 1. Editable install check

```bash
find /home/michael -name "__editable__.hashall-*.pth" 2>/dev/null
cat <path-found>
```

The pth file must contain a path ending in `hashall-20260626-151456` (the CR worktree), NOT any `__j` worktree path.

### 2. Orphan worktrees

```bash
git worktree list
```

Must show only the main repo and `hashall-20260626-151456` CR worktree. Any `__jNN` entries are orphans (Gate 1 FAIL until cleaned — note them but do not prune).

### 3. Test suite

```bash
pytest tests/ -x -q 2>&1 | tail -20
```

All tests must pass. Known pre-existing failures (test_scan_integration.py, test_e2e_workflow.py, test_cli_devices.py) are expected — if these and only these fail, Gate 1 passes for the test suite item. Document which tests failed and confirm they are in the known-failures list.

### 4. qB state snapshot

```bash
hashall payload status --state-summary 2>/dev/null
# or query directly
```

Record all state counts. The snapshot timestamp becomes the pre-mutation baseline.

### 5. Clean state check

stalledUP must be 0. checkingUP must be 0. If either is non-zero: Gate 1 FAIL — wait for state to stabilize before proceeding.

### 6. j46 LIFT verdict

```bash
cat docs/CANONICALIZE-PILOT-RESULTS.md | grep -i "LIFT\|HOLD\|Recommendation"
```

Must contain "LIFT". If "HOLD": Gate 1 FAIL — j46 findings blocked live execution.

## Output: docs/CANONICALIZE-PREFLIGHT.md

```markdown
# Canonicalize Pre-flight Report
Date: <timestamp>
Agent: j47-t03

## Gate 0 — Baseline stoppedDL Audit
| Item | Count | Baseline | Verdict |
|------|-------|----------|---------|
| stoppedDL total | N | ≤6 | ✅/❌ |
| HEALTHY | N | | |
| MISSING_DATA | N | ≤1 | ✅/❌ |
| RT_INCOMPLETE | N | ≤5 | ✅/❌ |

Gate 0 verdict: PASS / FAIL

## Gate 1 — Pre-flight Checklist
| Check | Result | Verdict |
|-------|--------|---------|
| Editable install path | <path> | ✅/❌ |
| Orphan worktrees | none / <list> | ✅/❌ |
| Test suite | N passed, M failed | ✅/❌ |
| qB state snapshot | stoppedUP=N, stoppedDL=N, stalledUP=N, checkingUP=N | — |
| stalledUP=0 | 0 | ✅/❌ |
| checkingUP=0 | 0 | ✅/❌ |
| j46 LIFT verdict | LIFT | ✅/❌ |

Gate 1 verdict: PASS / FAIL

## Overall Pre-flight Verdict: PASS / FAIL

<If FAIL: list each failing item and what must be fixed before Gate 2 can proceed>
```

## If Any Gate Fails

Report FAIL in the doc and in the task-log. The lead will address the failing items. Do NOT proceed to Gate 2 work. Do NOT emit status=blocked — emit status=done with the FAIL verdict clearly stated in the doc.
