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
  - `bin/qb-zfs-relocate.py` (`v0.1.4`)
  - `src/hashall/qb_zfs_relocate.py`
  - phases: `plan/copy/verify/validate/patch/resume/cleanup/rollback`
  - migrate now supports `--auto-cleanup=safe` with staged `rename -> observe -> delete`
  - resume observation now honors the configured soak window instead of short-circuiting immediately on first healthy check
  - pool-data wrapper default `PILOT_OBSERVE_SECONDS` is now `60`
  - cleanup now live-validates qB state, verify evidence, path safety, and overlap rules before any delete path
  - wrappers now write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
- Shared bencode/fastresume groundwork added:
  - `src/hashall/bencode.py`
  - strict full-consumption decode now backs fastresume mutation.
- Repo-local CLI bootstrap added:
  - `python3 -m hashall` now resolves from repo root via local bootstrap packages.
- Latest local validation for this tooling slice:
  - `pytest tests/test_qb_zfs_relocate.py -q`
  - result: `29 passed`
- Live relocation status:
  - successful migrate runs observed at `12:03` and `12:30` on 2026-03-08
  - both completed with `resume_ok=2` and `exit_code=0`
  - cleanup dry-runs against both successful manifests returned `blocked=0`, `dryrun=2`, `source_missing=0`
  - live cleanup has now completed for both successful manifests; four source payloads were removed from `/pool/data/media/torrents/seeding`
  - latest `v0.1.4` run at `14:33` completed with `resume_ok=2`, `cleaned=2`, `blocked=0`, and a full `60s` resume observe window

Latest rehome integration note (2026-03-08):

- `hashall` is now `0.4.164`.
- Commit `e572bf8` added explicit root-to-root relocation planning in `rehome`:
  - new CLI: `hashall rehome relocate-plan`
  - new core planner path in `src/rehome/normalize.py`
  - supports batch plans for explicit moves like `/pool/data/media/torrents/seeding -> /pool/media/torrents/seeding`
  - synthesizes unique destination sibling views under `_rehome-unique/<hash>` when a shared-root group would otherwise collide on the same target view
- Commits `d553f20` and `264ec25` closed the next execution gap:
  - new CLI: `hashall rehome qb-missing-audit`
  - `rehome apply` now routes donor verification / offline fastresume mutation through the guarded `qb-zfs-relocate` backend
  - `MOVE` source cleanup is now deferred instead of deleting source payloads immediately
- Commit `65eaa82` added a stale-root remediation step to `qb-zfs-relocate`:
  - source missing + destination already present now becomes `copy_status=reused_existing_dest`
  - this allows legacy root-drift items to reuse the already-good `/pool/media/...` payload instead of failing in copy
- Live audit result for the current qB `missingFiles` cohort:
  - `49` items currently classified by the tool as `root_drift_fastresume_stale`
  - evidence: old `/pool/data/...` qB + fastresume paths, mapped `/pool/media/...` payload present
  - interpretation: legacy stale-root path drift, not new `qb-zfs-relocate` corruption
- Latest live stale-root remediation pilot status:
  - refresh was not hung; it finished `PARTIAL` because payload sync hit `24` zero-file old-root upgrade entries from this same cohort
  - `qb-start-seeding-gradual` halt set of `35` hashes is a subset of the audited `49`
  - explicit dry-run pilot on `Stranger.Things.S02` (`3` hashes) reused existing destination payload and verified all `3` hashes as `exact_tree`
  - current uncommitted blocker: `validate` still rejects these rows with `torrent_not_complete` because qB reports stale `progress=0.0`
- Latest validation for this slice:
  - `pytest tests/test_rehome_atomic_relocation.py tests/test_rehome_catalog_sync.py tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py -q`
  - result: `47 passed`
  - `hashall rehome relocate-plan --help`
  - `hashall rehome qb-missing-audit --help`
  - `pytest tests/test_qb_zfs_relocate.py -q`
  - result after commit `65eaa82`: `33 passed`

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/ops-log.md`

Latest repair/handoff note (2026-03-10):

- `hashall` is now `0.4.168`.
- Commit `5d83419` hardened payload-group repair:
  - `bin/qb-repair-payload-group.sh` is now a thin launcher over `src/hashall/qb_repair_payload_group.py`
  - validates `payload_hash` equality before apply
  - matches files by relative path, not basename
  - uses shared fastresume backup/journal logic instead of ad hoc in-place mutation
  - writes per-run artifacts under `out/qb-repair-payload-group/<stamp>-<hash>/`
  - targeted validation passed locally:
    - `pytest tests/test_fastresume.py tests/test_qb_repair_payload_group.py -q`
    - result: `8 passed`
- Live qB repair progress:
  - commit `fe6b0fb` fixed qB API readiness checks used by the repair restart path
  - `0fff0ce260a58b789f857f6ad085a5d03622b952` repaired successfully from donor `4511c5f4149223175792ca180eea5a41655abea4`
  - qB now reports that hash as `stoppedUP 100%`
  - current non-healthy qB lane is down to `6` `stoppedDL`
  - current qB state snapshot:
    - `stalledUP=5138`
    - `uploading=5`
    - `stoppedDL=6`
    - `stoppedUP=1`
- Hardened repair artifacts:
  - initial dry-run artifact:
    - `out/qb-repair-payload-group/20260310-102047-0fff0ce260a5/repair-plan.json`
  - successful live apply artifact:
    - `out/qb-repair-payload-group/20260310-164254-0fff0ce260a5/repair-plan.json`
- Remaining blocker classification:
  - `1feb6eda...`, `4bfee343...`, `57c38fa8...`, `aa0a5bbb...` each miss one `.nfo`
  - `e2d30cbf...` misses `23` `.srt` files
  - `f51bd14b...` misses `7` `.srt` files
  - exact local copies of those missing sidecar filenames were not found in the current catalog
- Separate repo issue is no longer open:
  - commit `74ea2b5` fixed `hashall payload siblings` to open catalogs read-only
