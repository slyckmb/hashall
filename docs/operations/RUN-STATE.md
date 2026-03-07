# Run State (Canonical)

Last updated: 2026-03-07
Status: canonical living state

## Purpose

Single living document for current operational status, handoff context, and next-agent execution guidance.

## Current Mission

1. Keep qB stoppedDL repair loop safe and convergent.
2. Keep hashall catalog refresh + dedup pipeline robust across `stash`, `data`, and `spare`.
3. Eliminate refresh/runtime failures caused by device alias drift and negative device IDs.
4. Remove remaining storage-layer dependence on volatile `device_id` by binding file tables to stable `fs_uuid`.
5. Publish one canonical machine-readable seed-root-state contract so `traktor` and related tooling stop inferring root/link state ad hoc.

## Seed-Root Contract Update (2026-03-07 11:35 EST)

- New source-of-truth publisher added:
  - `src/rehome/seed_state.py`
  - `rehome seed-root-state show [--write]`
- Published contract path:
  - `~/.hashall/seed-root-state.json`
- Ownership model:
  - `hashall` writes
  - `traktor` should consume read-only
- Consumer rule:
  - consumers should fail closed if `schema_version`, `writer`, or required sections are missing/invalid
- Required top-level contract fields:
  - `schema_version`
  - `updated_at`
  - `generation`
  - `writer`
  - `active`
  - `target`
  - `cross_seed`
  - `migration`
  - `aliases`
  - `mirror_roots`
- Update timing now improved:
  - `rehome config set`
  - `rehome config add-root`
  - `rehome config remove-root`
  - `rehome config sync-roots --apply`
  - `rehome config migrate`
  all republish `~/.hashall/seed-root-state.json` automatically
  - `rehome refresh` now also republishes at managed-run start so external consumers see the current advertised roots before scan/dedup/payload-sync work begins
- Contract currently publishes:
  - `active.seeding_root`
  - `target.seeding_root`
  - `cross_seed.link_root`
  - `migration.state`
  - `migration.source_roots`
  - `aliases`
  - `mirror_roots`
- Current operational intent:
  - advertise `/pool/media/torrents/seeding` as the active/target seeding root
  - surface legacy `/pool/data/media/torrents/seeding`, `/pool/data/seeds`, and `/data/media/torrents/seeding` explicitly as migration mirrors/source roots
- Related refresh anomaly now tracked/fixed:
  - post-`Plan #59` dedup execution on `spare` failed due to `ActionInfo` local shadowing in `hashall.link_executor.execute_plan()`
  - fixed in active worktree and covered by regression test

## Refresh Anomaly Ledger (2026-03-07)

- Hidden delegated confirmation prompt
  - symptom: refresh appeared stalled with no visible progress
  - root cause: `hashall link execute` was launched without `--yes`
  - fix: refresh now invokes non-interactive execute and points operators to `~/.logs/hashall/hashall.log`
  - status: fixed

- Post-`Plan #59` `ActionInfo` crash
  - symptom: `hashall link execute` failed on `spare` immediately after plan creation
  - root cause: local import shadowed `ActionInfo` inside `execute_plan()`
  - fix: removed local shadowing import; added regression
  - status: fixed

- Mixed-root dedup observed during migration
  - symptom: refresh dedup operates on both `/pool/data/media/...` and legacy `/pool/data/seeds/...`
  - root cause: migration is not converged; legacy repair roots are still catalog-visible and dedup-eligible
  - mitigation: do not treat dedup completion as migration convergence; qB migration still requires separate guarded workflow
  - status: active operational constraint

- Long quiet periods during delegated work
  - symptom: operator uncertainty about hang vs progress
  - current mitigation: watch `~/.logs/hashall/hashall.log`
  - follow-up: improve heartbeat/progress feedback further
  - status: partially mitigated

## Compact-Critical Snapshot (2026-03-06 12:30 EST)

- Branch/worktree in active use for this incident:
  - `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`
  - `chatrap/codex-hashall-20260305-181919`
