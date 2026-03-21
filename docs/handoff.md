# Handoff Notes

## 2026-03-21 Rehome qB Runtime Settle Fix (same branch)

### What changed
The `West Wing` pilot had already proved the data path was good. The remaining failure was the
post-patch qB runtime handoff after restart: `.fastresume` was correctly patched to `/pool/media`,
but runtime verification could still see stale `/pool/data` information during qB restart jitter.

### Code fixes in this sub-session
- `src/rehome/executor.py`
  - hardened fastresume post-patch now waits for qB restart/authentication
  - runtime `save_path` verification now requires live qB API data and ignores cache-fallback
    reads during verification
  - if runtime `save_path` stays stale after a good patch, executor retries with an explicit
    `set_location(expected_save_path)` nudge before failing
  - post-patch accounting now waits for qB to settle, but still fails fast for definite bad
    states like `pausedDL`, `stoppedDL`, or nonzero `amount_left`
- tests
  - added regressions for cache-fallback save-path polling
  - added regressions for post-patch accounting settle
  - added regressions for stale runtime `save_path` recovered by reapplying the target location

### Simulation / dry-run status
- targeted simulation suite:
  - `pytest tests/test_rehome_catalog_sync.py tests/test_rehome_atomic_relocation.py tests/test_rehome_normalize.py -q`
  - result: `81 passed`
- live dry-run:
  - `/home/michael/.venvs/hashall/bin/python -m hashall.cli rehome apply out/rehome-plan-west-wing-s02-2026-03-21-v087.json --dryrun`
  - completed cleanly

### Operational conclusion
- The remaining `West Wing` issue was a qB runtime settle bug, not another data-move bug.
- Next step is to rerun the same real `West Wing` pilot with `0.8.8`.

## 2026-03-21 Rehome Content Identity Hardening (same branch)

### What changed
The previous fix set still had one important blind spot: target-family reuse could treat a family
as reusable when sibling roots matched only by file count and total bytes. That was not enough for
real-world payloads like `Shining.Girls...`, where two `/pool/media` sibling roots had the same
shape but different bytes.

### Code fixes in this sub-session
- `src/rehome/content_identity.py`
  - new helper that computes a payload hash from the live filesystem bytes with inode-based hash
    caching, so hardlinked siblings do not get rehashed repeatedly
- `src/rehome/normalize.py`
  - planner target-family inspection now compares actual content before choosing `REUSE`
  - conflicting same-size roots now count as real target-family conflicts
- `src/rehome/executor.py`
  - executor target-family inspection now uses the same content proof
  - apply blocks before any work when alternate target-side siblings are content-divergent
  - stale-source reuse fallback is preserved when the source root is already gone
- tests
  - added regressions for same-size/different-content target roots and reuse-family preflight
    blocking

### Simulation / dry-run status
- targeted simulation suite:
  - `pytest tests/test_rehome_normalize.py tests/test_rehome_atomic_relocation.py tests/test_rehome_catalog_sync.py -q`
  - result: `78 passed`
- compile check:
  - `python3 -m py_compile src/rehome/content_identity.py src/rehome/normalize.py src/rehome/executor.py`
  - result: passed
- live dry-run:
  - `West Wing S02` remains a clean `MOVE`
- live plan generation:
  - `Shining.Girls...` now hashes real files to prove reuse and is therefore materially slower than
    the old count/byte heuristic

### Operational conclusion
- `Shining.Girls...` is confirmed as a real target-side content conflict on `/pool/media`, not a
  planner hallucination
- `West Wing` is still the best current live `MOVE` pilot for proving the end-to-end rehome lane

## 2026-03-20 Rehome Planner/Executor Hardening (same branch)

### Root cause confirmed
The real `West Wing S02` apply on 2026-03-20 copied ~71 GB and then failed on a target-side
`Aither (API)` sibling conflict. The real bug was not rsync. It was that the planner/executor
treated one canonical target root as the whole truth:

- planner chose `MOVE` when that one canonical target root was absent
- it ignored alternate sibling target views already present on `/pool/media`
- target-view “preflight” was not actually read-only; it could relink identical files
- rollback then deleted a pre-existing good target-side sibling view because it did not track
  whether a view existed before the run

### Code fixes in this sub-session
- `src/rehome/normalize.py`
  - planner now inspects the whole target family and reuses an exact existing target-side sibling
    as the donor when one exists
- `src/rehome/executor.py`
  - family-level target inspection now runs before donor acquisition
  - alternate conflicting target siblings now block `MOVE` before rsync
  - rollback now only removes target views created during the current run
  - move failures now write both `failure-pre-rollback` and `failure-post-rollback` reality
    snapshots
- `src/rehome/view_builder.py`
  - target-view preflight now compares existing targets without relinking them

### Simulation / dry-run status
- targeted simulation suite:
  - `pytest tests/test_rehome_normalize.py tests/test_rehome_atomic_relocation.py tests/test_rehome_catalog_sync.py -q`
  - result: `76 passed`
- module compile check:
  - `python3 -m py_compile src/rehome/normalize.py src/rehome/view_builder.py src/rehome/executor.py`
  - result: passed
- fresh live dry-run (2026-03-20):
  - `Shining.Girls...` = `REUSE`
  - `The.West.Wing.S02...` = `MOVE`
  - `Alien Romulus` = `MOVE`

### Current important live fact
- the previously good `/pool/media` `West Wing` donor is already gone from the earlier buggy run
- therefore the fresh `West Wing` plan correctly has no reusable target-side donor right now
- if you want a real reuse/reconcile pilot, use `Shining.Girls...`, not `West Wing`

