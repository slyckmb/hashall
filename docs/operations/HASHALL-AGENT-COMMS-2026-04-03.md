# Hashall Agent Comms — 2026-04-03

## Status

- The residual `Bullet Train` stash reuse family that was looping on `dest_missing` is now fixed.
- The fix is in `src/rehome/executor.py`.
- Execution result:
  - `10/10` sibling rows verified successfully in the `20260403-010351-8b5c09e0c7c083bf` report
  - qB patch completed
  - stash source cleanup remains deferred by design

## What changed

- Reuse verification now handles mixed families where some siblings are flat-file targets and others are wrapped single-entry targets.
- Fallback wrapper views are constructed when the planner did not emit explicit `view_targets` but torrent metadata proves a nested single-entry layout.

## Direction for other agents

- Do not re-open the old `Bullet Train` `dest_missing` issue unless a new failing hash appears.
- Do not restart the broad unattended maintenance loop blindly.
- The current safe next stash reuse queue is only:
  - `The Muppet...`
  - `Le...`
- If another repo needs to reason about current `hashall` stash reuse safety, treat `Bullet Train` as closed and the queue as narrowed to those two items.
