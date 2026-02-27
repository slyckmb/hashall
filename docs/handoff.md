# Hashall Handoff (Living)

Last updated: 2026-02-27

## Scope

This handoff tracks the active qB repair campaign and qB seeding guard tooling.
Use this as the current state, not dated session prompts.

## Execution Model

- User executes CLI locally for live monitoring.
- Agent provides commands, expected outcomes, analysis, and targeted patches.
- Agent only runs mutating commands with explicit approval from user.
- Do not run concurrent mutating commands against qB/catalog DB.

## Current Status

- Shared qB polling cache is now available and wired into two tools:
  - `bin/qbit-cache-daemon.py` (lease-based daemon, exits after idle grace)
  - `bin/qbit-cache-agent.py` (lease renew + `--ensure-daemon` + `--status`)
  - `bin/qbit-start-seeding-gradual.sh --cache --cache-max-age N`
  - `bin/rehome-99_qb-checking-watch.sh --cache --cache-max-age N`
- `qbit-start-seeding-gradual.sh` is patched for two live issues:
  - Removed argv-size failure (`Argument list too long`) by reading large JSON payload from temp files.
  - Safety gate changed to flip-only behavior:
    - HALT only on newly flipped downloading-like hashes after a batch.
    - Pre-existing downloading-like hashes are logged but do not trigger HALT.
- `qbit-start-seeding-gradual.sh` version is now `1.3.1`.

## What Worked

- Shared cache mode reduced direct qB polling contention across scripts.
- Flip-only safety gate matches operational intent: "do not allow new flips to downloading."
- Guard scripts remain fail-closed on parsing/fetch errors.

## Current Risks

- Pre-existing downloading-like hashes in protected scope are still present and must be handled in repair flow.
- Remaining unresolved queue objective remains:
  - `stoppedDL=168`
  - `missingFiles=10`
- `--resume` flag in `qbit-start-seeding-gradual.sh` is currently a no-op and should be cleaned up or implemented.

## Next Ordered Steps

1. Restart seeding daemon command on patched script version:
   - `bin/qbit-start-seeding-gradual.sh --daemon --apply --min-batch 1 --poll 15 --cache --cache-max-age 15`
2. Confirm daemon logs show:
   - `downloading_new=<N>` and `downloading_preexisting=<N>`
   - HALT only when `downloading_new > 0`
3. Continue phase-2 relink workflow for unresolved hashes while monitoring with cache-enabled watchdog:
   - `bin/rehome-99_qb-checking-watch.sh --enforce-paused-dl --cache --cache-max-age 5 --interval 15`
