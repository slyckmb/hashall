# Job Queue — hashall CR

session: hashall-20260626-151456
branch: cr/hashall-20260626-151456
worktree: /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456
updated: 2026-07-07

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
| j49 | orphan-migration-guard | OP-57 | Merged to CR as superseded planning. OP-57 consolidated into j50; do not dispatch j49. |
| j53 | repo-mastery-docs | OP-64 | Merged to CR. commit 23d000c. |
| j54 | stoppeddl-tooling | OP-66 | Merged to CR. merge(cr/hashall-20260626-151456__j54). 
| j50 | orphan-safety-tooling-closeout | OP-57 | Merged to CR. merge(cr/hashall-20260626-151456__j50). |
| j57 | rt-qb-state-guard | OP-69 | Implemented on CR in `f06e944` with direct-CR workflow caveat. Guard tools/docs/prompts are usable now; root-cause follow-up remains open. |
| j51 | qb-stoppeddl-recovery | OP-62,OP-70,OP-78 | Active recovery planning blocked before live apply. RT-first worksheet complete, but first approved batch failed pre-apply verification; regenerate apply-compatible verified plan before mutation. |
| j52 | mirror-placement-anomalies | OP-58,OP-59,OP-63,OP-74 | Planned. Surgical mirror/rehome fixes for known small anomaly set plus RT/qB pause-state sync RCCA. |
| j55 | pool-orphan-dedupe-gated | OP-60,OP-61 | Planned. Dry-run/classify first; live deletion/rsync requires explicit operator approval. |
| j42 | lane2-strategy | OP-23,OP-26 | Planned after immediate qB/orphan blockers. |
| j39 | cross-seed-repair | OP-09,OP-15,OP-17,OP-19,OP-24,OP-47,OP-68 | Planned after lane strategy. |
| j43 | rt-state-monitor | OP-10,OP-12 | Planned infrastructure/state work after j57 guard. |
| j44 | chatrap-infra | OP-42,OP-45,OP-71,OP-72,OP-73,OP-77 | Planned orchestration/session/security reliability work. |
| j56 | link-plan-ux | OP-65 | Planned low-risk UX cleanup. |
| j45 | cr-to-main | OP-14 | Final merge only. |

---

## Dependencies

- j50 is a code/tooling closeout only. Do not run live orphan deletion or rsync in j50.
- j57 guard/enforcement exists and is usable. Any further live RT/qB repair mutation is still blocked unless it uses full 4-Gate or surgical mini-gate; stop-only qB containment remains the only exception.
- j51 requires j54 tooling and j57 guard/enforcement; both are satisfied. j51 live apply remains blocked until a fresh t09 plan identifies exact hashes/batches, includes the OP-70 RT-first source-of-truth gate, guard artifacts pass, and the operator explicitly approves.
- j52 should run after j51 so qB passive-state enforcement is already hardened; it handles a tiny known anomaly set (TorrentDay mirror race + Elemental duplicate).
- j55 must not mutate live storage until its dry-run/classification output is reviewed. Live deletion/rsync requires explicit operator approval.
- j42 and j39 remain downstream of immediate safety repairs and storage feasibility decisions.
- j45 is last — merge only after planned repair jobs complete.

---

## Run Order

j50 → j57 → j51 → j52 → j55 → j42 → j39 → j43 → j44 → j56 → j45