## 2026-03-19 Migration Audit + Bug Fixes (same branch)

### Stale lock cleared
`~/.hashall/rehome.lock` pid 3888189 confirmed dead and removed. Migration is now unblocked.

### qB consecutive_failures counter bug fixed
`src/hashall/qb_cache.py`: `_write_meta` on successful fetch did not include
`consecutive_failures: 0`, so the 640-failure count from a prior qB outage persisted
in the meta file even after recovery (`source=daemon_live`, fresh cache). Fixed: both
the `daemon_once` and `daemon_live` success paths now explicitly write `consecutive_failures: 0`.
Test added: `test_daemon_once_resets_consecutive_failures_on_success`.

### Other fixes in this sub-session
- `bin/qb-checking-watch.sh` help text: `--interval` and `--cache-max-age` both said
  `"default: 15"` but actual defaults are `30`. Corrected.
- `bin/qb-stoppeddl-apply-watch.sh`: default `BUCKET_DIR` changed from
  `/tmp/qb-stoppeddl-bucket-live` (volatile) to `~/.hashall/qb-stoppeddl-bucket`.
- `bin/migrate-pool-data-to-media_common.sh:14`: added portability comment to
  `FASTRESUME_DIR` host-specific default.
- `docs/operations/RUN-STATE.md`: updated opening version line from `0.8.0` to `0.8.5`.
- `src/hashall/__init__.py`: version bumped to `0.8.5`.

### Migration readiness (post-fixes)
- Lock: cleared ✓
- qB API: healthy (cache fresh, failure counter now resets correctly after recovery)
- Migration scripts: `bin/migrate-pool-data-to-media.sh` ready for Phase 1 plan generation
- Next step: run Phase 0→1 workflow (see RUN-STATE.md "2026-03-19 Migration Analysis")

---

## 2026-03-19 Migration Analysis (same branch)

Pool-data → pool-media migration is still `in_progress` with two blockers.

**Live counts:**
- `old_path_count=41` pool-data torrents (up from 34 in Mar-13 docs; all `stalledUP`)
- `new_path_count=344` pool-media torrents

**Blockers before resuming:**
1. Stale `~/.hashall/rehome.lock` — 5 days old (2026-03-14 10:02). Verify process dead, then `rm`.
2. 640 consecutive qB API failures in cache meta. Cache itself is fresh (`source=daemon_live`, `2026-03-19T15:32`). Investigate `last_error` and confirm live API responds before trusting plan output.

**Resumption order:**
1. Phase 0: clear lock, verify qB health, `hashall refresh --verbose`
2. Phase 1: `hashall rehome relocate-plan --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding --output out/rehome-plan-pool-data-to-media-2026-03-19.json`; audit coverage vs. 41 qB pool-data hashes
3. Phase 2: execute in small curated batches

**Special-case audit update (2026-03-19):**
- The live `41` remaining `/pool/data` qB rows are split across three path families:
  - `8` under `/pool/data/media/torrents/seeding`
  - `28` under `/pool/data/cross-seed-link`
  - `5` under `/pool/data/cross-seed`
- Dry-running `bin/migrate-pool-data-to-media.sh` only selected the `8` rows under the exact
  wrapper source root. It is therefore **not** the full 41-row resume command as currently wired.
- That dry-run also included `Alien Romulus` (`1376e795...`), which remains a deliberate
  repair/proving-lane item and should stay out of plain migration batches.
- `Shining.Girls...` also remains unresolved as a bad reuse candidate and should stay excluded
  from plain migration batches until it is explicitly re-audited.

**Code notes for new plan:** 2026-03-18/19 audit fixes (bind-mount false-positive, unique-view single-torrent) may reclassify some previously-BLOCKED candidates. No executor logic changed.

**Out/ plan files:** plan files live in the main repo, not this worktree. Run plan generation from main repo or copy output after.

---

## 2026-03-18/19 Audit Session (branch: cr/claude-hashall-20260318-232039)

### What happened
Full code audit against `docs/REQUIREMENTS.md` (which was itself updated to v1.1 in this session).
Five bugs found; five fixed across two commits. Tests written for all fixes. No regressions
(636 pass; 13 pre-existing failures unrelated to this work).

### REQUIREMENTS.md v1.1 (docs/REQUIREMENTS.md)
- Gap analysis of ~30 items applied: §2.5 Seeding Domain, §2.6 Seed-Root State Contract added;
  ZFS pool topology table added; `~noHL` advisory-only note; hitchhiker invariant; staged cleanup
  model; drift policy tables; fastresume-preferred qB integration; reality snapshots; partial
  reconcile exception; 14 new glossary terms; §11 roadmap updated.

### Bug fixes in this session (commits 3fd06c0 and b88343f)

#### HIGH — followup.py: GOOD_STATES missing 'stoppedup'
- File: `src/rehome/followup.py` line 31
- Before: `{"uploading", "stalledup", "queuedup", "forcedup", "pausedup"}`
- After: added `"stoppedup"` — without this, paused-after-rehome torrents (state=stoppedUP,
  normal operator behavior) permanently accumulate `.rehome-cleanup-stage/` directories.
- Test: `tests/test_rehome_followup.py::test_followup_cleanup_passes_gate_when_torrent_is_stoppedup`

#### MEDIUM — scan.py: nested dataset scan dropped drift_policy
- File: `src/hashall/scan.py` (~line 2025)
- `--drift-policy=full/quick` silently fell back to `metadata` for all nested ZFS datasets.
- Fix: added `drift_policy=drift_policy` to the recursive `scan_path` call.
- Test: `tests/test_scan_hardlinks.py::test_drift_policy_forwarded_to_nested_dataset_scan`

