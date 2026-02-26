# Hashall Handoff (Living)

Last updated: 2026-02-26

## Scope

This handoff is for the qbit-repair + db-refresh + nohl-basics repair campaign.
Use this document as the current-state source, not dated session docs.

## Execution Model

- User executes CLI locally for live monitoring.
- Agent provides commands, expected outcomes, and analysis.
- Agent only runs mutating commands with explicit approval.
- Do not run concurrent mutating commands against qB/catalog DB.

## Preconditions

1. Work from the active chatrap worktree for this session.
2. Use the branch associated with the active chatrap session.
3. Confirm no overlapping long-running hashall command is active before starting a new one.

## Completed Milestones

- qbit-repair script hardened through v1.6.1 (BUG-8 included).
- UUID migration completed before db refresh rescans.
- db-refresh step1 and step2 scans completed.
- db-refresh step3 collision upgrade completed with lock-wait handling.
- db-refresh step3.5 link dedup apply completed for plans 30/31/32 with zero failed actions.

## Immediate Next Step

Run:

```bash
bin/db-refresh-step4-payload-sync.sh
```

Expected result:

- Payload relationships refreshed against current catalog state.
- Log written under `~/.logs/hashall/reports/db-refresh/`.

## Next Sequence After Step 4

1. `bin/rehome-89_nohl-basics-qb-automation-audit.sh`
2. `bin/rehome-89_nohl-basics-qb-automation-audit.sh --mode apply` (if risks flagged)
3. `bin/rehome-100_nohl-basics-qb-repair-baseline.sh`
4. `bin/rehome-101_nohl-basics-qb-candidate-mapping.sh`
5. `bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode dryrun --limit 10`
6. `bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 10`
7. Repeat `rehome-102` apply in bounded batches.

## Active Follow-Ups

- qbit repair state-transition edge case:
  - Hash `a047ce7c` reached partial progress in qB while repair monitor kept reporting persistent stoppedDL.
  - Track as code-level TODO for future repair-batch monitor fixes.
- Device identity stability:
  - Avoid using transient numeric `device_id` as durable identity in operator-visible workflows.