Notes:
- j48 (sha256-content-anchor) done — SHA256 backfill + _Sha256ContentMatcher + repoint_both_to_stash delivered; 83 blocked FPs resolvable
- j50 (orphan-safety-tooling-closeout) done — orphan hardlink guard + orphan repoint tooling merged to CR. No live orphan deletion or rsync was authorized in j50.
- j53 (repo-mastery-docs) done — OP-64 full audit delivered. 203 principles cataloged, 62 tested by Q1-Q8, 141 untested. 10 high-severity gaps identified.
- j54 (stoppeddl-tooling) done — OP-66 closed. 6 gaps fixed: pause_mirror_seeders extended, watchdog built, 4-Gate protocol updated, --extra-root-file added, --restore-from-backup added, verify-persistence.sh built. Hardened pipeline ready for j51 safety gate.
- j57 (rt-qb-state-guard) implemented in `f06e944` — OP-69 hardens the gap exposed by recurring RT/qB state regressions: existing tooling existed but ad hoc live repairs could bypass gate evidence, watchdogs, persistence checks, and prompt/brief enforcement. `chatrap ack commit HEAD` flags direct-CR workflow, but validation passed and tools are usable.
- j51 (qb-stoppeddl-recovery, OP-62/OP-70/OP-78) active recovery planning blocked before live apply — OP-62 started as 440 missingFiles. Current 2026-07-07 refresh: qB `stoppedDL=441`, `stoppedUP=4478`, `checking=0`, active upload/download=0; bucket `/tmp/qb-stoppeddl-bucket-live` has 441 hashes. DB refresh artifacts live under `.agent/reports/db-refresh-j51-20260707-045304/`. Correction after t07: generic catalog-drain policy was the wrong first lens; direct RT session mapping shows all 441 qB stoppedDL hashes are present in rTorrent and all 441 RT paths exist. RT-first worksheet is done, but t09 path-shape Class A evidence was not apply-compatible: dry-run selected 0, and first approved batch stopped on hash `376c463cd58324` because verifier found partial_match. No qB mutation ran. Next: regenerate a native verified drain/apply-compatible plan before any live apply.
- j52 (mirror-placement-anomalies) groups the small known mirror/rehome anomalies before broad strategy work: OP-58/59 TorrentDay race, OP-63 Elemental pool→stash hardlink payload rehome, and OP-74 RT/qB paused-100 sync mismatch/RCCA.
- j55 (pool-orphan-dedupe-gated) holds the high-risk pool orphan deletion/rsync work. It starts with dry-run/classification and stops for operator approval before deletion.
- j42 (lane2-strategy) after immediate blockers — quantifies Lane 2 scope for 1030 ROOT_DRIFT + 2361 compound drift items on POOL; decide STASH→POOL vs POOL→stash strategy using new library_dupe/repoint_both_to_stash tooling
- j39 (cross-seed-repair) after j42 — requires canonicalize drift items corrected (j46+j47+j48 done) and lane2 strategy settled; includes OP-68 RT `PD` holdouts/regression. 2026-07-05 surgical dry-runs keep `f9389496` and `8685d0e6` blocked because current RT directories lack required payload files.
- j43 (rt-state-monitor) — RT restart + qB cache daemon migration (OP-12 re-slotted from j40); depends on j57 for RT/qB guard primitives
- j44 (chatrap infra) — upstream fixes plus new friction from this session: enforce session goals, eliminate direct-CR S05 failures, stop secret leakage through process argv/logs, and fix `lead ship`/fallback dispatch false-success issues from OP-77.
- j56 (link-plan-ux) — low-risk UX cleanup for hardlink plan labels; can run whenever operational jobs are paused
- j45 (cr-to-main) — merge CR to main after all repair jobs done

## Brief Status

- Reusable existing briefs:
  - `comms/briefs/TASK-BRIEF-j50-t01.md`
  - `comms/briefs/TASK-BRIEF-j50-t02.md`
  - `comms/briefs/j51-t01-deep-dive.md`
  - `comms/briefs/j51-t02-stoppeddl-sop.md`
  - `comms/briefs/TASK-BRIEF-j54-t01.md` through `TASK-BRIEF-j54-t06.md` (already executed/merged)
- Current j51 briefs:
  - `j51-t04` state refresh only — done by lead read-only refresh
  - `j51-t05` tool/readiness audit only — done by lead read-only refresh
  - `j51-t06` bucket sync only — done by lead read-only refresh
  - `j51-t07` tiny drain pilot — done by lead read-only refresh; no Class A candidates in first 10
  - `j51-t08` RT→qB repair worksheet — done by lead read-only refresh
  - `j51-t09` execution-plan synthesis — done; approval plan copied to `.agent/reports/j51-ship-20260708/`
  - `j51-t10` live execution — blocked; first approved batch failed pre-apply verification before mutation
  - `j52-t01` mirror/rehome anomaly investigation
  - `j55-t01` orphan dry-run/classification
  - `j55-t02+` live deletion/rsync briefs only after operator approval

---

## j57 — rt-qb-state-guard

