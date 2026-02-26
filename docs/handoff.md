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
- Repair pipeline upgrades implemented:
  - Phase 100 now records tracker/category hints and current payload root.
  - Phase 101 supports tracker-aware ranking and top-N candidate persistence.
  - Phase 102 supports ranked candidate attempts with fallback + fail-fast mismatch handling.
  - Phase 103 ownership audit added and wired as an apply preflight gate.

## Immediate Next Step

Run:

```bash
bin/rehome-101_nohl-basics-qb-candidate-mapping.sh --tracker-aware --candidate-top-n 10
```

Expected result:

- Candidate mapping JSON includes ranked candidates and payload-root ownership fields.
- Tracker/category-aware ranking should reduce wrong tracker-folder picks.

## Next Sequence After Step 4

1. `bin/rehome-89_nohl-basics-qb-automation-audit.sh`
2. `bin/rehome-89_nohl-basics-qb-automation-audit.sh --mode apply` (if risks flagged)
3. `bin/rehome-100_nohl-basics-qb-repair-baseline.sh`
4. `bin/rehome-101_nohl-basics-qb-candidate-mapping.sh --tracker-aware --candidate-top-n 10`
5. `bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh`
6. `bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode dryrun --limit 10 --candidate-top-n 3 --candidate-fallback`
7. `bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 10 --candidate-top-n 3 --candidate-fallback`
8. Re-run `bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh` after each apply batch.
9. Repeat `rehome-102` apply in bounded batches.

## Active Follow-Ups

- qbit repair state-transition edge case:
  - Hash `a047ce7c` reached partial progress in qB while repair monitor kept reporting persistent stoppedDL.
  - Track as code-level TODO for future repair-batch monitor fixes.
- Device identity stability:
  - Avoid using transient numeric `device_id` as durable identity in operator-visible workflows.
