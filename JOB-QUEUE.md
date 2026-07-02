# Job Queue — hashall CR

session: hashall-20260626-151456
branch: cr/hashall-20260626-151456
worktree: /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456
updated: 2026-07-01

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
| j47 | canonicalize-execute | OP-51,OP-52,OP-54 | Merged to CR. merge(cr/hashall-20260626-151456__j47). |
| j48 | sha256-content-anchor | OP-53,OP-55,OP-56 | Merged to CR. merge(cr/hashall-20260626-151456__j48). |
| j49 | orphan-migration-guard | OP-57 | OBE — merged into j50 (pool-orphan-dedupe). Branch deleted, worktree removed. |
| j50 | pool-orphan-dedupe | OP-57,OP-60,OP-61 |
| j53 | repo-mastery-docs | OP-64 |
| j51 | missingFiles-repair | OP-62 |
| j52 | rt-qb-mirror-race | OP-58,OP-59 |
| j42 | lane2-strategy | OP-23,OP-26 |
| j39 | cross-seed-repair | OP-09,OP-15,OP-17,OP-19,OP-24,OP-47 |
| j43 | rt-state-monitor | OP-10,OP-12 |
| j44 | chatrap-infra | OP-42,OP-45 |
| j45 | cr-to-main | OP-14 |

---

## Dependencies

- j39 (cross-seed-repair) requires j37 (code-bug-fix) — must fix OP-16 before migrating ~2000 items
- j47 (canonicalize-execute) requires j46 (build-canonicalize-tool) — executor gates on j46-t05 LIFT verdict
- j39 (cross-seed-repair) requires j47 (canonicalize-execute) — all drift items must be corrected before cross-seed migration begins
- j42 (lane2-strategy) benefits from j46 (build-canonicalize-tool) — canonicalize batch output quantifies Lane 2 scope precisely
- j48 (sha256-content-anchor) requires OP-53 Phase 1 SHA256 backfill before Phases 2-4 can be tested with real data
- j45 (cr-to-main) is last — merge only after all planned repair jobs complete

---

## Run Order

j48 → j50 → j53 → j51 → j42 → j39 → j52 → j43 → j44 → j45

Notes:
- j48 (sha256-content-anchor) done — SHA256 backfill + _Sha256ContentMatcher + repoint_both_to_stash delivered; 83 blocked FPs resolvable
- j50 (pool-orphan-dedupe) current — consolidated job: OP-57 hardlink guard (code done, uncommitted), OP-60 quick_hash mode for cross-device matching, OP-61 execute SHA256-confirmed orphan dedupe. Class B complete (6,208 files, 2.7 TB recovered). t06 (Class C rsync) + t07 (wrap) pending.
- j53 (repo-mastery-docs) next — OP-64 full audit of repo mastery documentation. Trigger: agent proposed rehome-rule violation because mastery self-check didn't test the pattern. Tasks: audit REQUIREMENTS.md, AGENT-MASTERY.md, ARCHITECTURE.md for untested principles; write new self-check questions; end-to-end verify. ORDERED NEXT.
- j51 (missingFiles-repair) urgent — 440 qB torrents at missingFiles 0% because save_path points to stale stash paths. Batch set_location to pool + recheck per OP-62. Single-file items allow fast fix; multi-file need dir move
- j42 (lane2-strategy) after j50 — quantifies Lane 2 scope for 1030 ROOT_DRIFT + 2361 compound drift items on POOL; decide STASH→POOL vs POOL→stash strategy using new library_dupe/repoint_both_to_stash tooling
- j39 (cross-seed-repair) after j42 — requires canonicalize drift items corrected (j46+j47+j48 done) and lane2 strategy settled
- j52 (rt-qb-mirror-race) — OP-58/OP-59 investigate mirror flow share-limit race that left 2 TorrentDay cross-seed items stalledUP in qB + PU in RT. Can run in parallel with j39 since it's a different subsystem
- j43 (rt-state-monitor) — RT restart + qB cache daemon migration (OP-12 re-slotted from j40)
- j44 (chatrap infra) — upstream fixes
- j45 (cr-to-main) — merge CR to main after all repair jobs done

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

## j48 — sha256-content-anchor

**Slug:** sha256-content-anchor
**OPs:** OP-53, OP-55, OP-56
**Goal:** Add SHA256-based cross-device content matching to canonicalize pipeline so items with library copies on different filesystems are correctly classified as STASH candidates. Resolves 83 blocked FP items from Gate 2 dry-run (OP-55). Fixes qB recheck gap post-set_location (OP-56).
**Prerequisites:** Phase 1 SHA256 backfill scan on `/pool/media/torrents/seeding` must complete before Phases 2-4 can be tested with real data.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j48-t02 | planned | Phase 1: SHA256 backfill on pool seeding roots. Phase 2: `_Sha256ContentMatcher` class in `client_drift.py` for cross-device content matching |
| j48-t03 | planned | Phase 3: Wire `library_dupe` parameter into `classify_seeding_device()` + `resolve_canonical_path()` + CLI `--library-dupe` flag |
| j48-t04 | planned | Phase 4: Extend client-drift rank/apply for SHA256-dupe; add `repoint_both_to_stash` action; fix OP-56 qB recheck gap |