**Slug:** rt-qb-state-guard
**OPs:** OP-69
**Goal:** Make RT/qB live-state mutation safe by default. Any future live torrent-state mutation must use either the full 4-Gate protocol or a hash-scoped surgical mini-gate; direct helper/API/XMLRPC mutation is forbidden except qB stop-only containment.
**Urgency:** Highest — j51 live recovery and j39 RT repair must not proceed through informal manual repair paths again.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j57-t01 | done | Updated canonical docs: 4-Gate scope, RT/qB state policy, stoppedDL SOP, and surgical repair runbook. Defined stop-only containment, surgical mini-gate artifacts, and abort rules. |
| j57-t02 | done | Built `bin/rt-surgical-repair.py`: explicit-hash RT repoint/hash-check/start wrapper that verifies torrent metadata, handles single-file vs multi-file target semantics, blocks missing files, writes reports, and never starts incomplete items. |
| j57-t03 | done | Built `bin/rt-qb-state-guard.py`: baseline/check/watch/report for RT non-ideal states, stale/missing directories, qB active upload/download, qB stoppedDL deltas, and checking backlog. |
| j57-t04 | done | Updated prompts, mastery, INIT/QUICKSTART, and brief guidance so RT/qB mutation briefs must declare gate type, exact hashes, allowed commands, required artifacts, and stop conditions. |
| j57-t05 | done | Added focused tests and smoke validation for the surgical wrapper, state guard, qB passive enforcement, and existing safe-start behavior. Validation: 28 focused tests passed. |
| j57-t06 | done | Replanned j51/j39 after guard completion: j51 live apply remains blocked until t09 approval plan and guard artifacts pass; j39 RT PD repairs use the new surgical wrapper only. |

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

## j50 — orphan-safety-tooling-closeout

**Slug:** orphan-safety-tooling-closeout
**OPs:** OP-57
**Goal:** Close the already-built orphan safety tooling branch. This job is code/tooling only: hardlink guard + orphan-path repoint tooling + tests. It must not delete, rsync, or mutate live storage.

### Why we're here (the chain back to the original goal)

The original goal was **enforce §4.4 placement policy** — move cross-seed content from stash to pool, where it belongs. j47 Gate 4 batch was doing this: 428 stash→pool moves completed before **pool hit 0 bytes**. The batch stopped mid-flight.

The pool was full because `/pool/media/torrents/orphans/` was hoarding **3.9 TB** (`du`). Plan A was to offload orphans to an external WD6TB drive (OP-54). But `rsync -a` without `-H` expanded internal hardlinks: `du` saw 3.9T but rsync transferred ~8T. The 5.2 TB WD6TB filled at 71%. Offload failed.

**Strategy pivot:** Instead of migrating orphans off pool (which requires matching storage), dedupe them: find orphan files whose content exists on stash library, hotspare, or WD6TB via cross-device SHA256 matching, and delete the pool copy. Zero data transfer.

The SHA256 upgrade scan completed (21,943 files, 19,370 updated). Pool snapshot + pilot deletion freed ~875 GB. Pool had 810G free at that checkpoint. The live dedupe pipeline is now scheduled in j55, not j50.

The original broad j50 mixed tooling, live deletion, rsync, and rehome work. This replan splits those apart. j50 now only closes the rebased tooling branch. Live orphan dedupe moved to j55; mirror/rehome anomalies moved to j52.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j50-t01 | done (job branch) | Build hardlink-guard tool: `validate_orphan_hardlinks()` in `orphan_sweep.py` + `hashall orphan-validate --hardlink-guard` CLI + tests on the rebased `cr/hashall-20260626-151456__j50` branch. |
| j50-t02 | done (job branch) | **Repoint active clients referencing orphan paths** (known: f37b9983 `His.Three.Daughters.2024`). Tooling and tests completed on the rebased `cr/hashall-20260626-151456__j50` branch. |
| j50-t03 | planned | Lead review of the rebased j50 diff, confirm focused tests and S05 checks, then close/merge j50. |

---

## j54 — stoppeddl-tooling

**Slug:** stoppeddl-tooling
**OPs:** OP-66
**Goal:** Close 6 stoppedDL pipeline tooling gaps identified by DSV4 Pro analysis in `comms/docs/STOPPEDDL-SOP.md`. Harden the `bucket→drain→apply→roundloop` pipeline so that 425 stoppedDL-at-0% torrents never recur after ad-hoc repair. Build the missing tools: watchdog, persistence verifier, and mass-backup rollback. Extend existing tools for download-state coverage and curated candidate paths. Update 4-Gate protocol to mandate pause_mirror_seeders.py enforcement.