- Last completed safety fix in this worktree:
  - commit `657eccc`: `qb-stoppeddl-drain` now treats empty bucket `index.json` as valid no-op (`summary selected=0`) instead of hard error.
  - script semver now `bin/qb-stoppeddl-drain.py v0.1.23`.
- Current stoppedDL bucket status at last check:
  - `python3 bin/qb-stoppeddl-bucket.py --bucket-dir /tmp/qb-stoppeddl-bucket-live --states stoppedDL,missingFiles,pausedDL,error --limit 0 --prune-absent`
  - result: `active=0 total_entries=0`.
- Confirmed catalog identity drift that must not be ignored:
  - `devices` still contains parked temp negative `device_id` (`-905882091`).
  - `payloads` has rows on missing/unknown `device_id` values (`141`, `NULL`, legacy `49`).
  - `torrent_instances` has rows on missing/unknown `device_id` values (`141`, `NULL`).
- Strategic directive now active:
  - migrate identity model from volatile `device_id` to stable `fs_uuid` as primary key for payload/torrent/rehome workflows.
  - keep `device_id` only as runtime lookup for `files_<device_id>` tables until table model is redesigned.
- Critical WIP note:
  - `fs_uuid` transition is now implemented-in-progress across core code and tests; do not discard silently.

## fs_uuid Identity Layer Update (2026-03-06 13:35 EST)

- Implemented schema migration:
  - `src/hashall/migrations/0012_fs_uuid_identity.sql`
  - adds `fs_uuid` to `payloads` and `torrent_instances`
  - adds fs_uuid indexes
  - backfills from `devices`, then payload/torrent cross-link fallbacks
- Implemented model/write path updates:
  - `src/hashall/payload.py`
    - `Payload`/`TorrentInstance` now carry `fs_uuid`
    - `build_payload()` resolves fs_uuid
    - `upsert_payload()` prefers `(fs_uuid, root_path)` identity when available
    - `upsert_torrent_instance()` persists fs_uuid when column exists
    - getters support fs_uuid-aware filtering/reads
  - `src/hashall/cli.py`
    - `payload sync` writes `TorrentInstance.fs_uuid`
- Implemented rehome identity propagation:
  - `src/rehome/planner.py`
    - resolves stash/pool fs_uuid from devices
    - pool/stash payload existence checks use fs_uuid-aware filtering
    - executable demote/promote plans now carry `source_fs_uuid` / `target_fs_uuid`
  - `src/rehome/executor.py`
    - resolves runtime `device_id` from plan fs_uuid when present
    - catalog sync writes/updates fs_uuid fields when schema supports them
- Version bumps:
  - `hashall`: `0.4.131`
  - `rehome`: `0.6.1`
- Verification run:
  - `pytest -q tests/test_rehome.py tests/test_payload.py` -> pass
  - `pytest -q tests/test_cli_payload_sync.py tests/test_rehome_catalog_sync.py tests/test_rehome_promotion.py tests/test_rehome_stage4.py` -> pass
- Rollout caveat:
  - migration has **not** been intentionally forced against live `~/.hashall/catalog.db` in this turn; it will apply on next write-open via normal migration path.

## fs_uuid Identity Repair Execution (2026-03-06 13:20 EST)

- New repair tooling added in this worktree:
  - `hashall doctor repair-identity`
  - `bin/hashall-fs-identity-repair.py` (`v0.1.1`)
  - `src/hashall/identity_repair.py`
- Safety hardening in repair logic:
  - fail-closed inference (no `/pool/media` <-> `/pool/data` aliasing)
  - optional bind alias only for `/data/media` <-> `/stash/media`
  - same-run convergence for dependent torrent repairs (`torrent_linked_payload_pending_repair`)
  - report filename collision fixed (microsecond timestamp suffix)
- Version bump:
  - `hashall`: `0.4.133`
