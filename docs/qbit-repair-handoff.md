# qB Repair Handoff Entry (Compact-Safe)

Canonical operations state:
`docs/operations/RUN-STATE.md`

Critical qB repair continuity (2026-03-06):

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