---

---

## j50 — pool-orphan-dedupe

**Slug:** pool-orphan-dedupe
**OPs:** OP-57, OP-60, OP-61
**Goal:** Clear the pool space wall so the original canonicalize pipeline (Gate 4 batch, OP-51) can resume. Recover ~2.2 TB on pool by deleting orphan files whose content is confirmed safe elsewhere — no data copy needed.

### Why we're here (the chain back to the original goal)

The original goal was **enforce §4.4 placement policy** — move cross-seed content from stash to pool, where it belongs. j47 Gate 4 batch was doing this: 428 stash→pool moves completed before **pool hit 0 bytes**. The batch stopped mid-flight.

The pool was full because `/pool/media/torrents/orphans/` was hoarding **3.9 TB** (`du`). Plan A was to offload orphans to an external WD6TB drive (OP-54). But `rsync -a` without `-H` expanded internal hardlinks: `du` saw 3.9T but rsync transferred ~8T. The 5.2 TB WD6TB filled at 71%. Offload failed.

**Strategy pivot:** Instead of migrating orphans off pool (which requires matching storage), dedupe them: find orphan files whose content exists on stash library, hotspare, or WD6TB via cross-device SHA256 matching, and delete the pool copy. Zero data transfer.

The SHA256 upgrade scan just completed (21,943 files, 19,370 updated). Pool snapshot + pilot deletion freed ~875 GB. Pool now has 810G free. j50 runs the dedupe pipeline.

**After j50 frees ~2.2 TB:** Gate 4 batch resumes (OP-51) → canonicalize finishes → j42 Lane 2 strategy begins for 1030 ROOT_DRIFT + 2361 compound drift items. The canonicalize pipeline was suspended mid-Gate-4 for this dedupe detour; j50 is the wall we knock down to get back on track.

### Tasks

Tasks ordered working **backwards from the original goal** — simplest, highest-impact wins first:

| Task | Status | Goal |
|------|--------|------|
| j50-t01 | done (uncommitted) | Build hardlink-guard tool: `validate_orphan_hardlinks()` in `orphan_sweep.py` + `hashall orphan-validate --hardlink-guard` CLI + tests. 345 lines, 9/9 tests, written by agent on `opencode/deepseek-v4-flash-free`. |
| j50-t02 | planned (brief written) | **Repoint active clients referencing orphan paths** (known: f37b9983 `His.Three.Daughters.2024`). Before any deletion, ensure no torrent depends on orphan-dir data. Scan RT session dirs + qB cache for `/pool/media/torrents/orphans/` prefix; resolve canonical path via existing tooling; repoint RT via `rt_apply_directory_repoint()` and qB via `set_location()`. Brief at comms/briefs/TASK-BRIEF-j50-t02.md. |
| j50-t03 | planned | **Run hardlink-guard classification** via `hashall orphan-validate --hardlink-guard /pool/media/torrents/orphans/`. Output three-class report: Class A (hardlinked to seeder — safe to delete orphan link), Class B (unique orphans with SHA256 match on stash/hotspare/WD6TB — zero-copy delete), Class C (unique orphans with no cross-device match — requires rsync to hotspare first). |
| j50-t04 | planned | **Verify SHA256 coverage** — confirm hotspare has full SHA256 for cross-device matching. Already at 99.9% (39,320/39,347 files). If any gaps remain, run targeted `hashall scan --hash-mode upgrade` on the hotspare orphan_data subtree. WD6TB is intentionally excluded from dedupe — it was the failed offload target (incomplete partial copy, 0% SHA256, no authoritative value for matching). |
| j50-t05 | planned | **Delete Class A** — orphan files hardlinked to seeding content. `rm` the orphan-dir entries; seeder's hardlink retains data. No pool space recovered (seeder still holds the inode) but orphan dir shrinks. Run per ORPHAN-MIGRATION-PROCESS.md Step 2. |
| j50-t06 | planned | **Delete Class B** — unique orphans with SHA256-confirmed matches on hotspare (99.9% covered) or stash/media (79.2% covered). Zero-copy space recovery — the pure win. Query catalog for SHA256 matches across devices. Run per ORPHAN-MIGRATION-PROCESS.md Step 3. Expected recovery: ~1.2 TB from hotspare matches alone. |
| j50-t07 | planned | **Rsync Class C + verify + delete** — unique orphans with no cross-device match. `rsync -aH` to hotspare with hardlink preservation, verify with `rsync -aH --dry-run --delete --itemize-changes`, then delete from pool. Blocked if hotspare lacks capacity (741G free). Run per ORPHAN-MIGRATION-PROCESS.md Steps 4-5. |
| j50-t08 | planned | **Report and unblock** — document pool free space delta; confirm Gate 4 batch can resume (OP-51, ~237 remaining fix_placement_only items). Update JOB-QUEUE.md run order to advance j42. Close OP-57, OP-60, OP-61. Archive ORPHAN-MIGRATION-PROCESS.md as completed spec. |
| j50-t07 | planned | **Report and unblock** — document pool free space delta; confirm Gate 4 batch can resume (OP-51, ~237 remaining fix_placement_only items). Update JOB-QUEUE.md run order to advance j42. Close OP-57, OP-60, OP-61. Archive ORPHAN-MIGRATION-PROCESS.md as completed spec. |

