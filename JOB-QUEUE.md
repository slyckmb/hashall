# Job Queue — hashall CR

session: hashall-20260626-151456
branch: cr/hashall-20260626-151456
worktree: /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456
updated: 2026-06-26

---

## Active Execution Plan

| Job | Slug | OPs |
|-----|------|-----|
| j36 | close-resolved | OP-29,OP-32,OP-46,OP-48 | Merged to CR. merge(cr/hashall-20260530-000517-claude__j36). |
| j37 | code-bug-fix | OP-04,OP-05,OP-06,OP-16 | Merged to CR. merge(cr/hashall-20260530-000517-claude__j37). |
| j38 | rcca-and-audit | RCCA/audit complete; follow-ups moved forward | Merged to CR. merge(cr/hashall-20260530-000517-claude__j38). |
| j40 | docs-batch | OP-01,OP-02,OP-03,OP-07,OP-08,OP-11,OP-12,OP-13,OP-25 | Merged to CR. merge(cr/hashall-20260626-151456__j40). 
| j41 | explore-unified-tool | OP-18 | Merged to CR. merge(cr/hashall-20260626-151456__j41). 
| j46 | build-canonicalize-tool | OP-50 | Merged to CR. merge(cr/hashall-20260626-151456__j46). 
| j47 | canonicalize-execute | OP-51 |
| j39 | cross-seed-repair | OP-09,OP-15,OP-17,OP-19,OP-24,OP-47 |
| j42 | lane2-strategy | OP-23,OP-26 |
| j43 | rt-state-monitor | OP-10,OP-43 |
| j44 | chatrap-infra | OP-42,OP-44,OP-45,OP-49 |
| j45 | cr-to-main | OP-14 |

---

## Dependencies

- j39 (cross-seed-repair) requires j37 (code-bug-fix) — must fix OP-16 before migrating ~2000 items
- j47 (canonicalize-execute) requires j46 (build-canonicalize-tool) — executor gates on j46-t05 LIFT verdict
- j39 (cross-seed-repair) requires j47 (canonicalize-execute) — all drift items must be corrected before cross-seed migration begins
- j42 (lane2-strategy) benefits from j46 (build-canonicalize-tool) — canonicalize batch output quantifies Lane 2 scope precisely
- j45 (cr-to-main) is last — merge only after all planned repair jobs complete

---

## Run Order

j36 → j37 → j38 → j40 → j41 → j46 → j47 → j39 → j42 → j43 → j44 → j45

Notes:
- j40 (docs) is independent and can be interleaved
- j43 (monitoring) should run promptly — OP-43 items have a 48h check window
- j44 (chatrap infra) is upstream work; file issues with chatrap maintainers, not code in this repo
- j36 first to clear resolved OPs and keep opscan count accurate

---

## j37 — code-bug-fix

**Slug:** code-bug-fix
**OPs:** OP-04, OP-05, OP-06, OP-16
**Goal:** Audit 4 open code bugs; close those already fixed; fix any still open.

### Tasks

| Task | Type | Goal |
|------|------|------|
| j37-t01 | discovery | Verify OP-05, OP-06, OP-16 status in current code; close confirmed-fixed OPs; document OP-04 fix scope |
| j37-t02 | implementation | Fix OP-04: integrate SYSTEM_TAGS with traktor registry (TBD after t01) |

---

## j40 — docs-batch

Status: planned
Slug: docs-batch
OPs: OP-01, OP-02, OP-03, OP-07, OP-08, OP-11, OP-12, OP-13, OP-25
Goal: Batch documentation/runbook cleanup for known process and dependency gaps.

### Tasks

| Task | Type | Goal |
|------|------|------|
| j40-t01 | discovery | Audit docs OPs and produce a precise docs-batch implementation plan; close any already-satisfied docs OPs with evidence |

---

## j46 — build-canonicalize-tool

**Slug:** build-canonicalize-tool
**OPs:** OP-50
**Goal:** Build `src/hashall/canonicalize.py` — a unified single-pass orchestrator that resolves both placement (WHERE: stash vs pool) and path structure (WHAT: canonical subdir formula) per torrent, cross-validates both dimensions against the §4.4 spec, emits structured drift verdicts, and generates repair plans consumable by existing executors. Exposes `hashall canonicalize` and `hashall canonicalize-batch` CLI. Mutation block on rehome/save_path_inference lifts only after pilot verification passes.

### Tasks

| Task | Type | Goal |
|------|------|------|
| j46-t01 | discovery | Map exact function signatures and instantiation requirements for the 3 key functions to wire; write `docs/CANONICALIZE-INTERFACE-MAP.md` |
| j46-t02 | implementation | Write `src/hashall/canonicalize.py`: dataclasses, 5-step pipeline, repair plan generator |
| j46-t03 | implementation | Add `hashall canonicalize` and `hashall canonicalize-batch` CLI entry points to `src/hashall/cli.py`; bump version |
| j46-t04 | testing | Write `tests/test_canonicalize.py`; all 6 gate scenarios must pass |
| j46-t05 | verification | Pilot run `hashall canonicalize-batch --drifted-only --limit 50`; inspect for false positives; write `docs/CANONICALIZE-PILOT-RESULTS.md`; recommend lift/hold on mutation block |

---

## j47 — canonicalize-execute

**Slug:** canonicalize-execute
**OPs:** OP-51
**Goal:** Build the `hashall canonicalize-apply` executor; formalize the 4-gate mutation protocol as an institutional doc; run all four gates against the live inventory to correct placement and path drift across ~4k RT items. Mutation block on rehome/save_path_inference fully lifted only after Gate 4 batch completes with stoppedDL delta=0.
**Gates on:** j46-t05 LIFT verdict (false positive rate ≤ 5%)

### Tasks

| Task | Type | Goal |
|------|------|------|
| j47-t01 | doc | Write `docs/4-GATE-MUTATION-PROTOCOL.md` — canonical protocol reference; update REPO-MASTERY.md |
| j47-t02 | implementation | Build `apply_repair_plan()` + `hashall canonicalize-apply` and `hashall canonicalize-apply-batch` CLI; default dry-run, require --force to mutate |
| j47-t03 | verification | Gate 0+1: catalog freshness, stoppedDL baseline, editable install, test suite green, qB state snapshot; write `docs/CANONICALIZE-PREFLIGHT.md`; PASS required before Gate 2 |
| j47-t04 | verification | Gate 2: dry-run all drifted items via `canonicalize-apply-batch --dry-run`; write `docs/CANONICALIZE-REPAIR-MANIFEST.md`; operator review required before Gate 3 |
| j47-t05 | verification | Gate 3: single fix_path_only item live pilot; record pre/post RT+qB state; 60s re-check; write `docs/CANONICALIZE-GATE3-PILOT.md`; PASS = stoppedUP at canonical path, zero new stoppedDL |
| j47-t06 | implementation | Gate 4: gated batch — fix_path_only first, then fix_placement_only, then fix_both if storage permits; ≤5 items per batch, state check after each; write `docs/CANONICALIZE-GATE4-PROGRESS.md` |

---

## Queue State Notes

JOB-QUEUE.md written 2026-06-26 by lead after opscan showed 32 unslotted OPs.
All 32 open OPs now slotted across 10 planned jobs.
After j38 RCCA, OP-19/24/47 remain open and are re-slotted to j39 for follow-up repair/audit.
Next job to dispatch: j40 (docs-batch), per run order.