- Live catalog execution (with snapshots before each apply):
  - snapshot: `out/reports/fsuuid-identity/catalog-pre-identity-repair-20260306-131658.db`
  - apply pass: strict (`--no-allow-bind-alias`) -> `83` actions
    - report: `out/reports/fsuuid-identity/identity-repair-apply-20260306-131703.json`
  - apply pass: strict follow-up -> `16` actions
    - report: `out/reports/fsuuid-identity/identity-repair-apply-20260306-131827-569679.json`
  - apply pass: bind-alias lane (validated same `st_dev` for `/data/media` and `/stash/media`) -> `13` actions
    - report: `out/reports/fsuuid-identity/identity-repair-apply-20260306-131853-274411.json`
  - apply pass: linked-incomplete lane -> `2` actions
    - report: `out/reports/fsuuid-identity/identity-repair-apply-20260306-131914-013677.json`
  - total identity repairs applied: `114`
- Post-apply audit snapshot:
  - report: `out/reports/fsuuid-identity/identity-drift-audit-post-20260306-1319.json`
  - key metrics:
    - `payloads_fs_uuid_null: 31` (down from `72`)
    - `payloads_device_id_null: 2` (down from `27`)
    - `payloads_device_unknown: 29` (down from `45`)
    - `torrents_fs_uuid_null: 69` (down from `137`)
    - `torrents_device_id_null: 2` (down from `75`)
    - `torrents_device_unknown: 67` (unchanged; all on missing device `141`)
- Remaining unresolved scope:
  - `100` identity-candidate rows remain (all rooted under `/pool/media`)
  - payload candidates: `31` (`29` with stale `device_id=141`, `2` with `device_id=NULL`)
  - torrent candidates: `69` (`67` with stale `device_id=141`, `2` with `device_id=NULL`)
  - no remaining auto-fix actions from repair tool without a valid `/pool/media` device mapping in `devices`.

## Stable Files Table Binding WIP (2026-03-06 20:40 EST)

- Strategic objective:
  - stop using runtime `device_id` as the physical identity of `files_*` tables.
  - preserve `device_id` only for kernel/runtime hardlink-boundary facts and backward compatibility.
- Chosen design:
  - add `devices.files_table` as the stable physical table binding derived from `fs_uuid`.
  - use stable physical tables named from `fs_uuid` instead of renaming `files_<device_id>` on reboot/device rotation.
  - keep `files_<device_id>` as compatibility views over the stable physical table.
  - this is an intermediate hardening step before any future unified-files-table redesign.
- New migration added but not yet committed:
  - `src/hashall/migrations/0013_stable_files_table_binding.sql`
  - adds `devices.files_table`
  - backfills deterministic stable table names from `fs_uuid`
  - adds unique index on `devices.files_table`
- Core code already patched in working tree (uncommitted):
  - `src/hashall/device.py`
    - new stable files-table helpers (`files_table_name_for_fs_uuid`, `get_files_table_name`, compatibility-view helpers)
    - `ensure_files_table()` now resolves stable physical table when `fs_uuid` is known
    - `register_or_update_device()` no longer treats `device_id` rotation as a reason to rename the physical files table
  - callers updated to resolve files table through helper instead of raw `f"files_{device_id}"`:
    - `src/hashall/scan.py`
    - `src/hashall/payload.py`
    - `src/hashall/export.py`
    - `src/hashall/link_executor.py`
    - `src/hashall/link_analysis.py`
    - `src/hashall/diff.py`
    - `src/hashall/link_planner.py`
    - `src/hashall/treehash.py`
    - `src/hashall/sha256_migration.py`
    - `src/hashall/status_report.py`
    - `src/hashall/cli.py`
  - new CLI entrypoint in working tree:
    - `hashall devices migrate-files-tables`