---

## j51 — missingFiles-repair

**Slug:** missingFiles-repair
**OPs:** OP-62
**Goal:** Fix 440 qB torrents at missingFiles (0%) caused by stale save_path pointing to stash paths after rehome migration. Batch `set_location` to pool path + recheck. 265 single-file (fast fix: set_location to target file), 177 multi-file (need set_location to parent dir + recheck).
**Urgency:** High — missingFiles items cannot seed or be started.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j51-t01 | planned | Batch-scan qB for missingFiles torrents; extract current save_path and canonical pool path; generate set_location mapping; dry-run first, then apply with recheck |

---

## j52 — rt-qb-mirror-race

**Slug:** rt-qb-mirror-race
**OPs:** OP-58, OP-59
**Goal:** Investigate and fix the RT→qB mirror share-limit race that left 2 TorrentDay cross-seed items (Cold Case Files 2017 S01 a98fc34, The Bear S04 acb52ed) stalledUP in qB and PU in RT. Stop both in qB, repoint to pool path per `~noHL` tag, harden mirror workflow to prevent recurrence.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j52-t01 | planned | Investigate mirror flow; identify share-limit race or missed stop signal; stop both items in qB, repoint to pool path; harden `client-drift` mirror handler |

---

## j53 — repo-mastery-docs

**Slug:** repo-mastery-docs
**OPs:** OP-64
**Goal:** Full audit of all repo mastery documentation. Catalog every documented principle, rule, and invariant across REQUIREMENTS.md, AGENT-MASTERY.md, ARCHITECTURE.md, and related docs. Map existing mastery self-check questions to source principles. Write new questions for every gap. Verify every question has a correct, referenced answer. Target: every §1–§7 principle has at least one matching mastery self-check question. No undocumented gaps between stated policy and tested knowledge.
**Trigger:** j50-t06 planning — agent proposed repointing 55a3df42 to ef1071a1's stash path (violates §1.4 per-item payload invariant) because the mastery self-check (§8) had no question testing rehome payload-tree patterns (§5.3, §6.3). The pattern is fully documented in REQUIREMENTS.md but the agent lacked skill because the mastery check doesn't test it.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j53-t01 | planned | **Audit REQUIREMENTS.md** — catalog every principle, rule, invariant, constraint, and requirement. Group by section. For each: extract the canonical statement, note which AGENT-MASTERY.md question (if any) tests it. Output: master principle catalog with coverage gaps. |
| j53-t02 | planned | **Audit AGENT-MASTERY.md** — map existing self-check questions (Q1–Q8, now 8 total) to source principles. Audit the document body (sections 1–7) for every documented behavior/testable statement. Identify statements with no matching self-check question. Output: gap list of untested principles. |
| j53-t03 | planned | **Audit ARCHITECTURE.md and supporting docs** — scan ARCHITECTURE.md, REPO-MASTERY.md, CANONICALIZE-INTERFACE-MAP.md, 4-GATE-MUTATION-PROTOCOL.md, ORPHAN-MIGRATION-PROCESS.md for any principles not covered by REQUIREMENTS.md or AGENT-MASTERY.md. Output: supplementary principle list with source references. |
| j53-t04 | planned | **Write new self-check questions** — for every gap found in t01–t03, write a complete Q+N question and its answer. Each question must: (a) reference the source doc section, (b) test understanding of the principle not just memory, (c) have an answer that cites the source. Insert into AGENT-MASTERY.md §8. Update the "Answer all N" counters. |
| j53-t05 | planned | **Integration and end-to-end verify** — update all cross-references, section numbers, and question counts in AGENT-MASTERY.md. Run through all questions sequentially to verify each has a correct, reachable answer in the linked docs. Confirm no orphan references, broken section links, or stale counts. |

---

## Queue State Notes

JOB-QUEUE.md written 2026-06-26 by lead after opscan showed 32 unslotted OPs.
Replanned 2026-06-29 (j48-replan): all 17 open OPs now properly slotted in In-Job section.
Replanned 2026-07-01: slotted OP-61→j50, OP-62→j51, OP-58+OP-59→j52. Consolidated j49 into j50 — all 3 pool-dedupe OPs (OP-57, OP-60, OP-61) under one job per ORPHAN-MIGRATION-PROCESS.md. j49 marked OBE, branch deleted, worktree removed. Run order: j50→j51→j42→j39→j52→j43→j44→j45. j50-t01 code done (uncommitted, ported from j49 worktree). j52 parallel-eligible with j39.
Replanned 2026-07-02: added j53 (repo-mastery-docs, OP-64). Ordered next after j50. Trigger: agent proposed hitchhiker violation during j50-t06 planning because mastery self-check didn't test §1.4/§5.3/§6.3 rehome payload-tree invariant. Full doc audit briefed. AGENT-MASTERY.md Q8 + answer added as immediate hotfix.