#### MEDIUM — planner.py: bind-mount false-positive BLOCK on external consumer detection
- File: `src/rehome/planner.py`
- Two sub-fixes:
  1. `_normalize_abs_path` now calls `canonicalize_path` instead of `path.resolve()` so
     bind-alias hardlink paths (/data/media/...) are mapped to canonical form (/stash/media/...)
     before seeding-domain comparison.
  2. Legacy-table DB prefix query now uses original `root_path` string (pre-canonicalization)
     rather than `str(root)` (post-canonicalization) — canonicalized prefix wouldn't match
     rows stored under the bind alias.
- Test: `tests/test_rehome.py::TestExternalConsumerDetection::test_external_consumer_no_false_positive_when_hardlink_under_bind_alias`

#### LOW — planner.py: single-torrent bypass of unique-view scheme
- File: `src/rehome/planner.py` `_build_view_targets()`
- `if len(raw_targets) <= 1: return raw_targets` bypassed the `_rehome-unique/<hash>` scheme
  for single-torrent payloads. Risk: collision when two single-torrent payloads share
  `root_name`; state mismatch when payload gains a cross-seed after initial demotion.
- Fix: changed `<= 1` to `== 0` so single-torrent payloads also use unique-view.
- Updated test: `tests/test_rehome_mapping.py::test_plan_includes_view_targets`
  (expected path updated to `/pool/data/_rehome-unique/torrent_map`)

#### LOW — qb_cache.py: daemon URL env var gap
- File: `src/hashall/qb_cache.py` `daemon_main()`
- Daemon only read `QBIT_URL`; `qbittorrent.py` falls back through `QBITTORRENT_API_URL`
  → `QBITTORRENT_URL` → `QBITTORRENT_HOST` → `QBITTORRENTAPI_HOST`. Setting any standard
  var had no effect on the cache daemon.
- Fix: daemon now tries the full fallback chain before defaulting to `http://localhost:9003`.

### Version after this session
- `hashall` semver: `0.8.4` (bumped in `src/hashall/__init__.py`)
- Branch commits: `3fd06c0` (HIGH+MEDIUM fixes), `b88343f` (LOW fixes)

### Test baseline after this session
- 636 passed, 13 pre-existing failures (not introduced by this session):
  - `test_scan_integration.py` (7): findmnt -T resolves /tmp through /dev/nvme0n1p7 on this host
  - `test_codex_says_run_this_next_script.py` (4): pre-existing
  - `test_payload_auto_workflow.py` (2): pre-existing

---

## Key Facts

- `hashall` semver baseline is now `0.8.4` (was 0.8.0 before this audit session).
- New 2026-03-15 qB compatibility/cache baseline:
  - `hashall` now owns a local qB shared-cache implementation:
    - `src/hashall/qb_cache.py`
    - `bin/qb-cache-agent.py`
    - `bin/qb-cache-daemon.py`
  - the local cache no longer depends on qbitui’s external raw-API cache scripts
  - qB server/profile detection now lives in `src/hashall/qbittorrent.py`
  - current normalized compatibility contract:
    - probe `app/version`
    - probe `app/webapiVersion` when available
    - probe `app/buildInfo` when available
    - normalize pause-state aliases:
      - `pausedDL` / `stoppedDL` -> canonical `stoppedDL`
      - `pausedUP` / `stoppedUP` -> canonical `stoppedUP`
  - local cache metadata now records `qb_profile`
  - local cache path:
    - `~/.cache/hashall-qb/`
  - live read-heavy scripts now routing list/status reads through the local cache:
    - `bin/qb-checking-watch.sh`
    - `bin/qb-start-seeding-gradual.sh`
    - `bin/qb-path-watch.py`
    - `bin/pd-score.sh`
    - `bin/pd-triage.sh`
    - `bin/qb-find-repair-candidates.sh`
    - `bin/qb-triage-step1-inspect.sh`
    - `bin/qb-triage-step2-start-stopped-up.sh`
    - `bin/qb-triage-step3-relink-partials.sh`
    - `bin/qb-repair-batch.sh` discovery/no-ramp list reads
  - operator implication:
    - multiple list/status views should now share one cache daemon instead of each polling qB directly
    - qbitui dashboard remains an external follow-up if you want the same compatibility/cache contract there
- Active docs are now intentionally minimal and stub-free:
  - canonical active set:
    - `README.md`
    - `docs/README.md`
    - `docs/REQUIREMENTS.md`
    - `docs/architecture/SYSTEM.md`
    - `docs/tooling/CLI-OPERATIONS.md`
    - `docs/tooling/REHOME-RUNBOOK.md`
    - `docs/operations/RUN-STATE.md`
    - `docs/project/AGENT-PLAYBOOK.md`
    - `docs/project/PLAN.md`
    - continuity docs:
      - `docs/handoff.md`
      - `docs/ops-log.md`
      - `docs/next-agent.md`
      - `docs/NEXT-AGENT-PROMPT.md`
  - superseded active-tree docs were archived under `docs/archive/2026-doc-consolidation/`
  - do not recreate active-tree compatibility stubs
- Anchor the current model on this invariant:
  - a qB item needs its own unique payload tree / file-structure instantiation on disk
  - that tree should normally be built from donor bytes via hardlinks, not by creating redundant physical copies
  - when these notes say `unique target`, `de-hitchhike`, or `_rehome-unique/<hash>`, read that as “unique per-item payload tree,” not “force duplicate bytes”
