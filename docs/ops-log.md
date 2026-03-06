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
- Known data drift retained for remediation:
  - `payloads`: rows with `device_id in (141, NULL, 49 legacy)`;
  - `torrent_instances`: rows with `device_id in (141, NULL)`;
  - `devices`: one parked negative `device_id` row.

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/ops-log.md`
