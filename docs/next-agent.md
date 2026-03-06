# Next Agent Entry (Compact-Safe)

Primary run-state source:
`docs/operations/RUN-STATE.md`

If context is compacted, recover with this sequence:

1. Confirm branch/worktree:
   - `chatrap/codex-hashall-20260305-181919`
   - `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`
2. Confirm stoppedDL pipeline baseline:
   - run `qb-stoppeddl-bucket` and verify `active=0` or current live count.
   - note: drain no-op fix is commit `657eccc` (`v0.1.23`).
3. Continue architecture task in progress:
   - replace identity dependence on `device_id` with `fs_uuid` in payload/torrent/rehome core flows.
   - current implementation-in-progress already includes:
     - migration `0012_fs_uuid_identity.sql`
     - fs_uuid-aware payload/torrent writes and planner/executor propagation.
   - new repair path now available:
     - `hashall doctor repair-identity`
     - `bin/hashall-fs-identity-repair.py` (`v0.1.1`)
     - `hashall` semver is `0.4.133`
4. Preserve and remediate known drift:
   - `payloads`/`torrent_instances` rows with missing or stale `device_id` values.
   - parked negative `device_id` row in `devices`.
5. Current unresolved identity bucket:
   - 100 rows remain and all are `/pool/media` scoped.
   - no further auto-repair actions exist until `/pool/media` has valid `devices` mapping.

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/next-agent.md`
