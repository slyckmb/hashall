# Ops Log Entry (Compact-Safe)

Canonical living state:
`docs/operations/RUN-STATE.md`

Latest critical operations note (2026-03-06):

- `qb-stoppeddl-bucket` now clean (`active=0 total_entries=0`) in live checks.
- `qb-stoppeddl-drain` empty-index error fixed:
  - commit `657eccc`
  - semver `v0.1.23`
  - behavior: valid empty bucket returns `selected=0` no-op.
- Current strategic ops shift:
  - stop treating `device_id` as durable identity;
  - implement `fs_uuid`-first identity path for payload/torrent/rehome flows.
- New repair path is active:
  - `hashall doctor repair-identity`
  - `bin/hashall-fs-identity-repair.py` (`v0.1.1`)
- Live repair progress:
  - `214` identity actions applied on `~/.hashall/catalog.db` (including final `/pool/media` batch).
  - current repair dry-run reports `payload_candidates=0`, `torrent_candidates=0`, `unresolved=0`.
- Residual catalog risks:
  - parked negative `device_id` row remains in `devices` (`-905882091`).
  - ensure refresh step-2 continues scanning `/pool/media` to avoid reintroducing unknown device rows.
- New architecture WIP now active and uncommitted:
  - move physical `files_*` storage binding from volatile `device_id` to stable `fs_uuid` via `devices.files_table`.
  - keep `files_<device_id>` only as compatibility views.
  - migration: `src/hashall/migrations/0013_stable_files_table_binding.sql`.
- Rollout status:
  - blocker cleared, targeted suite green, migration workflow hardened with dry-run/apply/snapshot/report.
  - copied-DB rehearsal succeeded.
  - live `~/.hashall/catalog.db` migration completed with snapshot and post-apply preflight `ok=true`.

Latest tooling note (2026-03-08):

- Guarded qB dataset relocation workflow added:
  - `bin/qb-zfs-relocate.py` (`v0.1.3`)
  - `src/hashall/qb_zfs_relocate.py`
  - phases: `plan/copy/verify/validate/patch/resume/cleanup/rollback`
  - migrate now supports `--auto-cleanup=safe` with staged `rename -> observe -> delete`
  - cleanup now live-validates qB state, verify evidence, path safety, and overlap rules before any delete path
  - wrappers now write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
- Shared bencode/fastresume groundwork added:
  - `src/hashall/bencode.py`
  - strict full-consumption decode now backs fastresume mutation.
- Repo-local CLI bootstrap added:
  - `python3 -m hashall` now resolves from repo root via local bootstrap packages.
- Latest local validation for this tooling slice:
  - `pytest tests/test_qb_zfs_relocate.py -q`
  - result: `28 passed`
- Live relocation status:
  - successful migrate runs observed at `12:03` and `12:30` on 2026-03-08
  - both completed with `resume_ok=2` and `exit_code=0`
  - cleanup dry-runs against both successful manifests returned `blocked=0`, `dryrun=2`, `source_missing=0`
  - live cleanup has now completed for both successful manifests; four source payloads were removed from `/pool/data/media/torrents/seeding`

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/ops-log.md`