- New 2026-03-14 content-drift hardening baseline:
  - `hashall scan` now supports `--drift-policy metadata|quick|full`
  - `hashall refresh` / `rehome refresh` now expose:
    - `--scan-hash-mode fast|full|upgrade`
    - `--drift-policy metadata|quick|full`
  - operator meaning:
    - `metadata` keeps the old size+mtime trust model
    - `quick` rechecks unchanged files with the quick hash and escalates to full hashing on mismatch
    - `full` fully rehashes unchanged files in the requested scan scope
  - this closes the known gap where same-size / same-mtime content drift could survive a routine incremental scan
- New 2026-03-13 hardlink-normalization baseline:
  - `rehome` view construction no longer accepts a preexisting identical destination copy as “good enough”
  - `src/rehome/view_builder.py` now atomically relinks identical destination files back to the donor inode, so successful rehome/reconnect runs do not leave duplicate bytes behind
  - `bin/qb-repair-fresh.py` now does the same normalization during same-fs repair preparation
  - live implication:
    - if a target file already exists with identical bytes, the code should now convert it into a hardlink-backed per-item payload tree instead of preserving a redundant copy
- New 2026-03-13 refresh/jdupes diagnosis baseline:
  - the last `refresh --verbose` was not still running; what remained was a step-3.5 dedupe backlog with weak surfaced status
  - observed evidence:
    - pool-media dedupe reported `27` duplicate groups
    - a failing `Cinderella.2021...` group was only obvious deep in the shared log as `jdupes did not link files with matching SHA256`
  - new behavior:
    - `hashall link execute` now prints the jdupes log glob for the plan and a failed-action preview
    - `bin/db-refresh-step4_5-link-dedup.sh` now writes a structured per-device summary JSON and logs dry-run/apply rc plus failed-action preview
  - latest completed refresh:
    - `~/.logs/hashall/rehome/refresh/20260313-172217.log`
    - ended `OK`
    - one follow-up anomaly remains:
      - root `99/99` `V.for.Vendetta...`
      - `/pool/media/torrents/seeding/cross-seed/hawke-uno/V.for.Vendetta...`
      - logged `files=0 bytes=0`
      - `Upgrade ended incomplete: groups=0`
    - keep this as an explicit idle-time investigation task; it did not invalidate the refresh run
- New 2026-03-13 planner stale-no-op hardening baseline:
  - `relocate-plan` now skips groups when every per-hash view target is already `source_save_path == target_save_path`
  - this closes the deferred-cleanup stale-planner gap that kept resurfacing fully converged groups like `Brave.New.World.US.S01...`
  - live proof:
    - `Brave.New.World.US.S01...` completed successfully at `~/.logs/hashall/reports/rehome-relocate/20260313-114142-66eebb2df636b12a/`
    - a fresh remainder plan now drops from `31` candidates to `29`
    - refresh-seeded remainder plans are no longer the active source of truth once a live-qB-seeded plan is available
- New 2026-03-13 Twisters bridge hardening baseline:
  - planner now prefers surviving target donors when stale rows already point at target-side payloads
  - unique single-file directory-root target views now preserve the expected `root_dir/file` shape instead of flattening to a bare filename
  - mixed `reconcile_subset + patch_one` hardened manifests now work, so `8` already-correct rows can be left alone while the one stale sibling is patched
  - qB is now restarted automatically if a hardened validate/patch failure happens after `qb_stop`
  - reality snapshots now classify these rows as `stale_runtime_and_fastresume_root` instead of the noisier false `mixed_drift`
  - live proof:
    - `Twisters.2024...` completed successfully at `~/.logs/hashall/reports/rehome-relocate/20260313-112558-9962465e30b69544/`
    - `9/9` rows verified `exact_tree`
    - bridge log: `rehome_reconcile_subset ... reconcile_rows=8 patch_rows=1`
    - current qB result: no remaining `missingFiles` in that group
- New 2026-03-13 de-hitchhike baseline:
  - root-to-root relocation planning now defaults multi-hash payload groups to per-hash unique target roots instead of only uniquifying literal target collisions
  - `qb-missing-remediate` reconnect plans now follow the same rule, so reconnects stop recreating shared hitchhiker targets
  - `rehome` stash->pool view planning now also routes multi-hash groups into `_rehome-unique/<hash>` targets
  - successful attaches now remove an unused intermediate donor root when the entire sibling group is in-plan, so the run does not leave a hidden extra canonical target tree behind
  - this is about unique per-item payload trees backed by hardlinks where possible, not about forcing separate physical file copies
  - targeted validation for this slice:
    - `pytest tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py tests/test_rehome_mapping.py tests/test_rehome_catalog_sync.py -q -k 'unique or payload_rows or preflight_existing_view_conflicts_logs_progress_for_missing_targets'`
    - `pytest tests/test_rehome_atomic_relocation.py -q -k cleanup_unused_target_donor_removes_intermediate_root`
    - result: `7 passed`
- Latest live proof under the older pre-fix planner:
  - `Cinderella.2021...` completed operationally
  - report dir: `~/.logs/hashall/reports/rehome-relocate/20260313-095751-578fffbfe4fc2f8c/`
  - qB ended healthy on `/pool/media/...`
  - the post snapshot still warned that the catalog grouped the 4 hashes into `1` shared payload row
  - that warning is the exact structural gap the new de-hitchhike planner/executor slice is meant to close
