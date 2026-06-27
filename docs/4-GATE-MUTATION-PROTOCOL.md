# 4-Gate Mutation Protocol

**Version:** 1.0
**Status:** Active — required before any mass RT/qB state mutation
**Source:** Consolidated from LANE1-PILOT-RCCA.md, GATE0-STOPPDL-AUDIT.md, gate3-drift-pilot-results.md, REQUIREMENTS.md
**Applies to:** All hashall CLI mutations touching torrent state on RT or qB

---

## 1. Purpose and Scope

### What This Protocol Protects Against

The 4-gate protocol emerged from the Lane 1 pilot incident (2026-06-18), which caused:
- **115 stoppedDL** torrents from mass-pausing checkingUP items during cleanup
- **110 checkingUP** events from `set_location` unconditionally resuming torrents
- **27 stalledUP** items from re-pause race conditions
- **Stale editable install** pointed at j18 worktree, not CR — pilot ran wrong code throughout

The protocol is a staged safety barrier that prevents these failure modes by forcing
verification at each step before the next can proceed.

### When to Apply

The protocol is required for any operation that mutates RT or qB torrent state
on ≥1 item:

- `hashall set_location` — qB path mutation
- `hashall repoint` — RT/qB path synchronization
- `hashall rehome apply` — payload relocation (demote/promote)
- `hashall canonicalize-apply` — path normalization with `--force`
- Any custom script that calls `setLocation`, `pause_torrents`, `resume_torrents`,
  `recheck_torrent`, or RT `d.directory` on ≥1 item

### When NOT Required

Read-only or non-mutating commands may skip the full protocol:

- `hashall canonicalize` (plan mode, no `--force`)
- `hashall canonicalize-batch` without `--force`
- `hashall scan`, `hashall refresh`, `hashall payload sync`
- `hashall audit` commands (drift audit, stoppedDL audit, etc.)
- Read-only qB state queries via the cache

---

## 2. Pre-conditions (must all be true before Gate 0)

Before entering Gate 0, verify all three pre-conditions:

| # | Condition | Verification Command |
|---|-----------|---------------------|
| P1 | LIFT verdict for previous mutation run exists on file | `ls docs/CANONICALIZE-PILOT-RESULTS.md` (or equivalent LIFT results doc) |
| P2 | No orphan `__jNN` worktrees — all jobs merged to CR | `git worktree list` — only CR worktree and main repo should appear |
| P3 | REPO-MASTERY.md mastery gate passes | `chatrap ack lead --mastery-gate` exits 0 |

If any pre-condition fails, stop. Do not proceed to Gate 0.
Resolve the failing condition first (e.g., close unmerged jobs, fix mastery gap).

---

## 3. Gate Definitions

### Gate 0 — Incident Recovery / Baseline Audit

Check that no pre-existing damage would be obscured or conflated with mutation
effects. Gate 0 establishes the baseline.

| Aspect | Detail |
|--------|--------|
| **What it checks** | Current stoppedDL count and classification; verifies no hidden damage |
| **Required commands** | qB state query (all states + counts); RT poll of stoppedDL items |
| **Pass criteria** | stoppedDL ≤ known baseline (documented); no new MISSING_DATA items; zero checkingUP; zero stalledUP |
| **Fail criteria** | stoppedDL > baseline; unexplained new items (MISSING_DATA or RT_INCOMPLETE); any checkingUP or stalledUP present |
| **Abort action** | Investigate before proceeding. Do not skip to Gate 1. Write findings to PREFLIGHT doc and escalate. |
| **Output artifact** | Pre-flight stoppedDL snapshot (inline in PREFLIGHT doc — stoppedDL count by classification: HEALTHY / MISSING_DATA / RT_INCOMPLETE) |

**Baseline stoppedDL count:** 6 (post-Lane-1-recovery state, documented in LANE1-PILOT-RCCA.md).
If this number changes unexpectedly, investigate before mutating anything.

**Classification definitions:**
- **HEALTHY:** RT `d.complete=1`, `d.down.rate=0`, files present at qB path. qB confusion only — torrent data is intact.
- **MISSING_DATA:** RT `d.complete=1`, files NOT found at qB's cached save_path. Data exists at canonical path but qB metadata is stale. Fixable via set_location.
- **RT_INCOMPLETE:** RT `d.complete=0` — torrent data was never fully received. Pre-existing download failure, not mutation damage.

---

### Gate 1 — Pre-flight Checklist

Drawn from LANE1-PILOT-RCCA.md process changes. All 5 items must pass.