- Current dirty/uncommitted file set that must not be lost:
  - `src/hashall/cli.py`
  - `src/hashall/device.py`
  - `src/hashall/diff.py`
  - `src/hashall/export.py`
  - `src/hashall/link_analysis.py`
  - `src/hashall/link_executor.py`
  - `src/hashall/link_planner.py`
  - `src/hashall/payload.py`
  - `src/hashall/scan.py`
  - `src/hashall/sha256_migration.py`
  - `src/hashall/status_report.py`
  - `src/hashall/treehash.py`
  - `tests/test_device.py`
  - `src/hashall/migrations/0013_stable_files_table_binding.sql` (new)
- Test state for this WIP:
  - targeted compile checks for touched modules pass.
  - targeted test set result before compact:
    - `76 passed`
    - `1 failed`
  - failing test:
    - `tests/test_cli_payload_sync.py::TestPayloadSyncCLI::test_payload_sync_remaps_alternate_mountpoints_for_prefix_filtering`
  - exact failure signature:
    - `sqlite3.OperationalError: attempt to write a readonly database`
    - triggered from `src/hashall/payload.py -> get_files_for_path() -> src/hashall/device.py:get_files_table_name()`
    - occurs during `payload sync --dry-run` after canonical mount remap, meaning the new helper is still trying to perform write-side setup on a read-only/query-only path.
- Safety boundary:
  - do **not** run live `hashall devices migrate-files-tables` or any live files-table rebinding on `~/.hashall/catalog.db` until the read-only failure is fixed and targeted tests are green.
  - no live migration of physical files tables has been executed in this WIP.
- Current version note:
  - `hashall` semver is `0.4.135`.
  - code for this rollout is now committed; docs were updated after live validation.
- Progress tracker:
  - canonical checklist lives in `docs/project/PLAN.md` under `fs_uuid Files-Table Migration`.

## Copied-DB Validation (2026-03-06 22:22 EST)

- Validation target:
  - live catalog copied to `/tmp/hashall-catalog-fsuuid-validate-20260306-222228.sqlite3`
- Dry-run result on copied DB:
  - `mode=dry-run devices=13 actions={"rename_legacy_table": 13}`
  - report: `out/reports/fsuuid-files-table-validate/migrate-files-tables-dryrun-20260306-222228.json`
- Apply result on copied DB:
  - `mode=apply devices=13 actions={"rename_legacy_table": 13}`
  - snapshot of copied DB before apply:
    - `out/reports/fsuuid-files-table-validate/catalog-copy-pre-apply-20260306-222228.sqlite3`
  - apply report:
    - `out/reports/fsuuid-files-table-validate/migrate-files-tables-apply-20260306-222228.json`
- Post-apply checks on copied DB:
  - `devices` rows: `13`
  - physical stable tables (`files_fs_%`): `13`
  - compatibility views (`files_%`): `13`
  - sample report rows confirm `post_target_relation=table` and `post_legacy_relation=view`
  - post-apply preflight on copied DB reports `ok=true`
    - output capture: `out/reports/fsuuid-files-table-validate/preflight-after-apply-20260306-222228.json`
- Important boundary:
  - this validation was performed on a copied DB only.
  - live `~/.hashall/catalog.db` has **not** been modified by this validation.

## Live Files-Table Migration Execution (2026-03-06 22:43 EST)

- Code commits that enabled this rollout:
  - `7d896d6` `feat(identity): bind files tables to stable fs_uuid-backed storage`
  - `86d0e4b` `feat(devices): add guarded files-table migration workflow`
- Live dry-run against `~/.hashall/catalog.db`:
  - `mode=dry-run devices=13 actions={"rename_legacy_table": 13}`
  - report: `out/reports/fsuuid-files-table-live/migrate-files-tables-live-dryrun-20260306-224323.json`
- Live apply against `~/.hashall/catalog.db`:
  - snapshot written before mutation:
    - `out/reports/fsuuid-files-table-live/catalog-live-pre-apply-20260306-224323.sqlite3`
  - apply report:
    - `out/reports/fsuuid-files-table-live/migrate-files-tables-live-apply-20260306-224323.json`
  - result: `mode=apply devices=13 actions={"rename_legacy_table": 13}`
