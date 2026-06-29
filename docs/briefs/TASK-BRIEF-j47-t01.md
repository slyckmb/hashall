🟦 task-brief=j47-t01_4-gate-protocol-doc 🟦
id=j47-t01
role=agent
task_type=doc
goal=Write docs/4-GATE-MUTATION-PROTOCOL.md as the canonical institutional reference for the 4-gate staged mutation protocol; update REPO-MASTERY.md to reference it
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j47
expected_branch=cr/hashall-20260626-151456__j47
expected_head=set_at_dispatch
allowed_mutation=files-only
allowed_commands=grep,find,cat,head,tail,git log,git diff,git status,wc,ls
forbidden_commands=git commit,git push,pip install,opencode,chatrap job,rm -rf,hashall,make
success_criteria=
  - `docs/4-GATE-MUTATION-PROTOCOL.md` created with all 5 sections (see below)
  - All 4 gates defined with full pass/fail criteria and abort conditions
  - Process change lessons from LANE1-PILOT-RCCA.md incorporated (all 5 items)
  - REPO-MASTERY.md updated to reference the new doc under a "Key Process Protocols" or equivalent section
  - Document is self-contained — a future lead reading it cold can run the protocol without consulting RCCA history
  - task-log emitted with status=done
final_output_required=true
worktree_mirror_required=false
brief_hash="none"
agent_start_timestamp="set by agent at start — brief frozen after"
brief_freeze_violation="false"
🟦 task-brief=j47-t01_4-gate-protocol-doc 🟦

---

## Context

The 4-gate mutation protocol emerged from the Lane 1 pilot incident (2026-06-18, RCCA in `docs/LANE1-PILOT-RCCA.md`). That pilot ran 138 items with a stale editable install, caused 110 checkingUP torrents, mass-paused them into 115 stoppedDL, and took days to recover. The protocol was defined post-incident as the required process before any future mass mutation run.

It is currently scattered across `docs/LANE1-PILOT-RCCA.md`, `docs/GATE0-STOPPDL-AUDIT.md`, and `docs/gate3-drift-pilot-results.md`. It needs to be consolidated into a single canonical doc that any lead agent can find in REPO-MASTERY.md.

## Source Documents

Read all of these before writing the protocol doc:
- `docs/LANE1-PILOT-RCCA.md` — root causes, gate definitions, process change requirements (the primary source)
- `docs/GATE0-STOPPDL-AUDIT.md` — what Gate 0 looks like in practice
- `docs/gate3-drift-pilot-results.md` — what Gate 3 looks like in practice
- `docs/REQUIREMENTS.md §5.1` — staged cleanup model (relevant to how reversibility works)
- `REPO-MASTERY.md` — find the right place to insert the reference

## Output: docs/4-GATE-MUTATION-PROTOCOL.md

Structure the document with these 5 sections:

### 1. Purpose and Scope
- What the protocol protects against (mass stoppedDL from untested mutations, stale editable install, premature batch runs)
- When to apply it: any hashall CLI mutation touching ≥1 RT/qB torrent state (set_location, repoint, rehome apply, canonicalize-apply)
- When NOT required: read-only commands (canonicalize, canonicalize-batch without --force, audit commands)

### 2. Pre-conditions (must all be true before Gate 0)
- j46 LIFT verdict on file (docs/CANONICALIZE-PILOT-RESULTS.md or equivalent)
- No orphan `__jNN` worktrees registered in git (all jobs merged to CR)
- REPO-MASTERY.md mastery gate passes (chatrap ack lead --mastery-gate)

### 3. Gate Definitions

For each gate, document:
- **What it checks**
- **Required commands** (exact CLI, flags)
- **Pass criteria** (all items must be true)
- **Fail criteria** (any item triggers abort)
- **Abort action** (what to do on fail)
- **Output artifact** (what doc to write)

**Gate 0 — Incident Recovery / Baseline Audit**
  Verify no pre-existing damage that would be obscured by mutations. This was the recovery phase after the j18 incident — generalize it as a baseline audit step.
  - Catalog current stoppedDL count; classify each: HEALTHY (qB confusion), MISSING_DATA, RT_INCOMPLETE
  - Pass: stoppedDL ≤ known baseline (document the baseline); no new MISSING_DATA items
  - Fail: stoppedDL > baseline or unexplained new items → investigate before proceeding
  - Artifact: pre-flight stoppedDL snapshot (inline in PREFLIGHT doc)

