# Run State (Canonical)

Last updated: 2026-02-28
Status: canonical living state

## Purpose

Single living document for current operational status, handoff context, and next-agent execution guidance.

## Current Mission

Drive qB stoppedDL/stability work to completion while preserving no-download safety and payload uniqueness.

## Non-Negotiables

- One mutating qB workflow at a time.
- No unintended sustained downloading state flips.
- Prefer deterministic, idempotent loops.

## Active Toolchain

- `bin/qb-stoppeddl-bucket.py`
- `bin/qb-stoppeddl-drain.py`
- `bin/qb-stoppeddl-apply.py`
- `bin/qb-stoppeddl-apply-watch.sh`
- `bin/qb-stoppeddl-roundloop.sh`
- `bin/qbit-start-seeding-gradual.sh`

## Current Operating Pattern

1. Refresh stoppedDL bucket.
2. Drain/grade candidates.
3. Apply eligible hashes (`a/b/c`) with live-state safeguards.
4. Wait for checking queue to settle.
5. Repeat until convergence.

## Primary Logs and Reports

- qB triage logs: `~/.logs/hashall/reports/qbit-triage/`
- stoppedDL reports: `/tmp/qb-stoppeddl-bucket-live/reports/`

## Next Actions

- Continue loop until stoppedDL converges.
- Maintain ignore whitelist for intentional long-tail downloaders.
- Escalate unresolved `d/e` classes to reconstruction workflow.

## Compatibility Notes

Legacy docs now stubs:

- `docs/ops-log.md`
- `docs/handoff.md`
- `docs/next-agent.md`
- `docs/NEXT-AGENT-PROMPT.md`
- `docs/qbit-repair-handoff.md`
- `docs/qbit-repair-ops-log.md`