- Live post-apply verification:
  - `devices` rows: `13`
  - stable physical tables (`files_fs_%`): `13`
  - compatibility views (`files_%`): `13`

## Refresh Dedup Parser Fix (2026-03-07 00:00 EST)

- Operational anomaly confirmed from refresh log:
  - `rehome refresh` reported dedup mode `execute`, created `hashall link plan` plans, then skipped execution with:
    - `no plan_id in link plan output ... skipping execute`
- Root cause:
  - `src/rehome/auto.py` only parsed `plan_id=<n>`
  - current `hashall link plan` output emits `Plan #<n>`
  - result: refresh silently skipped `hashall link execute` for all generated plans
- Fix applied in active worktree:
  - added shared link-plan id parser that accepts both `plan_id=<n>` and `Plan #<n>` output forms
  - switched both refresh dedup call sites (managed roots and active/dest roots) to use the shared parser
  - improved skip log text to `no parsable plan_id ...`
- Regression coverage added:
  - `tests/test_rehome_refresh_safety.py`
  - covers machine-readable parser form, human summary/header form, and orchestration path proving `run_refresh()` issues `link execute` after a `Plan #<n>` result
- Version bumps for this fix:
  - `hashall`: `0.4.136`
  - `rehome`: `0.6.2`
  - representative devices show `post_target_relation=table` and `post_legacy_relation=view`
  - post-apply preflight reports `ok=true`
    - output capture: `out/reports/fsuuid-files-table-live/preflight-live-after-apply-20260306-224323.json`
- Current catalog state:
  - every registered device now has `devices.files_table` populated
  - live catalog physical storage is now fs_uuid-bound
  - legacy `files_<device_id>` access remains available via compatibility views
- New operational rule:
  - do not mutate files-table bindings by hand
  - use `hashall devices migrate-files-tables` for planning/reporting
  - use `doctor preflight` to reject volatile `dev-*` identity before apply-style operations

## Non-Negotiables

- One mutating qB workflow at a time.
- No unintended sustained downloading state flips.
- Prefer deterministic, idempotent loops.
- Any full refresh run must include all active roots:
  `/stash/media` (covers `/data/media` collection), `/pool/data`, `/pool/media`, `/mnt/hotspare6tb`.

## Active Toolchain

- qB stoppedDL pipeline:
  - `bin/qb-stoppeddl-bucket.py`
  - `bin/qb-stoppeddl-drain.py`
  - `bin/qb-stoppeddl-apply.py`
  - `bin/qb-stoppeddl-apply-watch.sh`
  - `bin/qb-stoppeddl-roundloop.sh`
  - `bin/qbit-start-seeding-gradual.sh`
- Full DB refresh pipeline:
  - `bin/codex-says-run-this-next.sh` (canonical)
  - `bin/full-hashall-db-refresh.sh` (equivalent explicit wrapper)
  - `bin/db-refresh-step1-scan-stash.sh`
  - `bin/db-refresh-step2-scan-pool-hotspare.sh`
  - `bin/db-refresh-step3-sha256-backfill.sh`
  - `bin/db-refresh-step4_5-link-dedup.sh`
  - `bin/db-refresh-step4-payload-sync.sh`
  - `bin/qb-hash-root-report.sh`

## Recent Hardening (2026-03-01)

- Refresh scripts now derive repo root from script location instead of hardcoded paths.
- Step 3 and step 3.5 now resolve device aliases safely:
  - supports `spare` and legacy `hotspare6tb`
  - fallback by mountpoint `/mnt/hotspare6tb`
  - logs resolved devices and fails cleanly if none resolve
- Step 3.5 default device set now uses `stash,data,spare`.
- Step 3 / 3.5 aggregate per-device failures and exit non-zero on partial failure.
- `hashall stats --hash-coverage` path for negative `device_id` tables is fixed in branch code
  by quoting dynamic SQLite identifiers (e.g. `files_-905882091`).

## Incident Update (2026-03-06 08:45 EST)