**Gate 1 — Pre-flight Checklist**
  Drawn directly from LANE1-PILOT-RCCA.md process changes:
  - `cat __editable__.hashall-*.pth` → must point to CR worktree (not a job worktree)
  - All `__jNN` worktrees removed (`git worktree list` shows only CR worktree and main repo)
  - Full test suite green (`pytest tests/ -x` exits 0)
  - qB state snapshot captured before any mutation (all state counts: stoppedUP, stoppedDL, stalledUP, checkingUP)
  - Zero stalledUP, zero checkingUP confirmed
  - Pass: all 5 checks green
  - Fail: any check fails → fix before Gate 2
  - Artifact: checklist table in PREFLIGHT doc with ✅/❌ per item

**Gate 2 — Dry-Run Validation**
  - Run mutation command with `--dry-run` flag across all target items
  - Inspect planned actions: verify canonical_path values match §4.4.2, verify plan_type correct, flag any cross-device moves where pool free space < payload size
  - Pass: all planned actions have correct target paths; no unexpected plan_type=blocked items; storage sufficient
  - Fail: any target path looks wrong, or cross-device move would exceed available pool space → fix inference bug or defer fix_both items
  - Artifact: repair manifest doc (CANONICALIZE-REPAIR-MANIFEST.md or equivalent)

**Gate 3 — Single-Item Live Pilot**
  Lessons from RCCA RC-6: Gate 3 pilot must exercise real state transitions, not just 1 low-risk item.
  - Select 1 item: smallest fix_path_only item (safest plan_type, no data movement)
  - Record exact pre-state: RT d.directory, qB save_path, qB state, RT complete, RT down_rate
  - Execute with `--force` flag
  - Record exact post-state immediately after
  - Wait 60 seconds; re-check state — confirm no spontaneous transitions (stalledUP → something else)
  - Verify RT is seeding at canonical path (state=1, down_rate=0)
  - Verify qB state is stoppedUP (not stoppedDL, not checkingUP, not stalledUP)
  - Pass: item stoppedUP at canonical path; stoppedDL count unchanged; no stalledUP; no checkingUP
  - Fail: any new stoppedDL, any stalledUP, any checkingUP → STOP. Do not proceed. Escalate via `chatrap session escalate`.
  - Artifact: pilot result doc

**Gate 4 — Gated Batch Execution**
  - Run in batches of ≤5 items
  - Order: fix_path_only first, then fix_placement_only, then fix_both (if storage permits)
  - Full state check after EACH batch: stoppedDL delta=0, stalledUP=0, checkingUP=0
  - Human sign-off before each next batch (write batch result, stop, wait)
  - Do not run fix_both items if pool free space < total fix_both payload size
  - Pass: all items stoppedUP at canonical path; stoppedDL delta=0 throughout
  - Fail: any stoppedDL increase → pause all further batches; diagnose; escalate
  - Artifact: progress doc updated after each batch

### 4. Abort and Recovery

- **Immediate abort triggers**: new stoppedDL, new stalledUP, new checkingUP, set_location returning False
- **On abort**: do NOT mass-pause checkingUP (this caused 115 stoppedDL in the original incident — let checkingUP complete naturally)
- **Recovery sequence**: wait for all checkingUP to reach stoppedUP naturally → then pause individually → audit state → file escalation
- **Escalate command**: `chatrap session escalate --reason "<what happened>"`

### 5. Lessons Incorporated (from LANE1-PILOT-RCCA.md)

Enumerate all 5 process change items from the RCCA verbatim, with a note on where each is addressed in the protocol.

## REPO-MASTERY.md Update

Add a section or entry referencing `docs/4-GATE-MUTATION-PROTOCOL.md` under a heading like:
```
## Key Process Protocols
- [4-Gate Mutation Protocol](docs/4-GATE-MUTATION-PROTOCOL.md) — required before any mass RT/qB state mutation
```

Find the appropriate place in REPO-MASTERY.md (near the top, in a Key Processes section, or at the end of the Operations section — wherever makes most sense in context).
