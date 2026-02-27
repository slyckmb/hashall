# Hashall Ops Log (Living)

Last updated: 2026-02-27

## Execution Model

- User runs all mutating CLI locally to monitor live behavior.
- Agent does not run mutating CLI commands without explicit approval.
- Run one mutating pipeline command at a time to avoid qB/db contention.

## Current Snapshot

- Active repair path is route-first nohl pipeline:
  - `rehome-100` baseline
  - `rehome-101 --tracker-aware --manifest-aware`
  - `rehome-103` ownership audit
  - `rehome-105` autoloop with `lane_mode=route-found`
- Latest autoloop run:
  - Log: `~/.logs/hashall/reports/rehome-normalize/nohl-autoloop-v2-autoloop-20260227-102535.log`
  - Round 1: `selected=15 ok=1 errors=14 fallback_used=1`
  - Round 2: `selected=7 ok=0 errors=7 fallback_used=1`
  - Round 3 dryrun: `selected=0 reason=no_preflight_eligible_candidates`
  - Autoloop exited cleanly after route-found candidates were exhausted.
- Queue moved from `179` to `178` in this run (`missingFiles=10`, `stoppedDL=168` at final baseline).
- Route-found lane filtering is working and prevents broad churn:
  - Round 1 lane-filtered entries: `21`
  - Round 2 lane-filtered entries: `13`
  - Round 3 lane-filtered entries: `6`, then preflight rejected remaining entries.

## This Run: Failure Mix

- `candidate_budget_exceeded`: 11
- `content_path_mismatch_post_move`: 8
- `item_budget_exceeded`: 1
- `recheck_only_stuck_terminal`: 1
- Confirmed success in run: hash `83c53ae8` reached `final_state=stoppedup`.

## Known Issues / TODO

- `qbit-repair-batch`: investigate hash tracking around `checkUP -> pausedDL/stoppedDL` transitions.
  - Example: `a047ce7c` observed at ~83% in qB while script still treated it as persistent `stoppedDL`.
- High `content_path_mismatch_post_move` indicates target-root mismatch for a subset of route-found picks.
- `candidate_budget_exceeded` dominates remaining route-found work when budgets are too tight.
- SQLite lock contention still appears under concurrent heavy operations; keep single-writer discipline.
- Device identity hardening TODO: prefer stable filesystem identity over transient numeric `device_id`.

## Next Ordered Steps

1. Re-run route-first autoloop with larger wait budgets and higher failure-cache threshold:
   - `CANDIDATE_FAILURE_CACHE_THRESHOLD=2`
   - `PHASE102_CANDIDATE_MAX_SECONDS=420`
   - `PHASE102_ITEM_MAX_SECONDS=1500`
   - Smaller wave size (`PHASE102_BATCH_SIZE=2`)
2. Re-check error mix after run; if `content_path_mismatch_post_move` remains dominant, shift unresolved hashes to sibling-build lane workflow.
3. Keep `CONFLICT_BLOCK_MODE=ownership-only` and `LANE_MODE=route-found` until route lane is fully drained.

## Log Locations

- qbit triage logs: `~/.logs/hashall/reports/qbit-triage/`
- nohl pipeline logs: `~/.logs/hashall/reports/rehome-normalize/`
- db-refresh logs: `~/.logs/hashall/reports/db-refresh/`
- hashall runtime log: `~/.logs/hashall/hashall.log`
