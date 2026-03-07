# Handoff Entry (Compact-Safe)

Canonical living state:
`docs/operations/RUN-STATE.md`

Critical now (2026-03-06):

- Active branch/worktree:
  - `chatrap/codex-hashall-20260305-181919`
  - `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`
- Last safety fix:
  - commit `657eccc` (`qb-stoppeddl-drain` empty-bucket no-op behavior, `v0.1.23`).
- Live stoppedDL bucket at last run:
  - `active=0 total_entries=0`.
- Active architecture objective:
  - remove brittle `device_id` dependence from identity paths; move payload/torrent/rehome identity to `fs_uuid`.
- New coordination objective:
  - publish `~/.hashall/seed-root-state.json` from `hashall` as the only machine-readable seeding-root contract for external tools.
  - contract ownership is explicit in code/tests/docs: `hashall` sole writer, external tools read-only, fail-closed on invalid schema/owner/required fields.
- New refresh bug fixed in this worktree:
  - `hashall link execute` no longer trips `UnboundLocalError` on `ActionInfo` after refresh-created plans (observed after `Plan #59` on `spare`).
- Identity repair tooling now implemented:
  - `hashall doctor repair-identity`
  - `bin/hashall-fs-identity-repair.py` (`v0.1.1`)
  - `hashall` semver now `0.4.133`
- Live catalog identity repair executed in safe passes:
  - total applied actions: `214` (including final `/pool/media` convergence batch)
  - full details and report paths in `docs/operations/RUN-STATE.md`.
- Verification:
  - targeted suites for payload/rehome/payload-sync/catalog-sync/stage4 + identity repair passed in this worktree.
- Catalog evidence to preserve:
  - prior unresolved `/pool/media` scope has been remediated after device registration;
  - current identity drift candidates are now `0`;
  - parked negative `device_id` exists in `devices` (`-905882091`).
- Root-cause mitigation applied:
  - refresh step-2 now scans `/pool/media` in addition to `/pool/data` and hotspare.
- New active Hashall-core WIP:
  - removing the last major architectural use of volatile `device_id` by moving physical files-table binding to stable `fs_uuid`.
  - design is `devices.files_table` + stable fs_uuid-named physical tables + compatibility views named `files_<device_id>`.
- Current uncommitted file set that must be preserved:
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
  - `src/hashall/migrations/0013_stable_files_table_binding.sql`
- Current blocker before any commit/live rollout:
  - resolved. lookup paths are now read-only-safe and covered by regression tests.
- Live rollout state:
  - `hashall devices migrate-files-tables` was run on `~/.hashall/catalog.db` after copied-DB rehearsal.
  - live snapshot: `out/reports/fsuuid-files-table-live/catalog-live-pre-apply-20260306-224323.sqlite3`
  - live apply report: `out/reports/fsuuid-files-table-live/migrate-files-tables-live-apply-20260306-224323.json`
  - live post-preflight report: `out/reports/fsuuid-files-table-live/preflight-live-after-apply-20260306-224323.json`
  - resulting shape: `13` stable physical files tables and `13` compatibility views.

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/handoff.md`
