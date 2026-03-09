# Next Agent Entry (Compact-Safe)

Primary run-state source:
`docs/operations/RUN-STATE.md`

If context is compacted, recover with this sequence:

0. Recover the new guarded qB relocation tooling state:
   - `bin/qb-zfs-relocate.py` (`v0.1.4`)
   - `src/hashall/qb_zfs_relocate.py`
   - `src/hashall/bencode.py`
   - repo-root `python3 -m hashall` bootstrap now works via local `hashall/` + `rehome/` packages.
   - wrapper runs now keep timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
1. Confirm branch/worktree:
   - `chatrap/codex-hashall-20260307-234425`
   - `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260307-234425`
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
     - `hashall` semver is `0.4.159`
4. Preserve and remediate known drift:
   - `payloads`/`torrent_instances` rows with missing or stale `device_id` values.
   - parked negative `device_id` row in `devices`.
5. Identity repair status now:
   - `/pool/media` mapping has been registered in `devices` (`device_id=141`).
   - identity repair dry-run returns zero candidates and zero unresolved.
   - keep refresh step-2 scanning `/pool/media` to prevent recurrence.
6. Active uncommitted WIP is broader than identity repair:
   - implemented and rolled out: `devices.files_table` now owns stable physical binding.
   - compatibility plan remains active: `files_<device_id>` are views, not physical truth.
7. First thing to recover after compact:
   - read `docs/operations/RUN-STATE.md` sections:
     - `Stable Files Table Binding WIP`
     - `Copied-DB Validation`
     - `Live Files-Table Migration Execution`
8. Current posture:
   - live migration is complete.
   - next work is to unify `rehome` planning with the hardened `qb-zfs-relocate` MOVE transport.
9. qB relocation-specific current state:
   - live `pool-data -> pool-media` migrate pilots have succeeded via `qb-zfs-relocate`
   - cleanup is now staged-safe and can run standalone from a manifest or via `migrate --auto-cleanup=safe`
   - cleanup dry-runs for both successful migrate batches returned `blocked=0`
   - live cleanup has now completed for both successful batches and removed the four migrated source payloads
   - resume observe now respects its configured soak window; the wrapper default is `60s`
   - latest `v0.1.4` live run completed cleanly with `resume_ok=2`, `cleaned=2`, and no cleanup blocks
10. New planner continuity to preserve:
   - `hashall rehome relocate-plan` now exists in commit `e572bf8`
   - `hashall` semver is `0.4.162`
   - planner lives in `src/rehome/normalize.py`
   - it can plan explicit root-to-root relocations and synthesize unique target views for shared-root sibling collisions
   - this is a planner-only integration step; `rehome apply` still needs the hardened `qb-zfs-relocate` MOVE backend merged in
11. First thing to do after compact if the task continues:
   - run `hashall rehome relocate-plan --help`
   - inspect `src/rehome/normalize.py`
   - decide whether to merge `qb-zfs-relocate` transport primitives into `rehome executor` directly or extract them into shared library code first

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/next-agent.md`
