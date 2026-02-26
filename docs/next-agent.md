# Next Agent Prompt (Living)

Date context: 2026-02-26

## Mission

Continue the qbit-repair campaign from the current db-refresh stage, then run nohl-basics repair pipeline in guarded batches.

## Non-Negotiables

- User runs mutating CLI locally and shares output/log path for analysis.
- Agent does not run mutating CLI without explicit approval.
- One mutating command at a time (avoid qB restart and sqlite lock conflicts).

## Current State

- Link dedup apply plans complete: 30 (`data`), 31 (`stash`), 32 (`spare`).
- No failed actions in those plans.
- Next required pipeline step is payload sync (db-refresh step4).

## Ordered Commands

```bash
# Step 4
bin/db-refresh-step4-payload-sync.sh

# Safety gate
bin/rehome-89_nohl-basics-qb-automation-audit.sh
# If risks flagged:
bin/rehome-89_nohl-basics-qb-automation-audit.sh --mode apply

# Baseline + mapping
bin/rehome-100_nohl-basics-qb-repair-baseline.sh
bin/rehome-101_nohl-basics-qb-candidate-mapping.sh
# Optional deeper discovery if unresolved volume is high:
MAP_ENABLE_DISCOVERY_SCAN=1 bin/rehome-101_nohl-basics-qb-candidate-mapping.sh

# Pilot
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode dryrun --limit 10
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 10

# Scale
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 100
```

## Validate After Each Step

- Capture command output.
- Capture emitted log path.
- Confirm no background mutating hashall/rehome task is still running before next step.

## Open TODOs

- Investigate qbit-repair monitor edge case around `checkUP -> pausedDL/stoppedDL` transitions (`a047ce7c` symptom).
- Improve durable identity references away from ephemeral numeric `device_id`.