- Pilot failure root cause is confirmed:
  - active guard daemon (`qbit-start-seeding-gradual.sh --daemon --guard-only`) stopped hashes in `checkingDL` during repair recheck, producing false `postcheck_timeout`.
  - evidence:
    - apply pilot report: `/tmp/qb-stoppeddl-bucket-live/reports/apply-pilot-r2-20260306-074556.json`
    - guard stop log: `/home/michael/.logs/hashall/reports/qbit-triage/start-seeding-gradual-guard-20260306-074602.log`
- New hardening now on this branch/worktree:
  - `bin/qbit-start-seeding-gradual.sh` `v1.3.8`
    - `checkingDL` is no longer treated as dangerous by default.
    - supports repair recheck allowlist file: `/tmp/qb-stoppeddl-bucket-live/guard-recheck-allowlist.json`.
    - optional `--guard-include-checkingdl` retains old strict behavior when explicitly requested.
  - `bin/qb-stoppeddl-apply.py` `v0.2.9`
    - preflight detection for active gradual/guard daemon; default fail-fast block (`mode=guard_daemon_blocked`).
    - explicit override available via `--allow-guard-daemon`.
    - guard allowlist add/remove around recheck waits (`--guard-allowlist-*`).
    - enriched summary/report telemetry (`guard_daemon_detected`, guard daemon records).
- Pilot validation after patch:
  - preflight block works:
    - `/tmp/qb-stoppeddl-bucket-live/reports/apply-pilot-guard-preflight-20260306-083911.json`
  - override pilot records allowlist add/remove and guard presence:
    - `/tmp/qb-stoppeddl-bucket-live/reports/apply-pilot-guard-allow-20260306-084229.json`
- Critical operational caveat:
  - currently running daemon PID `115681` was started before these script edits and still uses old in-memory behavior (`checkingDL` stop). Restart daemon after deploying updated script to activate new guard logic.

## Current Long-Running Operation

- Full pipeline launched via `bin/codex-says-run-this-next.sh`.
- Step 3 and step 3.5 for `stash` and `data` completed and applied.
- Step 3.5 for `spare` currently running large `hashall link execute` action set.
- Monitoring signals:
  - plan status from `link_plans`
  - `link_actions` status counts
  - process liveness (`jdupes` in I/O state on large files)
  - `~/.logs/hashall/hashall.log` for error signatures

## Primary Logs and Reports

- DB refresh logs: `~/.logs/hashall/reports/db-refresh/`
- Hashall runtime log: `~/.logs/hashall/hashall.log`
- qB triage logs: `~/.logs/hashall/reports/qbit-triage/`
- stoppedDL reports: `/tmp/qb-stoppeddl-bucket-live/reports/`

## Next-Agent Checklist

1. Verify full refresh completion (all steps through payload sync + hash-root report).
2. If any step failed:
   - isolate failing device/step from logs,
   - patch root cause,
   - rerun only failed step(s),
   - confirm no regression in successful steps.
3. Re-run validations on this branch code path:
   - `PYTHONPATH=$PWD/src python3 -m hashall stats --hash-coverage`
   - syntax/compile checks for touched scripts.
4. Only after clean run + validation, finalize commits and leave clean working tree.

## Compatibility Notes

Legacy docs remain stubs pointing here:

- `docs/ops-log.md`
- `docs/handoff.md`
- `docs/next-agent.md`
- `docs/NEXT-AGENT-PROMPT.md`
- `docs/qbit-repair-handoff.md`
- `docs/qbit-repair-ops-log.md`

## Incident Update (2026-03-05)

### Scope

- Active incident: qB `missingFiles` after `/pool/data/media` -> `/pool/media` migration attempts.
- Objective this session: truth assessment, preserve DB state, apply safest remediation lane in controlled batches.

### Baseline and Artifacts

- DB backups/snapshots:
  - `out/reports/recovery-truth/db-backups/catalog-pre-refresh-20260305-194555.db`
  - `out/reports/recovery-truth/catalog-snapshot-20260305-193532.db`
