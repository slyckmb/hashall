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
- qB gradual seeding daemon fixed to halt only on newly flipped downloading-like states.

## What Is True Now

- qB must not be the byte mover.
- `REUSE` is the correct model once donor already exists at target.
- `MOVE` must be refactored to match the same attach/repoint path after external transfer.
- Current `MOVE` apply is not safe for scale yet.

## Immediate Next Work

1. Finish the remaining pool `REUSE` batches in small steps.
2. Fix cleanup-source path/provenance drift.
3. Refactor `MOVE` into:
   - donor acquisition by external transfer
   - shared offline attach/repoint
4. Pilot `MOVE`.
5. Then resume planning for `~noHL`.

## Key Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Do Not Forget

- use `hashall ...`, not `rehome ...`
- do not reintroduce qB `setLocation` as the normal migration primitive
- do not scale `MOVE` before the shared attach refactor lands
