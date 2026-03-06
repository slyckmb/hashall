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
- Implemented in this worktree (not yet committed):
  - migration `src/hashall/migrations/0012_fs_uuid_identity.sql`
  - fs_uuid-aware payload/torrent model writes in `src/hashall/payload.py`
  - payload-sync propagation in `src/hashall/cli.py`
  - fs_uuid-carrying executable plans in `src/rehome/planner.py`
  - fs_uuid-to-device resolution in `src/rehome/executor.py`
  - version bumps: hashall `0.4.131`, rehome `0.6.1`
- Verification:
  - targeted suites for payload/rehome/payload-sync/catalog-sync/stage4 passed in this worktree.
- Catalog evidence to preserve:
  - unknown/legacy `device_id` rows remain in `payloads` and `torrent_instances` (`141`, `NULL`, legacy `49`);
  - parked negative `device_id` exists in `devices` (`-905882091`).
- WIP in tree:
  - multiple files modified for fs_uuid rollout; see `git status --short`.

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/handoff.md`