### Why this matters

425 qB torrents accumulated at stoppedDL 0% because the pipeline was bypassed during ad-hoc repair. Active downloads re-emerged post-stop. The 6 gaps are:

| Gap | Tool | Issue |
|-----|------|-------|
| GAP-1 | `scripts/pause_mirror_seeders.py` | Only handles upload states — download states (stalledDL, downloading, forcedDL) go undetected |
| GAP-2 | **NEW** `bin/qb-stoppeddl-watchdog.py` | No post-mutation guard that detects emergent stoppedDL during active repair |
| GAP-3 | `docs/4-GATE-MUTATION-PROTOCOL.md` | Gate 4 doesn't mandate pause_mirror_seeders.py enforcement |
| GAP-4 | `bin/qb-stoppeddl-drain.py` | Missing `--extra-root-file` for curated candidate path lists |
| GAP-5 | `bin/qb-stoppeddl-rollback.py` | No mass restore-from-backup for catastrophic fastresume corruption |
| GAP-6 | **NEW** `bin/qb-stoppeddl-verify-persistence.sh` | No tool validates repaired torrents survive qB restart (Feb-2026 disaster: 2103 reverted to stoppedDL) |

### Tasks

| Task | Type | Goal |
|------|------|------|
| j54-t01 | implementation | GAP-1: Extend `scripts/pause_mirror_seeders.py` to detect download states (stalledDL, downloading, forcedDL) in addition to upload states; add --dry-run, --states override, --report-json. Brief: TASK-BRIEF-j54-t01-pause-mirror-download-states.md |
| j54-t02 | implementation | GAP-2: Build NEW `bin/qb-stoppeddl-watchdog.py` — poll qB for emergent stoppedDL during mutation; pause on detection; optional --auto-repair triggers drain+apply; JSONL journal. Brief: TASK-BRIEF-j54-t02-stoppeddl-watchdog.md |
| j54-t03 | implementation | GAP-3: Update `docs/4-GATE-MUTATION-PROTOCOL.md` Gate 4 to mandate pause_mirror_seeders.py before/after each batch; bump to v1.1.0. Brief: TASK-BRIEF-j54-t03-gate4-pause-mirror-enforcement.md |
| j54-t04 | implementation | GAP-4: Add `--extra-root-file` flag to `bin/qb-stoppeddl-drain.py` (reads candidate paths from file, one per line, # comments); bump to 0.1.25. Brief: TASK-BRIEF-j54-t04-drain-extra-root-file.md |
| j54-t05 | implementation | GAP-5: Add `--restore-from-backup` mode to `bin/qb-stoppeddl-rollback.py` — stop qB, mass-restore .fastresume.bak files, restart; bump to 0.1.2. Brief: TASK-BRIEF-j54-t05-rollback-restore-from-backup.md |
| j54-t06 | implementation | GAP-6: Build NEW `bin/qb-stoppeddl-verify-persistence.sh` — take pre/post restart state snapshots, flag reverted-to-stoppedDL hashes, investigate qBt-downloadPath. Brief: TASK-BRIEF-j54-t06-verify-persistence-restart.md |

### Task ordering

t01 (GAP-1) → t03 (GAP-3, depends on t01 tool existing) → t02 (GAP-2, watchdog can reference t01 output format).
t04, t05, t06 are independent and can run in parallel with t01–t03.
Recommended dispatch order: t01 → t04 → t05 → t06 → t03 → t02.

---

## j51 — qb-stoppeddl-recovery

**Slug:** qb-stoppeddl-recovery
**OPs:** OP-62, OP-70
**Goal:** Recover the qB mirror fallout from the stale save_path repair. Current evidence says the original 440 missingFiles count reached 0, but many items transitioned into stoppedDL/checking and require the hardened j54 stoppedDL pipeline. Keep qB passive: zero active downloads/uploads/stalledUP.
**Urgency:** High — qB mirror state is operationally noisy and can regress if not drained with the hardened tools.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j51-t01 | done (exploratory) | Analyze missingFiles repair options. Recommended COA: offline fastresume batch patch from RT session directory mapping, then qB recheck with rollback via `.fastresume.bak-j51`. Log: `.agent/logs/hashall-20260626-151456/j51/j51-t01-opencode.log`. |
| j51-t02 | done (exploratory/spec) | Document stoppedDL SOP/tooling for the observed missingFiles→stoppedDL fallout. j54 implemented the six tooling gaps from this spec. Log: `.agent/logs/hashall-20260626-151456/j51/j51-t02-opencode.log`. |
| j51-t03 | blocked (audit) | Current-state audit completed enough to block mutation: qB reachable; counts were `checkingDL=4`, `checkingUP=3080`, `stoppedDL=432`, `stoppedUP=1394`, `missingFiles=0`. Report: `comms/reports/J51-T03-CURRENT-STATE-AUDIT.md` in the j51 worktree. |
| j51-t04 | done (lead read-only refresh) | qB refresh 2026-07-07 after DB refresh: `stoppedDL=441`, `stoppedUP=4478`, `checking=0`, active upload/download=0. Guard baseline/check artifacts: `.agent/reports/db-refresh-j51-20260707-045304/rt-qb-baseline-after-db-refresh.json`, `.agent/reports/db-refresh-j51-20260707-045304/rt-qb-check-after-db-refresh.json`. Guard check flagged one new RT tracker-error item unrelated to qB stoppedDL. |
| j51-t05 | done (lead read-only refresh) | Tool/readiness refresh passed for rollback, persistence verifier, pause enforcement, watchdog, RT/qB guard, and RT surgical wrapper. Report: `.agent/reports/rt-qb-guard-20260705-232752/j51-tool-readiness-refresh.md`. |
| j51-t06 | done (lead read-only refresh) | Bucket sync refreshed `/tmp/qb-stoppeddl-bucket-live`: 441 active stoppedDL hashes, 441 index entries, 0 missing/pruned. Report: `/tmp/qb-stoppeddl-bucket-live/reports/sync-20260707-051113.json`. |
| j51-t07 | done (lead read-only pilot) | Tiny generic drain pilot processed 10 hashes after catalog refresh and found no Class A candidates under strict root/filesystem policy. Follow-up direct RT session map supersedes this as the primary repair lens: all 441 qB stoppedDL hashes are present in RT and all 441 RT paths exist. Reports: `.agent/reports/db-refresh-j51-20260707-045304/j51-t07-drain-pilot.json`, `.agent/reports/db-refresh-j51-20260707-045304/j51-rt-qb-session-map.json`. |
| j51-t08 | done (lead read-only RT worksheet) | RT→qB worksheet built for all 441 hashes. All 441 qB stoppedDL hashes are present in RT and all RT paths exist. Worksheet summary: 182 clean multi-file parent targets; 259 need offline torrent-shape verification before choosing RT directory vs parent as qB save path. Report: `.agent/reports/db-refresh-j51-20260707-045304/j51-rt-qb-repair-worksheet.json`. |
| j51-t09 | done (lead approval plan) | Execution plan synthesis completed from t08 plus OP-70 source-of-truth gate. Plan: 441 total stoppedDL worksheet hashes; 182 Class A `multifile_parent_of_info_name` candidates in `J51-T09-CLASS-A-HASHES.txt`; 259 `directory_as_save_path_needs_verify` items held for offline torrent-shape verification. Batch size: 25. Report copied to `.agent/reports/j51-ship-20260708/J51-T09-EXECUTION-PLAN.md`. |
| j51-t10 | blocked (pre-apply verification) | Operator approved first 25 Class A hashes, but no live qB mutation ran. Apply dry-run selected 0 because the t09 worksheet is not a native drain report. Offline verification then stopped on hash `376c463cd58324cdb1b5645930227055b3053837`: verifier reported `partial_match`, `expected_files=3`, `actual_files=6`, `exact_tree=false`, `verified=false`. Updated blocked report copied to `.agent/reports/j51-ship-20260708/J51-T10-GUARDED-EXECUTION.md`. Next: regenerate an apply-compatible verified plan. |

---

## j44 — chatrap-infra

**Slug:** chatrap-infra
**OPs:** OP-42, OP-45, OP-71, OP-72, OP-73
**Goal:** Fix orchestration reliability gaps that hide friction, allow workflow bypass, or leak sensitive runtime data.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j44-t01 | planned | Fix OP-42: make after-job scan opencode/Pi/direct logs and artifact dirs for task-log/friction/ops_closed blocks; preserve logs under `.agent/logs/<session>/<job>/`. |
| j44-t02 | planned | Fix OP-45 class: enforce explicit hash allowlists/exclusion lists in torrent-state mutation briefs and dispatch wrappers so agents cannot act on visible-but-out-of-scope stopped torrents. |
| j44-t03 | planned | Fix OP-71: make chatrap session tracking refuse or loudly warn on meaningful work with unset `goal`; provide safe goal recovery from current step/evidence. |
| j44-t04 | planned | Fix OP-72: hard-block direct-CR project commits or provide an explicit lead tracking-commit path that records equivalent task-log/friction metadata and passes S05. |
| j44-t05 | planned | Fix OP-73: remove qB password/user from payload-sync argv/logging; use env/config/cookie loading and add a smoke test proving `ps`/logs do not expose qB secrets. |

---

## j52 — rt-qb-mirror-race

**Slug:** mirror-placement-anomalies
**OPs:** OP-58, OP-59, OP-63, OP-74
**Goal:** Resolve the small known mirror/rehome anomaly set before broad drift work: two TorrentDay mirror race items, one Elemental pool→stash duplicate, and the new RT paused-100 vs qB not-paused-100 sync mismatch. Keep scope narrow and explicit.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j52-t01 | planned | Investigate RT/qB state for the two TorrentDay hashes; stop any qB active states; identify mirror share-limit race or missed stop signal. |
| j52-t02 | planned | Repoint the two TorrentDay items to their correct pool path per `~noHL`, with RT/qB post-checks and no broad scan. |
| j52-t03 | planned | Rehome Elemental.2023 pool duplicate to stash with unique payload tree and hardlink payload per REQUIREMENTS §1.4/§5.3/§6.3. |
| j52-t04 | planned | Harden the mirror workflow or write a precise follow-up OP if root cause is outside this narrow fix scope. |
| j52-t05 | partially done | Investigated OP-74: no mirror-add flip found; qB mirror imports are still added stopped. Hardened `scripts/pause_mirror_seeders.py` so legacy `pausedUP` is acceptable and post-stop live qB state is recorded, with focused tests. Remaining: identify why `f4a6a8` drifted before enforcement caught it. |

---

## j55 — pool-orphan-dedupe-gated

**Slug:** pool-orphan-dedupe-gated
**OPs:** OP-60, OP-61
**Goal:** Resume pool orphan dedupe safely after immediate qB/mirror blockers are handled. This job is explicitly gated: dry-run/classification first, then stop for operator approval before any deletion or rsync.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j55-t01 | planned | Add or verify quick-hash cross-device analysis path for orphan dedupe. If already implemented, document the exact command and evidence. |
| j55-t02 | planned | Run read-only hardlink-guard/classification against `/pool/media/torrents/orphans/`: Class A hardlinked orphan links, Class B cross-device confirmed duplicates, Class C no confirmed duplicate. |
| j55-t03 | planned | Produce deletion/rsync manifest with byte counts, source-of-truth evidence, rollback constraints, and pool free-space forecast. No mutation. |
| j55-t04 | approval gate | Stop for explicit operator approval before any `rm`, `rsync --remove-source-files`, `mv`, or live client mutation. |
| j55-t05 | planned after approval | Execute approved Class A/Class B deletion in small batches with pre/post catalog scan and pool free-space report. |
| j55-t06 | planned after approval | Execute Class C rsync only if capacity and dry-run verification pass; use `rsync -aH`, verify, then delete source only after proof. |

---

## j56 — link-plan-ux

**Slug:** link-plan-ux
**OPs:** OP-65
**Goal:** Make hardlink-plan output labels less misleading. This is low-risk code/UX work and can run when operational jobs are paused.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j56-t01 | planned | Audit `hashall link show-plan` and `link execute --dry-run` output labels for directional wording. |
| j56-t02 | planned | Replace misleading "Keep"/"Replace" language or add a clear note that hardlinks are non-directional and all paths to the same inode are equal. |
| j56-t03 | planned | Add/adjust focused output tests. |

---

## j53 — repo-mastery-docs

**Slug:** repo-mastery-docs
**OPs:** OP-64
**Goal:** Full audit of all repo mastery documentation. Catalog every documented principle, rule, and invariant across REQUIREMENTS.md, AGENT-MASTERY.md, ARCHITECTURE.md, and related docs. Map existing mastery self-check questions to source principles. Write new questions for every gap. Verify every question has a correct, referenced answer. Target: every §1–§7 principle has at least one matching mastery self-check question. No undocumented gaps between stated policy and tested knowledge.
**Trigger:** j50-t06 planning — agent proposed repointing 55a3df42 to ef1071a1's stash path (violates §1.4 per-item payload invariant) because the mastery self-check (§8) had no question testing rehome payload-tree patterns (§5.3, §6.3). The pattern is fully documented in REQUIREMENTS.md but the agent lacked skill because the mastery check doesn't test it.
**Status:** Merged to CR in `23d000c`.

### Tasks

| Task | Status | Goal |
|------|--------|------|
| j53-t01 | done | Audit REQUIREMENTS.md and produce principle coverage catalog. |
| j53-t02 | done | Audit AGENT-MASTERY.md and map self-check coverage. |
| j53-t03 | done | Audit supporting docs and supplementary principles. |
| j53-t04 | done | Write/integrate mastery coverage updates. |
| j53-t05 | done | Integration and end-to-end verify. |

---

## Queue State Notes

JOB-QUEUE.md written 2026-06-26 by lead after opscan showed 32 unslotted OPs.
Replanned 2026-06-29 (j48-replan): all 17 open OPs now properly slotted in In-Job section.
Replanned 2026-07-01: slotted OP-61→j50, OP-62→j51, OP-58+OP-59→j52. Consolidated j49 into j50 — all 3 pool-dedupe OPs (OP-57, OP-60, OP-61) under one job per ORPHAN-MIGRATION-PROCESS.md. j49 marked OBE, branch deleted, worktree removed. Run order: j50→j51→j42→j39→j52→j43→j44→j45. j50-t01 code done (uncommitted, ported from j49 worktree). j52 parallel-eligible with j39.
Replanned 2026-07-02: added j53 (repo-mastery-docs, OP-64). Ordered next after j50. Trigger: agent proposed hitchhiker violation during j50-t06 planning because mastery self-check didn't test §1.4/§5.3/§6.3 rehome payload-tree invariant. Full doc audit briefed. AGENT-MASTERY.md Q8 + answer added as immediate hotfix.
Replanned 2026-07-03: added j54 (stoppeddl-tooling, OP-66). Ordered after j53, before j51. Trigger: 425 qB stoppedDL-at-0% torrents accumulated after ad-hoc repair bypassed pipeline. DSV4 Pro identified 6 tooling gaps in STOPPEDDL-SOP.md. 6 task briefs written in comms/briefs/TASK-BRIEF-j54-t0*.md. Run order: j53→j54→j51. All 6 tasks fully briefed and ready for dispatch.
Replanned 2026-07-03 (logical safety replan): split j50 into tooling-only closeout (OP-57), j51 qB stoppedDL recovery (OP-62), j52 mirror/rehome anomaly fixes (OP-58/59/63), j55 gated orphan dedupe (OP-60/61, approval before live deletion/rsync), and j56 low-risk link-plan UX (OP-65). Run order: j50→j51→j52→j55→j42→j39→j43→j44→j56→j45.

Replanned 2026-07-03 (weak-model j51 split): j51-t03 audit blocked mutation because qB still had `checkingUP=3080` and `checkingDL=4`. Split broad recovery work into smaller dispatch slices: t04 state refresh only, t05 tool readiness only, t06 bucket sync only, t07 tiny drain pilot, t08 full read-only drain, t09 execution-plan synthesis, t10 approval-gated live execution. This avoids asking weak/free models to reason over qB state, tool readiness, drain policy, and mutation planning in one task.
Replanned 2026-07-07 (session-friction capture): added OP-70 to j51 after the lead used the wrong generic catalog-drain lens before checking RT truth; t09 must now include an explicit RT-first source-of-truth gate. Added OP-71/OP-72/OP-73 to j44 for chatrap session goal enforcement, direct-CR S05 failures, and qB secret leakage through payload-sync argv/logging.