| # | Check | Command | Pass | Fail |
|---|-------|---------|------|------|
| 1 | Editable install points to CR worktree | `cat __editable__.hashall-*.pth` | Path contains CR worktree, NOT `__jNN` | Points to a job worktree → reinstall with `pip install -e .` from CR worktree |
| 2 | All `__jNN` worktrees removed | `git worktree list` | Only CR worktree + main repo shown | Any `__jNN` present → `chatrap job done` + verify merge, then remove |
| 3 | Full test suite green | `pytest tests/ -x` | Exit code 0, all tests pass | Any failure → fix before proceeding |
| 4 | qB state snapshot captured | `hashall qb state` (or qB API state_breakdown) | Snapshot written to PREFLIGHT doc | Command fails → fix qB connection |
| 5 | Zero stalledUP, zero checkingUP | qB state query | stalledUP=0, checkingUP=0 | Any stalledUP or checkingUP → resolve naturally (do NOT mass-pause) |

**Output artifact:** Checklist table in PREFLIGHT doc with ✅/❌ per item. Include full qB state breakdown.

**If any check fails:** Fix before Gate 2. Do not proceed with mutations until all 5 are green.

---

### Gate 2 — Dry-Run Validation

Run the mutation command in `--dry-run` mode against all target items. Inspect
planned actions before any live execution.

| Aspect | Detail |
|--------|--------|
| **What it checks** | Planned action correctness: target paths, plan types, storage sufficiency |
| **Required commands** | Mutation command with `--dry-run` flag (e.g., `hashall canonicalize-apply --dry-run`, `hashall rehome apply --dry-run`) |
| **Pass criteria** | All planned actions have correct target paths (match §4.4.2 canonical path formula); no unexpected `plan_type=blocked` items; cross-device moves have sufficient free space on target pool |
| **Fail criteria** | Any target path looks wrong (non-canonical); unexpected blocked items; cross-device move would exceed available pool space by >10% |
| **Abort action** | Fix inference bug in path logic, or defer `fix_both` items if storage is insufficient. Do not proceed to live execution. |
| **Output artifact** | Repair manifest (e.g., `CANONICALIZE-REPAIR-MANIFEST.md`) listing all planned actions, target paths, plan types, and storage checks |

**Cross-device check:** When a planned action would move data across ZFS datasets,
verify `pool free space > total payload size` for all affected items. If free space
is insufficient, defer cross-device items and proceed only with same-device ones.

**Dry-run must produce zero unexpected results.** If the dry-run reveals items
you didn't expect to see, or items are unexpectedly blocked, investigate before
proceeding.

---

### Gate 3 — Single-Item Live Pilot

Before any batch execution, run exactly one live item to exercise real state
transitions. Per RCCA RC-6, the pilot must test actual mutation effects — not
just a trivial item.

| Aspect | Detail |
|--------|--------|
| **What it checks** | Real state transitions after a live mutation: RT seeding at canonical path, qB stoppedUP, no new stoppedDL/stalledUP/checkingUP |
| **Required commands** | Mutation command with `--force` on single item; state queries pre/post; 60-second wait |
| **Pass criteria** | Item is stoppedUP at canonical path; stoppedDL count unchanged from Gate 0 baseline; stalledUP=0; checkingUP=0 |
| **Fail criteria** | Any new stoppedDL; any stalledUP; any checkingUP → STOP. Do not proceed. Escalate. |
| **Abort action** | `chatrap session escalate --reason "<what happened>"`. Do NOT mass-pause checkingUP. Wait for natural resolution. |

**Pilot item selection:**
1. Prefer the smallest `fix_path_only` item (safest plan type — no data movement)
2. If no `fix_path_only` items exist, use the smallest `fix_placement_only` item
3. Do NOT select a `fix_both` item for the pilot unless no other plan types exist

**Pre-state recording (must capture before mutation):**
- RT: `d.directory`, `d.complete`, `d.down.rate`
- qB: `save_path`, `state`, `progress`
- qB global: stoppedDL count, stalledUP count, checkingUP count

**Post-state recording (immediately after mutation):**
- Same fields as pre-state
- Confirm RT `state=1` (seeding), `d.down.rate=0`

**60-second wait:** Re-check all states after 60 seconds. Confirm no spontaneous
transitions (e.g., stalledUP → something else, or new checkingUP appearing).

**Output artifact:** Pilot result doc with pre/post state table, 60-second follow-up,
and pass/fail verdict.

---

### Gate 4 — Gated Batch Execution

Execute remaining items in small batches with full state verification after each.

