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
  - `114` identity actions applied on `~/.hashall/catalog.db`.
  - post-repair unresolved candidate scope is `100` rows, all under `/pool/media`.
  - no further auto-fixes remain until `/pool/media` is represented correctly in `devices`.
- Residual catalog risks:
  - stale `device_id=141` rows remain on `/pool/media`;
  - parked negative `device_id` row remains in `devices` (`-905882091`).

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/ops-log.md`
