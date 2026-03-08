# Next Agent Prompt Entry (Compact-Safe)

Canonical state document:
`docs/operations/RUN-STATE.md`

Prompt-critical context (2026-03-06):

- New qB relocation tooling now exists and is the preferred next design/test path for dataset moves:
  - `bin/qb-zfs-relocate.py` (`v0.1.4`)
  - `src/hashall/qb_zfs_relocate.py`
  - guarded phases: `plan/copy/verify/validate/patch/resume/cleanup/rollback`
  - shared parser: `src/hashall/bencode.py`
  - validation slice now passes locally: `28` targeted relocation tests.
  - wrapper flows now preserve timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
  - cleanup is now staged-safe and available both standalone and via `migrate --auto-cleanup=safe`
- Use worktree/branch:
  - `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260307-234425`
  - `chatrap/codex-hashall-20260307-234425`
- Latest fixed blocker:
  - `qb-stoppeddl-drain` empty-bucket index now no-ops cleanly.
  - commit `657eccc`, script semver `0.1.23`.
- Strategic objective changed from tactical qB-only fixes to Hashall identity redesign:
  - migrate payload/torrent/rehome identity from transient `device_id` to stable `fs_uuid`.
- New identity repair tooling is now live:
  - `hashall doctor repair-identity`
  - `bin/hashall-fs-identity-repair.py` (`v0.1.1`)
  - `hashall` version now `0.4.159`.
- Known catalog inconsistencies to account for in migrations and repair logic:
  - stale/missing device identities in payload/torrent tables (`141`, `NULL`, legacy `49`).
  - parked negative `device_id` in devices table.
- Identity convergence status:
  - `/pool/media` device mapping was registered (`device_id=141`, fs_uuid `zfs-4673783476987974510`).
  - identity repair now converges with `payload_candidates=0`, `torrent_candidates=0`.
- New compact-critical WIP:
  - active refactor moved physical `files_*` table identity from volatile `device_id` to stable `fs_uuid`.
  - mechanism: `devices.files_table` + fs_uuid-derived physical table names + compatibility views for `files_<device_id>`.
  - this is no longer an uncommitted WIP; rollout was committed and applied to the live catalog.
- Current state:
  - read-only lookup bug is fixed and regression-tested.
  - live `hashall devices migrate-files-tables` execution completed successfully with snapshot + post-preflight verification.
  - next-agent work should treat fs_uuid-backed files tables as the current production model.
  - qB relocation has already completed live 2-item migrate pilots successfully on 2026-03-08 (`resume_ok=2`, `exit_code=0` for both runs).
  - cleanup dry-runs against both successful migrate manifests returned `blocked=0`, `dryrun=2`.
  - live cleanup has now completed for both successful batches; the four source payloads are gone from `/pool/data/media/torrents/seeding`.
  - resume observe now honors `PILOT_OBSERVE_SECONDS`; wrapper default is `60`.

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/NEXT-AGENT-PROMPT.md`
