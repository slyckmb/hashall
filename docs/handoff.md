# Handoff Entry (Compact-Safe)

Canonical living state:
- `docs/operations/RUN-STATE.md`
- `docs/project/PLAN.md`

Current branch/worktree:
- `chatrap/codex-hashall-20260305-181919`
- `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`

Current version:
- `hashall 0.4.153`

Canonical CLI:
- `hashall refresh`
- `hashall rehome ...`

Current installed surface:
- the separate `rehome` console script has been removed from packaging and from the venv
- all operator docs/examples should now use `hashall ...` only

Newest critical uncommitted/just-landed focus to preserve:
- `REUSE` no longer defaults to qB `setLocation`; it now uses offline fastresume repointing
- new helper module: `src/hashall/fastresume.py`
- `hashall rehome auto` `REUSE` apply line now reflects actual cleanup state (`cleanup pending` vs `source gone`)
- `stash` device identity was surgically repaired in the live catalog:
  - `devices.fs_uuid`: `dev-44` -> `zfs-4624186565346049802`
  - stale `/stash/media*` `scan_roots` / `scan_sessions` `dev-44` rows were rewritten
  - `hashall doctor preflight --db ~/.hashall/catalog.db` is clean again

Current operational facts:
- `~/.hashall/seed-root-state.json` is the canonical machine-readable seed-root contract.
- `hashall` is the sole writer; external tools are read-only consumers.
- `qb-stoppeddl-drain.py` and `qb-stoppeddl-apply.py` now default their allowed roots from that contract, but only admit pool-backed roots by default.
- The refresh failure where payload sync ended `PARTIAL` on zero upgrade work is fixed for future runs.
- The earlier hidden confirmation prompt and `Plan #59` `ActionInfo` crash are also fixed.

Still open:
- let the current `hashall refresh --verbose` complete after the `stash` fs_uuid repair and inspect for anomalies
- run a fresh live `REUSE qty1` pilot on the new fastresume transport
- if clean, scale `pool-data -> pool-media` `REUSE` cautiously before planning `MOVE`
- after pool migration convergence, resume `~noHL` planning/execution

Historical snapshot:
- `docs/archive/2026-doc-reduction/snapshot/docs/handoff.md`