- Current live migration remainder after the Twisters + Brave success:
  - `old_path_count=34`
  - `new_path_count=317`
  - qB health snapshot:
    - `stalledup=5152`
    - `stoppeddl=1` (`Alien Romulus`, still repair-lane only)
    - `stalleddl=2` (non-pool-data outliers under `/data/media/torrents/seeding/radarr`)
  - next operator step:
    - use `out/rehome-plan-pool-data-to-media-liveqb-20260313.json` for the next conservative slice
    - live-qB-seeded summary:
      - `seed_scope=mode:live_qb_root`
      - `qbit_hashes=34`
      - `mapped_payloads=14`
      - `candidates=14`
      - `reuse=7`
      - `move=7`
      - `covered old-root hashes=34/34`
  - explicit next proving task to keep in the active backlog:
    - `Alien Romulus`
    - why it matters:
      - this is a stalled mixed sibling family with `14` candidates and `7` `~noHL` siblings
      - it is a good next proving lane for rehome/repair logic that needs to lift `~noHL` siblings onto `pool-media`
      - the target outcome should be one correct per-item payload tree per qB item, backed by hardlinks where possible, not duplicate physical copies
    - current caution:
      - keep `1376e795...` in the repair lane until the family is audited as a whole

- `hashall` package semver is now `0.6.8`.
- New 2026-03-12 preflight feedback hardening landed after the long `Snowfall...` quiet window:
  - `_preflight_existing_view_conflicts()` now emits:
    - `preflight_target_views_progress`
    - `preflight_target_views_view_done`
    - `preflight_target_views_complete`
  - this closes the “step=preflight_target_views and then nothing for a long time” UX gap when an existing target tree is large but still healthy
  - live proof:
    - `Snowfall.2017.S05...` now logs an explicit preflight phase before the guarded `MOVE`
  - regression:
    - `tests/test_rehome_catalog_sync.py::test_preflight_existing_view_conflicts_logs_progress`
- New 2026-03-12 preflight target-view hardening landed after the `Novitiate...` partial-conflict abort:
  - `rehome` now logs `step=preflight_target_views` before `build_views` on guarded `REUSE` / target-donor paths
  - it probes any preexisting target-view files read-only and aborts before creating any new hardlinks if one of those destination paths already exists with conflicting bytes
  - plain-English root cause for that abort:
    - one `Novitiate...` target view path on `/pool/media/.../Aither (API)` already held different content
    - old behavior could build an earlier clean sibling view and only then explode on the conflicting path
    - new behavior blocks before mutation, so the run fails closed instead of leaving a partial view build behind
  - regression:
    - `tests/test_rehome_catalog_sync.py::test_preflight_existing_view_conflicts_blocks_before_any_link`
  - live proof after the hardening:
    - `The.Long.Walk.2025...` `REUSE` completed successfully with the new `step=preflight_target_views` phase
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-214219-38c7f2c20c7af677/`
  - current live migration baseline after the later Twisters wave:
    - `old_path_count=34`
    - `new_path_count=317`
    - qB health: `stalledup=5152`, `stoppeddl=1`, `stalleddl=2`
- New 2026-03-12 stale-root reconnect hardening landed after the `Peppermint` gap:
  - `hashall rehome qb-missing-remediate` now accepts `root_drift_after_rehome_reuse` rows when the mapped target payload exists under a different catalog `payload_hash`
  - reconnect donor selection now falls back to the exact mapped target payload row instead of requiring same-`payload_hash` sibling donors
  - this closes the old `/data -> /pool/data` reuse-drift gap where the surviving target payload existed but the stale rows were split onto an older payload hash
  - live proof:
    - `Peppermint.2018.1080p.BluRay.REMUX.AVC.DTS-HD.MA.7.1-EPSiLON.mkv`
    - four stale `missingFiles` hashes were reattached successfully via guarded `REUSE`
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-212329-4f2ac41db39d760f/`
  - post-run qB snapshot for that lane:
    - `missingFiles=0`
    - `stoppedDL=1` (`Alien Romulus`, still a real repair-lane item)
    - the four reattached `Peppermint` hashes are intentionally left `stoppedUP 100%`
- The stale `/data -> /pool/data` `qb-missing-audit` lane now returns `0`:
  - `hashall rehome qb-missing-audit --source-root /data/media/torrents/seeding --target-root /pool/data/media/torrents/seeding`
- `hashall` package semver is now `0.4.181`.
- New 2026-03-12 batch/staleness hardening landed after restarting the next live pool-data batch:
  - `rehome apply` now accepts any JSON with a top-level `plans` list as a batch plan, even without the older explicit `batch=true` marker
  - this fixes the `KeyError: 'decision'` crash when applying generated plan slices like `out/rehome-plan-pool-data-to-media-stale-next4-20260312.json`
  - the live reality layer now reports out-of-plan sibling coverage:
    - snapshot summary fields:
      - `payload_group_siblings`
      - `plan_rows`
      - `out_of_plan_siblings`
    - top-level warnings:
      - `group_warnings`
    - drift-audit summary now prints `plans_with_out_of_plan_siblings`
  - executor now logs `reality_warning ...` when a plan only covers part of a payload group, so cleanup/convergence risk is visible before later drift appears
  - targeted validation for this slice:
    - `pytest tests/test_rehome_cli_apply.py tests/test_rehome_reality.py tests/test_rehome_catalog_sync.py tests/test_rehome_qb_missing.py tests/test_rehome_followup.py tests/test_qb_libtorrent_verify.py -q`
    - result: `46 passed`
