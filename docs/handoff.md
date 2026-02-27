# Hashall Handoff (Living)

Last updated: 2026-02-27

## Scope

This handoff tracks the active qB repair campaign using the nohl 100/101/102/103/105/106/107 flow.
Use this as the current state, not dated session prompts.

## Execution Model

- User executes CLI locally for live monitoring.
- Agent provides commands, expected outcomes, and analysis.
- Agent only runs mutating commands with explicit approval.
- Do not run concurrent mutating commands against qB/catalog DB.

## Current Status

- Route-first autoloop (`lane_mode=route-found`) is implemented and exercised.
- Latest run log:
  - `~/.logs/hashall/reports/rehome-normalize/nohl-autoloop-v2-autoloop-20260227-102535.log`
- Latest run outcomes:
  - Round 1 apply: `selected=15 ok=1 errors=14`
  - Round 2 apply: `selected=7 ok=0 errors=7`
  - Round 3 dryrun: `selected=0` (`no_preflight_eligible_candidates`)
  - Loop stopped automatically and safely.
- Final baseline from this run:
  - `~/.logs/hashall/reports/rehome-normalize/nohl-autoloop-v2-r2-base-qb-repair-baseline-20260227-104047.json`
  - Queue snapshot: `missingFiles=10`, `stoppedDL=168`

## What Worked

- Ownership gate + lane-filtering prevented broad unsafe remaps.
- Failure quarantine and blocked-hash tracking reduced repeated churn.
- Pipeline converged to no remaining route-found preflight-eligible candidates.

## What Failed Most

- `candidate_budget_exceeded`
- `content_path_mismatch_post_move`
- Minor residual: `item_budget_exceeded`, `recheck_only_stuck_terminal`

These indicate two main classes:
1) checks that need longer budget to finish;
2) target path picks that do not match where qB resolves content after move.

## Immediate Next Step

Run one more route-first pass with safer timing and less aggressive quarantine:

```bash
APPLY_MODE=apply MAX_ROUNDS=8 BATCH_LIMIT=12 PHASE102_BATCH_SIZE=2 PHASE102_SELECTION_MODE=throughput CANDIDATE_TOP_N=2 MAPPING_TOP_N=10 CONFLICT_BLOCK_MODE=ownership-only LANE_MODE=route-found LANE_ROUTE_TOP_N=3 CANDIDATE_FAILURE_CACHE_THRESHOLD=2 PHASE102_CANDIDATE_MAX_SECONDS=420 PHASE102_ITEM_MAX_SECONDS=1500 bin/codex-says-run-this-next.sh
```

Expected result:

- Fewer false timeout failures (`candidate_budget_exceeded`).
- Better yield on large payload verification.
- Clearer separation of truly mismapped cases for sibling-build lane follow-up.

## Follow-Up After Next Run

1. Recompute failure buckets from the new `r*-apply` result JSON files.
2. If route-found again drains with low yield, switch unresolved hashes to build-from-sibling lane plan.
3. Keep ownership-only conflict block mode unless a specific conflict class regresses.

## Persistent TODOs

- Investigate qbit repair state-transition edge case (`a047ce7c` symptom).
- Device identity hardening: avoid transient numeric `device_id` as durable operator identity.
