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
- Identity repair tooling now implemented:
  - `hashall doctor repair-identity`
  - `bin/hashall-fs-identity-repair.py` (`v0.1.1`)
  - `hashall` semver now `0.4.133`
- Live catalog identity repair executed in safe passes:
  - total applied actions: `114`
  - full details and report paths in `docs/operations/RUN-STATE.md`.
- Verification:
  - targeted suites for payload/rehome/payload-sync/catalog-sync/stage4 + identity repair passed in this worktree.
- Catalog evidence to preserve:
  - unresolved identity rows are now isolated to `/pool/media` scope (100 rows);
  - unknown/legacy `device_id` remains primarily `141` in that scope;
  - parked negative `device_id` exists in `devices` (`-905882091`).
- Current blocking prerequisite for final convergence:
  - ensure `/pool/media` has valid `devices` mapping (`fs_uuid`, device_id) before rerunning identity repair.

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/handoff.md`