- New 2026-03-12 verifier/reality hardening landed after the `Wakanda` false-negative:
  - `bin/qb-libtorrent-verify.py` now promotes instant-complete `exact_tree` results that jump straight to healthy `seeding`/`stalledUP` without ever emitting a `checking_files` transition
  - this fixes tiny or cache-hot torrents that were being misclassified as `partial_match` with `verify_reason=no_recheck_transition` even though all bytes matched
  - `src/rehome/reality.py` now classifies ordinary source-only `MOVE` rows as `source_only` / `ready_repoint_or_reconcile` instead of the noisier false `target_view_missing`
  - post-apply reality snapshots now treat short-lived `checkingResumeData`/`checkingFiles` on already-repointed target rows as `post_apply_settling`
  - group-level post snapshots now report `settling_after_apply` instead of the noisier false `blocked_qbit_transient`
  - live proof:
    - payload `6bb9bb5432f39cbb...`
    - title: `David Khune - Wakanda - Native American Magic.epub`
    - failed pre-fix report: `~/.logs/hashall/reports/rehome-relocate/20260312-145411-6bb9bb5432f39cbb/`
    - successful rerun: `~/.logs/hashall/reports/rehome-relocate/20260312-145812-6bb9bb5432f39cbb/`
  - targeted validation for this slice:
    - `pytest tests/test_qb_libtorrent_verify.py tests/test_rehome_reality.py tests/test_rehome_qb_missing.py tests/test_rehome_followup.py tests/test_rehome_catalog_sync.py -q`
    - result: `41 passed`
    - later follow-up with the phase-aware post-apply logic:
      - same suite result: `43 passed`
- New stale-assumption hardening landed on 2026-03-12:
  - shared module: `src/rehome/reality.py`
  - new CLI: `hashall rehome drift-audit --plan <plan.json>`
  - every `rehome apply` run now writes `reality-pre.json`, `reality-post.json`, and `reality-failure.json` beside the hardened manifest
  - these snapshots compare live qB state, fastresume path fields, catalog rows, and filesystem existence instead of trusting any one source of truth
  - row classifications now include:
    - `aligned_target`
    - `catalog_drift_already_targeted`
    - `stale_runtime_and_fastresume_root`
    - `stale_runtime_root`
    - `stale_fastresume_root`
    - `target_view_missing`
    - `qbit_transient`
    - `incomplete_torrent`
    - `mixed_drift`
  - preflight failures now include plain-English guidance derived from the live snapshot instead of only raw qB state strings
  - targeted validation for this slice:
    - `pytest tests/test_rehome_reality.py tests/test_rehome_cli_followup.py tests/test_rehome_cli_lock.py tests/test_rehome_qb_missing.py tests/test_rehome_followup.py tests/test_rehome_catalog_sync.py -q`
    - result: `40 passed`
- `qb-zfs-relocate` remains the hardened live migration backend for guarded qB dataset relocation:
  - entrypoint: `bin/qb-zfs-relocate.py`
  - core module: `src/hashall/qb_zfs_relocate.py`
  - phases: `plan`, `copy`, `verify`, `validate`, `patch`, `resume`, `cleanup`, `rollback`
  - current script semver: `v0.1.13`
  - wrapper-driven runs write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
  - `migrate` supports staged safe cleanup via `--auto-cleanup=safe`
- `hashall` package semver is now `0.4.177`.
- New direct stale-root reconnect command landed on 2026-03-12:
  - CLI: `hashall rehome qb-missing-remediate`
  - purpose: reconnect `missingFiles` torrents that still point at dead `/data == /stash` roots to already-healthy surviving sibling payloads under `/pool/media/...`
  - live proof:
    - `Cleverman.S02...` (`2` hashes) remediated successfully
    - `Megalopolis...` (`4` hashes) remediated successfully
  - current post-run qB snapshot:
    - `stalledUP=5144`
    - `uploading=1`
    - `stoppedUP=6`
    - `missingFiles=0`
  - the `6` stoppedUP rows are the freshly reattached hashes left paused on purpose after reconnect
- `qb-repair-payload-group.sh` was hardened in commit `5d83419`:
  - wrapper: `bin/qb-repair-payload-group.sh`
  - core module: `src/hashall/qb_repair_payload_group.py`
  - script semver: `v0.2.0`
  - validates that `--good` and `--broken` share the same `payload_hash` before any apply step
  - uses dynamic catalog device/file-table resolution, full relative-path file matching, shared fastresume backup/journal logic, and per-run artifacts under `out/qb-repair-payload-group/<stamp>-<hash>/`
  - targeted validation now passes locally:
    - `pytest tests/test_fastresume.py tests/test_qb_repair_payload_group.py -q`
    - result: `8 passed`
- New `rehome` planning capability landed in commit `e572bf8`:
  - new CLI: `hashall rehome relocate-plan`
  - core planner: `src/rehome/normalize.py`
  - this can now generate `rehome apply` batch plans for explicit root-to-root relocations such as `/pool/data/media/torrents/seeding -> /pool/media/torrents/seeding`
  - shared-root sibling groups are now surfaced as one payload move plus synthesized unique destination views when sibling torrents would collide on the same target save path
  - this is the first planner step toward handling `2-to-1 -> 2-to-2` payload/view relocation inside `rehome`
