# Project Plan (Canonical)

Last updated: 2026-02-28
Status: active

## Purpose

Unified roadmap + active backlog for development and operations.

## Near-Term Priorities

1. Stabilize qB stoppedDL recovery loop.
2. Reduce repeated verification cost while increasing first-pass precision.
3. Finish fs_uuid-first files-table binding so reboot/remount `device_id` churn stops breaking catalog identity.
4. Keep documentation canonical and low-friction for agent handoffs.

## Active Task Tracker

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
