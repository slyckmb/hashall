# qB Repair Handoff Entry (Compact-Safe)

Canonical operations state:
`docs/operations/RUN-STATE.md`

Critical qB repair continuity (2026-03-06):

- New guarded relocation tool now exists for dataset moves that must avoid `setLocation` as mover:
  - `bin/qb-zfs-relocate.py` (`v0.1.4`)
  - `src/hashall/qb_zfs_relocate.py`
  - phases: `plan/copy/verify/validate/patch/resume/cleanup/rollback`
  - fastresume parsing/encoding now centralizes through `src/hashall/bencode.py`
  - wrappers now preserve per-run timestamped manifests and current-manifest pointers
  - cleanup now uses staged safe automation and can be invoked standalone from a manifest or from `migrate --auto-cleanup=safe`
- Latest local validation for the relocation tooling slice:
  - `29` targeted tests passed in `tests/test_qb_zfs_relocate.py`
  - live qB migrate pilots have now executed successfully twice on 2026-03-08
  - cleanup dry-runs for both successful migrate manifests returned `blocked=0`
  - live cleanup has now completed for both successful batches and removed the four source payloads
  - resume observe now honors the configured soak window; the pool-data wrapper default is `60s`
  - latest `v0.1.4` live run completed with `resume_ok=2`, `cleaned=2`, and `blocked=0`
- Drain empty-bucket blocker is fixed:
  - commit `657eccc`
  - `bin/qb-stoppeddl-drain.py` semver `0.1.23`
  - behavior: empty `index.json` is valid no-op.
- Last observed bucket state:
  - `active=0 total_entries=0` for `stoppedDL,missingFiles,pausedDL,error`.
- Do not regress current safety posture while architecture work proceeds:
  - no broad unsafe batch starts,
  - keep guard flows fail-closed,
  - continue fs_uuid-first identity redesign in Hashall core.
- Hashall identity remediation status:
  - `hashall doctor repair-identity` and `bin/hashall-fs-identity-repair.py` are available.
  - `214` catalog identity repairs have been applied safely.
  - current identity drift candidates are `0` after `/pool/media` device mapping registration.
- Current adjacent Hashall-core refactor to preserve:
  - stable files-table binding rollout is complete.
  - do not mistake this for a qB workflow issue; the main Hashall architecture shift has already been applied to the live catalog.
  - qB follow-up work should assume `files_<device_id>` is now a compatibility layer, not the physical source of truth.

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/qbit-repair-handoff.md`
