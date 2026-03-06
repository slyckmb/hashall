# qB Repair Ops Log Entry (Compact-Safe)

Canonical operations state:
`docs/operations/RUN-STATE.md`

Latest qB repair ops markers (2026-03-06):

- bucket sync loop currently clean (`active=0`).
- drain no-op behavior corrected (empty index no longer hard-fails).
- known root issue for broader incident remains architecture-level:
  - stale/missing identity data tied to `device_id` drift in catalog tables.
- active program of work:
  - move identity to durable `fs_uuid` across payload/torrent/rehome workflows.
- current identity-repair state:
  - new tooling live (`hashall doctor repair-identity`, `bin/hashall-fs-identity-repair.py v0.1.1`)
  - 214 repairs applied total; unresolved set now cleared (`0`).

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/qbit-repair-ops-log.md`
