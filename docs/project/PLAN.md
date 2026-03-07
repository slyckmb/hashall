# Project Plan (Canonical)

Last updated: 2026-03-07
Status: active

## Purpose

Unified roadmap + active backlog for development and operations.

## Near-Term Priorities

1. Stabilize qB stoppedDL recovery loop.
2. Reduce repeated verification cost while increasing first-pass precision.
3. Finish fs_uuid-first files-table binding so reboot/remount `device_id` churn stops breaking catalog identity.
4. Keep documentation canonical and low-friction for agent handoffs.

## Active Task Tracker

### Refresh / Migration Hardening Program (2026-03-07)

- [ ] Monitor live `rehome refresh` runs and fix any anomalies that appear during active execution.
- [ ] Build a compact anomaly ledger from `~/.logs/hashall/rehome/refresh/` with root cause, impact, fix, and status.
- [ ] Audit all remaining `device_id`-first code paths and complete the transition to `fs_uuid` as durable identity.
- [ ] Verify runtime-only use of `device_id` is limited to hardlink-boundary and current-mount lookup concerns.
- [ ] Collapse operational docs to a minimal canonical handoff set:
  - `docs/operations/RUN-STATE.md`
  - `docs/project/PLAN.md`
  - `docs/handoff.md`
  - archive all other handoff/status variants or turn them into pointers
- [ ] Audit qBit repair, rehome, and migration tooling for silent-failure patterns:
  - parser drift
  - unsafe default apply behavior
  - interactive prompts inside non-interactive orchestrators
  - long silent pauses with no heartbeat/progress feedback
  - stale cache / stale qB state assumptions
  - cross-filesystem donor selection
  - save-path / content-path mismatch handling
  - hardlink / inode preservation assumptions
- [ ] Review the current refresh long-pause behavior and fix operator feedback:
  - identify where orchestration can block on hidden confirmation prompts
  - emit heartbeat/progress lines during long-running steps
  - surface “waiting for confirmation” explicitly if a subprocess is interactive
  - identify secondary logs to watch during quiet periods
- [ ] Harden qBit migration/rehome workflows with explicit safety gates:
  - fail-closed on ambiguity
  - dry-run-first with machine-readable plan output
  - post-apply qB state validation
  - download-prevention guardrails
  - scope verification against filesystem and qB save path
- [ ] Define the production process to finish the dataset migration from:
  - `/pool/data/media/torrents/seeding`
  - to `/pool/media/torrents/seeding`
- [ ] Decide whether the dataset migration should use:
  - existing rehome/hashall tooling after hardening
  - a new dedicated qB dataset-rehome tool
  - or a hybrid approach
- [ ] Produce a pilot-safe migration lane for one payload class, validate end to end, then scale by batch.
- [ ] Evaluate rehome readiness for resuming `~noHL` stash -> pool moves and document blockers separately from dataset-migration blockers.

### Ordered Execution Plan

1. Keep the active refresh under observation and capture any new anomalies in real time.
2. Finish the fs_uuid transition audit so identity drift is no longer a confounding variable.
3. Reduce docs to the minimum canonical set before more changes land.
4. Audit and harden qBit migration/rehome tooling algorithms and safety model.
5. Choose and validate the dataset-migration process/tooling for `/pool/data/...` -> `/pool/media/...`.
6. Reassess `~noHL` rehome readiness after the above hardening removes shared failure modes.

### Exit Criteria

- [ ] `rehome refresh` no longer shows silent dedup or payload-sync quality anomalies.
- [ ] No critical workflow depends on brittle numeric `device_id` for durable identity.
- [ ] Canonical docs are reduced to one run-state doc, one plan doc, and one short handoff doc.
- [ ] qBit repair and migration workflows have explicit dry-run, scope verification, and post-apply safety gates.
- [ ] A validated, low-risk process exists for `/pool/data/media/torrents/seeding` -> `/pool/media/torrents/seeding`.
- [ ] A separate, validated resume plan exists for `~noHL` stash -> pool movement.

### fs_uuid Files-Table Migration

- [x] Land fs_uuid-first payload/torrent identity layer (`0012_fs_uuid_identity.sql` + model/write-path propagation).
- [x] Repair live catalog identity drift and converge `/pool/media` registration.
- [x] Design stable files-table binding around `devices.files_table` plus compatibility views named `files_<device_id>`.
- [x] Add migration draft `src/hashall/migrations/0013_stable_files_table_binding.sql`.
- [x] Patch core callers to resolve files tables through helper instead of raw `f"files_{device_id}"` in the main WIP files.
- [x] Fix the current blocker: make files-table lookup read-only-safe so `payload sync --dry-run` stops throwing `sqlite3.OperationalError: attempt to write a readonly database`.
- [ ] Split lookup from mutation cleanly across the whole binding layer: resolution helpers must not update `devices`, create views, rename tables, or create indexes unless explicitly in an apply path.
- [x] Update preflight checks to validate resolved fs_uuid-backed bindings instead of assuming physical `files_<device_id>` tables.
- [x] Update cross-device analysis/reporting to enumerate stable physical files tables from `devices.files_table` and ignore compatibility views as physical truth.
- [x] Sweep remaining direct physical-table assumptions in source and either migrate them to helper-based resolution or label them as intentional compatibility shims.
- [x] Harden `hashall devices migrate-files-tables` into a safe workflow with `--dry-run`, DB snapshot, report output, device filtering, and post-apply verification.
- [x] Decide and implement policy for `dev-{device_id}` fallback identities on managed roots: block, degrade, or explicitly quarantine them.
- [x] Add targeted regression tests for read-only lookup, compatibility views, preflight, cross-device analysis, and device-id rotation.
- [x] Re-run targeted green suite for device/scan/payload/payload-sync/treehash/preflight/link-analysis paths.
- [ ] Bump semver after code is green.
- [ ] Commit logical changes with detailed conventional commits.
- [ ] Update canonical architecture/requirements docs so they describe `fs_uuid` as durable identity and `device_id` as runtime hardlink-boundary metadata only.
- [x] Validate on a copied catalog DB first, then on a fresh snapshot of `~/.hashall/catalog.db`, and only then consider live apply.

### Current Status

- Previous blocker cleared:
  - `tests/test_cli_payload_sync.py::TestPayloadSyncCLI::test_payload_sync_remaps_alternate_mountpoints_for_prefix_filtering`
  - fixed by making `get_files_table_name()` stop backfilling `devices.files_table` on lookup-only paths.
- Live status:
  - fs_uuid-backed files-table migration is now applied to `~/.hashall/catalog.db`
  - preflight passes after live apply
  - remaining follow-up is monitoring, cleanup, and any future reduction of compatibility-surface assumptions

## Active Engineering Backlog

### Diff Engine and Core Completeness

- Implement remaining `src/hashall/diff.py` TODO logic.
- Add targeted tests for diff behavior and regression protection.

### Operational Hardening

- Improve long-running command progress visibility.
- Harden idempotent restart behavior in automation loops.
- Continue reducing stale-plan and stale-state failure modes.

### Data Integrity

- Maintain SHA256 backfill and verification coverage.
- Continue payload uniqueness and ownership audit workflows.

## Deferred / Nice-to-Have

- Additional UI/reporting polish.
- Extended automation around periodic audits.
- Lower-priority tooling cleanup beyond canonical workflows.

## Source Backlog

Legacy TODO content moved from root `TODO.md`:
- See `docs/archive/2026-doc-reduction/snapshot/docs/project/TODO.md` for preserved pre-consolidation details.
