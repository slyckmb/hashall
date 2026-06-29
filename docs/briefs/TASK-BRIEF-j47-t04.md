🟦 task-brief=j47-t04_gate2-dryrun 🟦
id=j47-t04
role=agent
task_type=verification
goal=Gate 2: run hashall canonicalize-apply-batch --dry-run across all drifted items; inspect all planned actions; write docs/CANONICALIZE-REPAIR-MANIFEST.md; flag any structural problems before live execution
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j47
expected_branch=cr/hashall-20260626-151456__j47
expected_head=set_at_dispatch
allowed_mutation=files-only
allowed_commands=grep,find,cat,head,tail,python3,pip show,git log,git status,wc,ls,hashall
forbidden_commands=git commit,git push,pip install,opencode,chatrap job,rm -rf,make,hashall canonicalize-apply --force
success_criteria=
  - `docs/CANONICALIZE-PREFLIGHT.md` confirmed PASS (Gate 0+1) before proceeding — if FAIL, emit status=blocked
  - `hashall canonicalize-apply-batch --dry-run --json` runs successfully across all drifted items
  - Output captured and analyzed: all planned actions inspected
  - Every planned target path validated against §4.4.2 canonical path spec in docs/REQUIREMENTS.md
  - Cross-device items (fix_both, fix_placement_only) checked for storage feasibility (pool free space vs. payload sizes)
  - Items with unexpected plan_type=blocked (but should be fixable) flagged as anomalies
  - Repair manifest sorted by plan_type: fix_path_only → fix_placement_only → fix_both
  - `docs/CANONICALIZE-REPAIR-MANIFEST.md` written (see format below)
  - Gate 2 verdict emitted: PASS (ready for Gate 3) or FAIL (structural problem found)
  - task-log emitted with status=done
final_output_required=true
worktree_mirror_required=false
brief_hash="none"
agent_start_timestamp="set by agent at start — brief frozen after"
brief_freeze_violation="false"
🟦 task-brief=j47-t04_gate2-dryrun 🟦

---

## Context

Read `docs/4-GATE-MUTATION-PROTOCOL.md` for the full Gate 2 definition.
Read `docs/CANONICALIZE-PREFLIGHT.md` — must show PASS before running dry-run.

**This task is READ-ONLY.** The `--force` flag must NOT be used. All commands run in dry-run mode.

## Dry-Run Execution

```bash
# Full dry-run across all drifted items
hashall canonicalize-apply-batch --dry-run --json 2>&1 | tee /tmp/j47-t04-dryrun.ndjson

# Summary stats
cat /tmp/j47-t04-dryrun.ndjson | python3 -c "
import sys, json, collections
results = [json.loads(l) for l in sys.stdin if l.strip()]
by_type = collections.Counter(r['plan_type'] for r in results)
print(by_type)
print('Total:', len(results))
"
```

## Validation Checks

### 1. Canonical path spot-check

For each plan_type=fix_path_only item, verify the `target_path` matches §4.4.2:
- ARR post-import: `<seeding-root>/<media-type>/<item-name>`
- cross-seed: `<seeding-root>/cross-seed/<prowlarr-tracker-name>/<item-name>`
- qbm tracker: `<seeding-root>/<tracker-name>/<item-name>`

Spot-check at least 10 items (5 fix_path_only, 3 fix_placement_only, 2 fix_both if present).

### 2. Storage feasibility for cross-device items

```bash
# Pool free space
df -h /pool/media/torrents/seeding

# Estimate total size of fix_placement_only + fix_both items
cat /tmp/j47-t04-dryrun.ndjson | python3 -c "
import sys, json
results = [json.loads(l) for l in sys.stdin if l.strip()]
cross_device = [r for r in results if r['plan_type'] in ('fix_placement_only','fix_both') and r.get('move_required')]
print(f'{len(cross_device)} cross-device items')
# Sum sizes if available in ApplyResult
"
```

If pool free space < total cross-device payload size: flag as Gate 2 WARN — fix_both items must be deferred in Gate 4 until storage is expanded. fix_path_only and fix_placement_only without physical move can still proceed.

### 3. Anomaly check

Flag any items where:
- plan_type=blocked but item appears healthy (no known external consumers) — possible false BLOCK
- target_path is inside a staging dir (`_rehome-unique/`, `_pending/`, etc.) — bug in path inference
- source_path does not exist on disk — item may have already been moved manually

### 4. Confirm no --force side effects

After the dry-run, confirm RT and qB state are unchanged:
```bash
hashall payload status --state-summary 2>/dev/null
```
stoppedDL count must match the pre-flight baseline.

## Output: docs/CANONICALIZE-REPAIR-MANIFEST.md

```markdown
# Canonicalize Repair Manifest
Date: <timestamp>
Dry-run: yes
Agent: j47-t04

## Summary
| plan_type | Count | Move Required | Estimated Data |
|-----------|-------|---------------|----------------|
| fix_path_only | N | no | — |
| fix_placement_only | N | N cross-device | ~X TB |
| fix_both | N | N cross-device | ~X TB |
| blocked | N | — | — |
| ok | N | — | — |

Pool free space: X GB
Cross-device total: X GB
Storage feasible: yes / no (deferred fix_both if no)

## Anomalies
<list any items flagged in checks above>

## Spot-Check Results (10 items)
| Hash | plan_type | source_path | target_path | Path Verdict |
|------|-----------|-------------|-------------|-------------|
| ... | ... | ... | ... | ✅/❌ |

## Execution Order (Gate 4)
1. fix_path_only (N items) — no data movement, lowest risk
2. fix_placement_only (N items) — cross-device rsync
3. fix_both (N items, defer if storage insufficient)

## Gate 2 Verdict: PASS / FAIL

<If FAIL: which check failed and what must be fixed>
<If PASS: manifest is ready for Gate 3 dispatch by lead>
```

## Operator Review Note

Gate 2 ends here. The manifest doc must be reviewed by the operator (human) before Gate 3 is dispatched. The lead will read `docs/CANONICALIZE-REPAIR-MANIFEST.md` and confirm the planned actions before issuing the j47-t05 brief.
