🟦 task-brief=j47-t06_gate4-batch 🟦
id=j47-t06
role=agent
task_type=implementation
goal=Gate 4: run gated batch execution of all repair plans; fix_path_only first, then fix_placement_only, then fix_both if storage permits; ≤5 items per batch with state check and lead approval between batches; write docs/CANONICALIZE-GATE4-PROGRESS.md
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j47
expected_branch=cr/hashall-20260626-151456__j47
expected_head=set_at_dispatch
allowed_mutation=files-only
allowed_commands=grep,find,cat,head,tail,python3,pip show,git log,git status,wc,ls,hashall,df
forbidden_commands=git commit,git push,pip install,opencode,chatrap job,rm -rf,make
success_criteria=
  - Gate 3 pilot (docs/CANONICALIZE-GATE3-PILOT.md) confirmed PASS — if FAIL, emit status=blocked
  - fix_path_only items processed first, in batches of ≤5
  - State check after each batch: stoppedDL delta=0, stalledUP=0, checkingUP=0
  - Lead approval checkpoint AFTER each batch before next batch (emit checkpoint note in doc, then stop and wait)
  - fix_placement_only items processed after all fix_path_only are done
  - fix_both items processed only if pool free space > total fix_both payload size; otherwise deferred with note
  - `docs/CANONICALIZE-GATE4-PROGRESS.md` written and updated after each batch
  - On any state regression: immediate halt, full abort report, escalate — do NOT continue
  - Final stoppedDL delta: 0 (no new stoppedDL introduced by any batch)
  - task-log emitted with status=done when batch execution completes (or status=blocked on abort)
final_output_required=true
worktree_mirror_required=false
brief_hash="none"
agent_start_timestamp="set by agent at start — brief frozen after"
brief_freeze_violation="false"
🟦 task-brief=j47-t06_gate4-batch 🟦

---

## Context

Read `docs/4-GATE-MUTATION-PROTOCOL.md` for the full Gate 4 definition and abort conditions.
Read `docs/CANONICALIZE-GATE3-PILOT.md` — must show Gate 3 PASS before proceeding.
Read `docs/CANONICALIZE-REPAIR-MANIFEST.md` for the full item list and execution order.

This is a LIVE MUTATION task. `--force` is authorized for all items in the manifest, subject to per-batch state checks and lead approval between batches.

## Pre-Batch Safety Check

Before the first batch, re-confirm clean state:
```bash
hashall payload status --state-summary 2>/dev/null
```
stalledUP must be 0, checkingUP must be 0. If not: abort. Do not start batch execution in a degraded state.

## Batch Execution Protocol

### Step 1: fix_path_only items

Divide all fix_path_only items into batches of ≤5. For each batch:

```bash
# Get next 5 fix_path_only hashes from manifest (track which have been done)
hashall canonicalize-apply-batch --force --plan-type fix_path_only --limit 5 --json \
  2>&1 | tee -a /tmp/j47-t06-batch-<N>.json
```

After each batch:
```bash
hashall payload status --state-summary 2>/dev/null
```

State check criteria:
- stoppedDL delta vs. Gate 1 baseline: must be 0
- stalledUP: must be 0
- checkingUP: must be 0

If all pass: append batch result to `docs/CANONICALIZE-GATE4-PROGRESS.md` and STOP. Emit a one-line status update indicating batch N complete and checkpoint reached. The lead will review and re-dispatch with the next batch authorized.

**IMPORTANT**: Do not run the next batch without receiving a re-dispatch instruction from the lead. Each batch is a separate authorization unit. After writing the progress doc update and status, STOP and emit the task-log with status=done for this batch only. The lead will dispatch a fresh run of this same brief for the next batch (or a new brief if phase changes to fix_placement_only).

### Step 2: fix_placement_only items

After all fix_path_only items complete and lead authorizes:
- Check pool free space: `df -h /pool/media/torrents/seeding`
- Sum fix_placement_only payload sizes from manifest
- If feasible: same batch protocol (≤5 per batch, state check, lead approval)
- If not feasible: note in progress doc, defer with storage-expand prerequisite

### Step 3: fix_both items

Only after fix_placement_only complete and lead authorizes:
- Re-check pool free space (fix_placement_only moves freed stash space, may not add pool space)
- Sum fix_both payload sizes
- If feasible: same batch protocol
- If not feasible: defer. Write deferred items list in progress doc with space requirement.

## Abort Conditions

ANY of these triggers immediate halt — do NOT continue to next batch:
- stoppedDL count increases above Gate 1 baseline
- stalledUP count > 0
- checkingUP count > 0
- Any `canonicalize-apply` call returns exit code non-zero
- Any item post-state shows qB state != stoppedUP

On abort:
1. Stop immediately — do not process remaining items in batch
2. Record exact state in progress doc: which item failed, what state it landed in
3. Do NOT mass-pause any torrents (RCCA lesson: pausing checkingUP causes stoppedDL)
4. Escalate: `chatrap session escalate --reason "Gate 4 batch abort: <description>"`
5. Emit task-log status=blocked

## Output: docs/CANONICALIZE-GATE4-PROGRESS.md

Append after each batch (do not overwrite):

```markdown
# Gate 4 Batch Execution Progress
Overall date range: <start> — <ongoing>

## Batch 1 — fix_path_only (items 1-5)
Date: <timestamp>
Items: <hash1>, <hash2>, ...
Result: 5/5 success
Post-state: stoppedDL=<N> (delta=0), stalledUP=0, checkingUP=0
State check: PASS
--- CHECKPOINT: lead approval required before Batch 2 ---

## Batch 2 — fix_path_only (items 6-10)
...

## Phase Summary: fix_path_only
Total: N items processed, N success, 0 fail
Proceeding to: fix_placement_only / DEFERRED (reason)

## Phase Summary: fix_placement_only
...

## Final Summary
fix_path_only: N/N complete
fix_placement_only: N/N complete (or deferred)
fix_both: N/N complete (or deferred — needs X GB pool space)
stoppedDL delta (Gate 1 baseline vs. final): 0
Gate 4 Verdict: PASS / FAIL / PARTIAL
Mutation block status: LIFTED / PARTIAL-LIFTED / HOLD
```

## Mutation Block Lift Criteria

After Gate 4 completes:
- If fix_path_only + fix_placement_only complete with delta=0: mutation block on `save_path_inference` is LIFTED
- If fix_both also complete with delta=0: mutation block on `rehome apply` is LIFTED
- If fix_both deferred (storage): partial lift — save_path_inference unblocked, rehome apply remains blocked until fix_both items are resolved

Record the final mutation block status in the progress doc.