- `rehome apply` now uses the hardened relocation backend for MOVE/REUSE attachment:
  - donor acquisition remains qB-metadata-only and copy-first
  - offline verify, validate, patch, restart checks, and deferred cleanup reuse the guarded `qb-zfs-relocate` contract
  - tests covering the merged path now pass locally:
    - `pytest tests/test_rehome_atomic_relocation.py tests/test_rehome_catalog_sync.py tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py -q`
    - result: `47 passed`
  - cross-device `REUSE` reruns now support catalog-only catch-up after successful live repoint:
    - executor logs `rehome_reconcile_only`
    - offline verify still runs
    - validate/patch are skipped when qB is already on the target save paths
    - catalog sync then updates the target `payloads` row and `torrent_instances`
  - non-reconcile `MOVE` runs now explicitly stop qB before patch-mode validate:
    - this removes the false `torrent_not_stopped` blocker that appeared after successful copy + offline verify
    - the live `Megalopolis.2024.REPACK...` pilot proved the corrected path
  - staged follow-up cleanup is now available in `rehome`:
    - `hashall rehome followup --cleanup` now stages source roots into hidden `.rehome-cleanup-stage/<payload_hash>/...`
    - it observes qB on the target save paths before final delete
    - any qB regression restores the staged source roots automatically
  - small live `rehome` pilots are now green on both major paths:
    - `REUSE`: `The.West.Wing.S07...` cross-device reuse group completed and catalog-synced on rerun via `rehome_reconcile_only`
    - `MOVE`: `Megalopolis.2024.REPACK...` moved from `/pool/data/...` to `/pool/media/...`, verified `exact_tree`, patched, resumed, and left source cleanup deferred
- mixed-state reruns are now handled safely:
  - commit `85b91af` added partial reconcile support for batches where some rows are already repointed and verified while others were skipped
  - post-patch save-path verification now ignores rows that were not actually patched
  - this unblocked the live `Longlegs` mixed-batch rerun
- commit `21ea673` added streamed rsync progress for `rehome` MOVE copy windows:
  - long `MOVE` transfers now emit `copy_progress percent=... elapsed=... eta=...`
  - a long pause after `step=move_payload` is no longer expected on new runs
- commit `f3071ff` fixed a real false-negative verify path exposed by `Mickey.17...`:
  - source bytes and a clean target copy both verified `exact_tree`
  - bug 1: source recheck completion could mark `completed` before qB ever entered a real `checking*` state
  - bug 2: transient post-copy `partial_match` results were not retried when `rehome` supplied hardened manifest rows with `copy_status=pending`
  - live proof on 2026-03-12:
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-111522-36390ecee324f1af/`
    - `Mickey.17.2025.1080p.iT.WEB-DL.DDP5.1.Atmos.H.264-BYNDR.mkv` completed `MOVE` successfully and ended `stoppedUP 100%` on `/pool/media/...`
- The 2026-03-12 stale sibling-root drift lane is now remediated live:
  - original scope:
    - `Megalopolis...` (`4` hashes)
    - `Cleverman.S02...` (`2` hashes)
  - root cause in plain English:
    - healthy sibling torrents for those payloads already existed under newer `/pool/media/...` target views
    - the stale hashes were left behind still pointing at dead old `/data == /stash` views in both qB and `.fastresume`
  - live result:
    - `hashall rehome qb-missing-audit --source-root /data/media/torrents/seeding --target-root /pool/media/torrents/seeding` now returns `0`
    - qB no longer has an active `missingFiles` lane for this class
- Follow-up cleanup is now hardened against creating more of this class:
  - cleanup now checks for any surviving same-`payload_hash` torrent refs that still point at non-target devices or old `/data`/`/stash` aliases
  - staged cleanup will stay blocked until those stale sibling refs are reconciled
- New stale-root audit exists for missing qB items:
  - CLI: `hashall rehome qb-missing-audit`
  - the original audited live cohort was `49` `missingFiles` items classified as `root_drift_fastresume_stale`
  - that stale-root `missingFiles` lane has now been remediated live in waves using `qb-zfs-relocate`
  - the older `/pool/data -> /pool/media` lane is no longer the active blocker
  - the current `missingFiles` lane is the separate 6-item `/data == /stash` sibling-root drift class described above
- current qB state snapshot after the new sibling-root audit:
    - `stalledUP=5138`
    - `uploading=7`
    - `missingFiles=6`
  - the active qB problem lane is now these `6` stale sibling-root drift rows
- Guarded relocation coverage is current:
  - `tests/test_qb_zfs_relocate.py` previously passed locally for the guarded dataset relocation slice
  - `hashall rehome relocate-plan --help` works
  - `hashall rehome qb-missing-audit --help` works
- Live qB relocation already succeeded for `pool-data -> pool-media` via `qb-zfs-relocate`:
  - successful migrate runs are logged under `~/.logs/qb-zfs-relocate/`
  - cleanup completed successfully for prior successful pilot batches
- Treat the older 49-item `missingFiles` cohort as a legacy remediation lane, not proof of a current `qb-zfs-relocate` fastresume scribbler.

## Immediate Next Work

1. Hardened live repair succeeded and the sidecar-fetch lane is now clear.
   - commit `fe6b0fb` fixed qB API readiness checks after container restart
   - `0fff0ce260a58b789f857f6ad085a5d03622b952` repaired from sibling donor and now seeds normally again
   - live artifact: `out/qb-repair-payload-group/20260310-164254-0fff0ce260a5/repair-plan.json`
2. The remaining sidecar blockers were resolved operationally.
   - qB resume attempts initially failed with `Permission denied` creating missing `.nfo` / `.srt` files
   - root cause: the six payload directories were `root:root 755` while qB runs as uid `1026` gid `101`
   - minimal live fix: change ownership of just those six directories to `1026:101`, then resume the six torrents
   - result: qB fetched the missing sidecars and all six returned to `stalledUP 100%`
3. `hashall payload siblings` read-only bug is fixed in commit `74ea2b5`.
4. `hashall refresh --verbose` has now returned `OK` after the stale-root / stoppedDL cleanup work.
   - `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` now returns `0`
5. The `West Wing S07` cross-device `REUSE` pilot is now green:
   - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-155600-8277eae774b3591b/`
   - all three siblings ended `stalledUP 100%` on `/pool/media/...`
   - catalog now shows:
     - `2d9004e9... -> payload_id 13703, device_id 141, save_path /pool/media/.../Aither (API)`
     - `8bf2aec2... -> payload_id 13703, device_id 141, save_path /pool/media/.../TorrentLeech`
     - `f18b8cd0... -> payload_id 13703, device_id 141, save_path /pool/media/.../_rehome-unique/...`
