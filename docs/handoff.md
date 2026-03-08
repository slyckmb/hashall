# Handoff (Canonical)

Use these three docs only:

- `docs/project/PLAN.md`
- `docs/operations/RUN-STATE.md`
- `docs/handoff.md`

## Current State

- Branch: `chatrap/codex-hashall-20260305-181919`
- Worktree: `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`
- Canonical CLI: `hashall`
- Package version: `0.4.153`

## What Is Done

- `hashall` is now the sole operator CLI.
- `rehome` console script removed from packaging.
- `stash` fs_uuid repaired live from `dev-44` to `zfs-4624186565346049802`.
- `hashall refresh --verbose` is healthy again.
- `REUSE` no longer uses qB `setLocation` by default.
- latest `REUSE` pilot succeeded with offline fastresume repointing.
- `MOVE` now uses the same offline donor-attach path instead of qB relocation semantics after copy.
- `pool-data -> pool-media` now shows `0 MOVE groups available` in dry-run; planner considers that phase exhausted.
- qB gradual seeding daemon fixed to halt only on newly flipped downloading-like states.

## What Is True Now

- qB must not be the byte mover.
- `REUSE` is the correct model once donor already exists at target.
- `MOVE` now matches the same attach/repoint path after external transfer.
- Current `MOVE` code still needs one live pilot before it is safe to scale.
- active next live gate is `stash -> pool-media` `REUSE` pilot `rehome_runs.id=338`

## Immediate Next Work

1. Fix cleanup-source path/provenance drift.
2. Confirm `stash -> pool-media` pilot `338` completes cleanly.
3. If clean, scale stash/noHL `REUSE` cautiously.
4. Pilot `MOVE` only if the planner surfaces a real move case again.
5. Then continue `~noHL`.

## Key Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Do Not Forget

- use `hashall ...`, not `rehome ...`
- do not reintroduce qB `setLocation` as the normal migration primitive
- do not scale `MOVE` before the first live pilot proves the new path