- Truth reports:
  - `out/reports/recovery-truth/truth-assessment-20260305-183948.csv`
  - `out/reports/recovery-truth/truth-assessment-20260305-183948.md`
  - `out/reports/recovery-truth/refresh-upgrade-roots-20260305-195619.csv`
  - `out/reports/recovery-truth/refresh-upgrade-roots-20260305-195619-summary.json`

### Refresh Readout

- Refresh log set reviewed:
  - `/home/michael/.logs/hashall/rehome/refresh/20260305-195619.log`
  - `/home/michael/.logs/hashall/rehome/refresh/20260305-195619.json`
- Run completed `OK`, but payload upgrade stage was mostly incomplete:
  - `queued=190 started=190 completed=5 failed=0`
  - parsed summary: `zero_files=185` (most roots unresolved/missing on disk)

### qB Missing Repair Progress

- Pre-remediation baseline:
  - `missing_total=49`
  - `actionable_total=34`
  - `ambiguous_root_name_candidates=11`
  - `qb_false_missing_content_exists=4`
- Applied safe lane (`root_name_unique_candidate`) in two batches:
  - Batch A: `limit=10`, `ok=10`, `errors=0`
  - Batch B: `limit=25`, `ok=25`, `errors=0`
  - Batch C: `limit=25`, selected `22`, `ok=22`, `errors=0`
- Current post-batch state:
  - `missing_total=23`
  - `actionable_total=8`
  - `ambiguous_root_name_candidates=11`
  - `qb_false_missing_content_exists=4`
- Latest audit artifacts:
  - `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-audit-20260305-204458.json`
  - `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-remediate-plan-20260305-204458.json`

### Seeding Daemon Safety Hardening

- `bin/qbit-start-seeding-gradual.sh` hardened to fail-closed (`v1.3.4`):
  - halt if any downloading-like state exists in protected scope,
  - halt on `missingFiles`/`error` state set,
  - stop affected hashes immediately.
- Verified behavior:
  - run at `2026-03-05 20:17` halted correctly,
  - `downloading_new=0`, confirming pre-existing DL-like states were detected, not newly created by that run.

### Immediate Next Actions

1. Apply remaining safe actionable lane (8 items):
   - `bin/rehome-57_qb-missing-remediate.sh --plan /home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-remediate-plan-20260305-204458.json --mode apply --only-reason root_name_unique_candidate --limit 8 --max-apply-actions 8`
2. Re-audit:
   - `bin/rehome-56_qb-missing-audit.sh`
3. Keep seeding daemon halted until:
   - actionable lane is cleared,
   - ambiguous/false-missing lanes are explicitly triaged.
4. Triage remaining ambiguous lane via strict mapping path (`rehome-108` + `rehome-102`) before any broad auto-start operations.

### Compact-Critical Continuity Notes

- Worktree and branch context are mandatory:
  - repo: `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`
  - branch: `chatrap/codex-hashall-20260305-181919`
- Current verified state after additional apply batches and targeted recheck:
  - latest audit: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-audit-20260305-204944.json`
  - `missing_total=11`
  - `actionable_total=0`
  - remaining class:
    - `ambiguous_root_name_candidates=11`
- Safe lane is exhausted:
  - latest apply: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-remediate-20260305-204728.json`
  - `selected=8 ok=8 errors=0`
- False-missing lane resolved by explicit qB recheck:
  - rechecked hashes: `1c7dcdd96f7c4a642ef8f94df9e2c0d119dd4ee5`, `23c02140437c1e5f7d510a7e76b7dfd97bc8d5a3`, `2e3809871661d946e1dd04afafa86c9b732dbb42`, `2f4a52783dffaa01470aec79d91c2f7bad653052`
  - recheck API status: `200`