6. The `Megalopolis.2024.REPACK...` `MOVE` pilot is now green:
   - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-173250-692ffa9407a574f4/`
   - all three sibling views verified `exact_tree`
   - qB ended `stalledUP 100%` on the target roots
   - catalog now shows:
     - `14e3deab... -> payload_id 13557, device_id 141, save_path /pool/media/.../Aither (API)`
     - `4da8ec78... -> payload_id 9704, device_id 141, save_path /pool/media/.../PrivateHD`
     - `6befda30... -> payload_id 13557, device_id 141, save_path /pool/media/.../_rehome-unique/...`
   - source removal stayed deferred and manual
7. The first mixed live scale-up is now green in curated form:
   - bad candidate excluded:
     - `Shining.Girls...` REUSE group from `mixed4`
     - reason: all `3` rows failed destination offline verify as `partial_match`, so this is a real bad reuse candidate, not a planner-only false positive
   - successful batch plan:
     - `out/rehome-plan-pool-data-to-media-mixed3-no-shining.json`
   - successful live results:
     - `Longlegs...` REUSE completed via `rehome_reconcile_subset`
       - `8` rows reconciled cleanly on `/pool/media/...`
       - `1` `dest_missing` row was left untouched on `/pool/data/...`
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-180840-a1041c6049c66abe/`
     - `Brave.New.World.US.S01...` MOVE completed successfully
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-182010-66eebb2df636b12a/`
       - all `4` torrents ended `stalledUP 100%` on `/pool/media/...`
     - `Greenland.2020.Repack...` MOVE completed successfully
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-183147-adf55dffe6443f6a/`
       - all `8` torrents ended `stalledUP 100%` on `/pool/media/...`
   - source cleanup remained deferred/manual for all three payload groups
8. Second curated live scale-up is now also green:
   - plan file: `out/rehome-plan-pool-data-to-media-next4c.json`
   - all four `MOVE` payload groups completed successfully:
     - `Brave.New.World.US.S01...`
     - `Greenland.2020.Repack...`
     - `Azrael...`
     - `Stranger.Things.S03...`
   - shared log ended with:
     - `✅ Summary: 25 torrent(s) checked, all in acceptable state`
9. Two `MOVE` carve-outs are now known and should stay out of the clean batch lane until separately investigated:
   - `Magic.City.S01...`
     - failed after copy with `Target file count mismatch after move`
     - observed runtime stats:
       - source: `8 files / 106474639951 bytes`
       - target: `9 files / 110028001871 bytes`
     - interpretation: dirty/preexisting target content, not a broad fastresume corruption signal
   - `Wilding.2023...`
     - copy completed and target verify passed
     - offline verify then sat at `checking_files 0.00%` for `15m+`
     - interpretation: verifier-control-path issue until re-tested, not proof of mover corruption
10. Deep audit conclusion on the recent failures:
    - there is no evidence of a broad errant fastresume scribbler in current `rehome` / `qb-zfs-relocate`
    - the recent failures have been:
      - stale-root drift already remediated
      - dirty/preexisting destination content (`Magic City`)
      - bad reuse candidate (`Shining.Girls`)
      - verifier stall behavior (`Wilding`)
11. Live staged cleanup is now proven on `/pool/data -> /pool/media` follow-up:
    - one pilot payload and six additional pool-data payload groups completed `cleanup_result=done`
    - follow-up reconcile then auto-healed the catalog-only backlog for healthy groups
    - two final cleanup retries initially restored because of source-side ownership/permission errors:
      - `/pool/data/cross-seed/PrivateHD`
      - `/stash/media/torrents/seeding/cross-seed/seedpool (API)/Stranger.Things.S03.1080p.NF.WEB-DL.DDP5.1.x264-NTG`
    - after a narrow ownership fix on those source paths, both cleanup retries completed `done`
12. Current follow-up backlog after the cleanup wave:
    - only `1` tagged group remains in follow-up:
      - payload `a1041c6049c66abe...` (`Longlegs...`)
      - reason: one live qB row still seeds from `/pool/data/...` and reports `save_path_mismatch`
    - everything else in the cleanup-required lane is now drained
13. Current qB health snapshot after cleanup + reconcile:
    - `stalledUP=5147`
    - `uploading=4`
14. Keep future direct `qb-zfs-relocate` runs on timestamped manifests or pass explicit per-run `--manifest` paths.

## Key Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Operational Reminders

- `hashall refresh --verbose` keeps catalog scans updated; run it after any donor copy.
- `hashall rehome auto --from <src> --to <dst> --limit <n> [--apply]` remains the canonical mover.
- `hashall rehome relocate-plan` is now the explicit planner for root-to-root relocation cases that `auto` does not surface cleanly.
- `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` remains the canonical proof path for the legacy `/pool/data` stale-root cohort.
- `hashall rehome qb-missing-audit --source-root /data/media/torrents/seeding --target-root /pool/media/torrents/seeding` is now the canonical proof path for the current 6-item sibling-root drift cohort.
- Do not let qB run `setLocation` as part of normal migration; we rely on offline fastresume repointing.
- Keep the guard log tailing commands handy for monitoring long runs.
