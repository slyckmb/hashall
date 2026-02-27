# Next Agent Prompt (Living)

Date context: 2026-02-27

## Mission

Continue the qB repair campaign with route-first execution, then pivot remaining hashes into sibling-build workflow if route lane is exhausted.

## Non-Negotiables

- User runs mutating CLI locally and shares output/log path for analysis.
- Agent does not run mutating CLI without explicit approval.
- One mutating command at a time (avoid qB restart and sqlite lock conflicts).

## Current State

- Latest route-first autoloop completed:
  - `~/.logs/hashall/reports/rehome-normalize/nohl-autoloop-v2-autoloop-20260227-102535.log`
- Rounds:
  - `r1 apply: selected=15 ok=1 errors=14`
  - `r2 apply: selected=7 ok=0 errors=7`
  - `r3 dryrun: selected=0 (no_preflight_eligible_candidates)`
- Dominant failure modes in latest run:
  - `candidate_budget_exceeded`
  - `content_path_mismatch_post_move`

## Primary Command (Next Run)

```bash
APPLY_MODE=apply MAX_ROUNDS=8 BATCH_LIMIT=12 PHASE102_BATCH_SIZE=2 PHASE102_SELECTION_MODE=throughput CANDIDATE_TOP_N=2 MAPPING_TOP_N=10 CONFLICT_BLOCK_MODE=ownership-only LANE_MODE=route-found LANE_ROUTE_TOP_N=3 CANDIDATE_FAILURE_CACHE_THRESHOLD=2 PHASE102_CANDIDATE_MAX_SECONDS=420 PHASE102_ITEM_MAX_SECONDS=1500 bin/codex-says-run-this-next.sh
```

## Why This Tuning

- `PHASE102_CANDIDATE_MAX_SECONDS=420` and `PHASE102_ITEM_MAX_SECONDS=1500` reduce timeout-driven false failures.
- `CANDIDATE_FAILURE_CACHE_THRESHOLD=2` prevents immediate quarantine on first failure.
- `PHASE102_BATCH_SIZE=2` lowers concurrent check pressure and contention.
- `LANE_MODE=route-found` keeps high-risk sibling routes out of this pass.

## Post-Run Checklist

1. Extract `r*-apply` summaries from the new autoloop log.
2. Count failure buckets from new `*-apply-qb-repair-pilot-result-*.json`.
3. If route lane drains again with low yield, run lane plan for sibling-build path and stop route-only retries.

## Open TODOs

- Investigate qbit-repair monitor edge case around `checkUP -> pausedDL/stoppedDL` transitions (`a047ce7c` symptom).
- Improve durable identity references away from ephemeral numeric `device_id`.