- Seeding daemon is intentionally in HALT state and must stay halted during ambiguity triage:
  - halt indicator: `/home/michael/.logs/hashall/reports/qbit-triage/daemon-halt-reset`
  - do not reset until ambiguous/false-missing lanes are resolved or explicitly accepted.
- `qbit-start-seeding-gradual.sh` hardening was first applied in a different worktree (`main`) and has not yet been ported in this chatrap worktree; re-apply/verify in this branch before daemon re-enable.
- Refresh caveat to preserve:
  - `/home/michael/.logs/hashall/rehome/refresh/20260305-195619.log` completed but upgrade stage mostly incomplete (`queued=190 completed=5`), so refresh success does not imply payload-root recovery.

## Identity Convergence Update (2026-03-06 13:55 EST)

- Root cause confirmed for remaining unresolved identity rows:
  - `/pool/media` is a separate ZFS dataset (`device_id=141`) from `/pool/data` (`device_id=231`).
  - refresh step-2 was only scanning `/pool/data` and hotspare, leaving `/pool/media` unmapped in `devices`.
- Mitigation executed:
  - small probe scan under `/pool/media` registered device `141` with fs_uuid `zfs-4673783476987974510` (`alias=pool2`).
  - final identity repair apply completed with `actions_planned=100 actions_applied=100 unresolved=0`.
  - dry-run verification now returns zero candidates:
    - `out/reports/fsuuid-identity/identity-repair-dryrun-20260306-135054-316604.json`
  - post-final audit metrics now all clean (null/unknown/mismatch counts all `0`):
    - `out/reports/fsuuid-identity/identity-drift-audit-post-final-20260306-1350.json`
- Preventive tooling update in branch:
  - `bin/db-refresh-step2-scan-pool-hotspare.sh` now scans `/pool/media` in addition to `/pool/data` and hotspare.
  - wrappers updated:
    - `bin/full-hashall-db-refresh.sh`
    - `bin/codex-says-run-this-next.sh`

### Immediate Next Commands (Post-Compact)

1. Reconfirm current missing state:
   - `bin/rehome-56_qb-missing-audit.sh`
2. False-missing lane (recheck-first):
   - run targeted remediation for non-relocation-safe items (no broad moves).
3. Ambiguous lane:
   - build strict mapping with `bin/rehome-108_nohl-basics-qb-build-strict-map.sh`
   - execute controlled pilot with `bin/rehome-102_nohl-basics-qb-repair-pilot.sh` (small limit).
4. Only after both lanes are resolved:
   - re-evaluate daemon halt and consider controlled reset.

## Incident Update (2026-03-05 21:06 EST)

### What Changed

- Applied manual ambiguity lane (`manual_ambiguous_2cand`) for 4 hashes:
  - run: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-remediate-20260305-210322.json`
  - result: `selected=4 ok=4 errors=0`
- Immediate re-audit still showed:
  - `missing_total=11`
  - `actionable_total=0`
  - class: `ambiguous_root_name_candidates=11`
  - audit: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-audit-20260305-210322.json`

### Key Root-Cause Clarification

- Daemon halt at `20:17` was not caused by the newly started batch item:
  - `downloading_new=0`
  - `downloading_preexisting=9`
  - source log: `/home/michael/.logs/hashall/reports/qbit-triage/start-seeding-gradual-20260305-201729.log`
- Safety gate behavior was correct: it detected pre-existing downloading-like torrents in protected scope and stopped them.

### Decisive Recovery Step

- Submitted explicit qB recheck for all 11 remaining ambiguous hashes, then re-ran audit:
  - latest audit: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-audit-20260305-210637.json`
  - current state: `missing_total=0`, `actionable_total=0`

### Current Operational State

- Missing-files incident is currently cleared in qB audit terms (`0 missing`).
- qB still has active downloading-like torrents unrelated to `missingFiles` count:
  - latest watch snapshot (`21:06:52`): `checking=16 missing=0 down=6 stoppedDL=15`
- Keep daemon halt/reset discipline in place until downloading-like inventory is explicitly reviewed and allowlisted or paused by policy.