| Aspect | Detail |
|--------|--------|
| **What it checks** | Batch execution safety: stoppedDL delta=0, stalledUP=0, checkingUP=0 after each batch |
| **Required commands** | Mutation command on ≤5 items per batch; full state check after each |
| **Pass criteria** | All items stoppedUP at canonical path; stoppedDL delta=0 throughout; stalledUP=0; checkingUP=0 |
| **Fail criteria** | Any stoppedDL increase → pause all further batches; diagnose; escalate |
| **Abort action** | Halt all remaining batches. Do NOT mass-pause checkingUP. Wait for natural resolution. Escalate. |

**Batch ordering (priority):**
1. `fix_path_only` items first (no data movement, lowest risk)
2. `fix_placement_only` items second (path update only)
3. `fix_both` items last (data movement, highest risk — only if storage permits)

**Storage guard for fix_both:** Do not run `fix_both` items if pool free space
< total `fix_both` payload size. Calculate total before the first `fix_both`
batch.

**Human sign-off:** After each batch, write batch results (items, outcomes,
state delta) to the progress doc and stop. Wait for human review and explicit
go-ahead before the next batch. Do NOT chain batches automatically.

**Full state check after EACH batch:**
```
stoppedDL delta = 0?     → continue (or stop if done)
stalledUP = 0?           → continue
checkingUP = 0?          → continue
Any failed item?         → log and examine, but do not stop unless systemic
```

**Output artifact:** Progress doc updated after each batch with:
- Batch number and items processed
- Success/failure per item
- Pre- and post-batch state breakdown
- Delta analysis (stoppedDL, stalledUP, checkingUP)
- Verdict (pass / paused / escalate)

---

## 4. Abort and Recovery

### Immediate Abort Triggers

Any of these during any gate or batch execution triggers an immediate abort:

| Trigger | Why | Action |
|---------|-----|--------|
| New stoppedDL appears | Data integrity risk — qB may consider data incomplete | STOP all mutations. Do not pause. |
| New stalledUP appears | Post-resume race condition | STOP. Do not mass-pause. |
| New checkingUP appears | `set_location` internal resume | STOP. Do NOT pause checkingUP items. |
| `set_location` returns False | Operation failed on a torrent | STOP. Investigate root cause. |
| Cross-device move guard fires | Data would be physically copied across pools | STOP. Re-plan cross-device items. |

### On Abort: Critical Rule

**DO NOT mass-pause checkingUP torrents.** Pausing during checkingUP when a
torrent is cross-seed (may be incomplete) causes qB to land the torrent in
`stoppedDL`. This was the direct cause of 115 stoppedDL in the original Lane 1
incident (LANE1-PILOT-RCCA.md, RC-5).

### Recovery Sequence

1. **Wait** — Let all checkingUP items complete naturally to stoppedUP.
   checkingUP is transient; most items resolve within seconds.
2. **Pause individually** — After checkingUP has resolved, pause any stalledUP
   items one at a time. Do NOT batch-pause.
3. **Audit state** — Re-run the Gate 0 baseline check. Compare current state
   against pre-mutation state. Document all deltas.
4. **Escalate** — File an escalation report:
   ```
   chatrap session escalate --reason "<what happened>"
   ```

### Containment vs Repair

The abort sequence is containment, not repair. After escalation, a dedicated
repair job (separate from the mutation run) should plan and execute repair with
its own 4-gate process.

---

## 5. Lessons Incorporated (from LANE1-PILOT-RCCA.md)

All five process change items from the Lane 1 RCCA are addressed in this protocol:

| # | RCCA Process Change | Addressed In |
|---|---------------------|-------------|
| 1 | **Editable install guard**: Before any `hashall payload` CLI execution, verify pth file points to CR worktree | Gate 1, Check #1 — `cat __editable__.hashall-*.pth` must show CR worktree path, not `__jNN` |
| 2 | **Job lifecycle**: All jobs MUST be closed (`chatrap job done`) before running production operations. Verify with `git log --oneline \| grep merge` | Pre-condition P2 + Gate 1, Check #2 — `git worktree list` confirms no orphan `__jNN` worktrees |
| 3 | **Pre-run qB snapshot**: Record `state_breakdown` before any execute operation. Compare after. | Gate 1, Check #4 — full qB state snapshot captured in PREFLIGHT doc; compared after each Gate 4 batch |
| 4 | **No mass-pause on checkingUP**: When cleaning up unexpected states, pause stalledUP individually and wait for checkingUP to complete naturally before pausing those. | §4 Abort and Recovery — explicitly prohibits mass-pause of checkingUP; recovery sequence waits for natural resolution |
| 5 | **Single-item test per code change**: Each new lane1_execute code change requires a single-item live test before batch use. | Gate 3 — single-item live pilot with 60-second observation window; must pass before Gate 4 batch execution |

---

*This document is canonical. Future leads should refer here before any mutation
operation. If protocol changes are needed, update this document and increment
the version number, recording the change in the version history.*
