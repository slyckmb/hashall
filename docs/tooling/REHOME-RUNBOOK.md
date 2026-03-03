# Rehome Runbook (Canonical)

Last updated: 2026-02-28
Status: canonical

## Purpose

Single operational runbook for rehome planning, apply flow, and safety gates.

## Rehome Principles

- Preserve hardlink safety.
- Prefer reuse over risky movement.
- Apply only from fresh scan + payload sync state.
- Treat `/data/media` and `/stash/media` as equivalent aliases.

## Baseline Workflow

1. Refresh catalog state with scans.
2. Sync payloads from qB.
3. Build rehome plan.
4. Review plan outputs and blockers.
5. Dry-run apply.
6. Apply if safe.
7. Verify qB + filesystem state.
8. Cleanup only after verification gates pass.

## Required Safety Gates

- No active-download regressions on repaired/rehomed hashes.
- Source cleanup only when relocated content is validated.
- Manual-action tags remain until follow-up completes.

## qB Integration Defaults

- Preferred mutation order: `setLocation -> recheck -> verify seeding-safe state`.
- Batch fastresume patching when required by selected hashes.
- Avoid concurrent mutating workflows.

## Operational Artifacts

- Plans: generated JSON plan files.
- Apply reports: execution result logs/reports.
- Follow-up tags: verification/cleanup backlog tracking.

## Related Canonical Docs

- `docs/tooling/CLI-OPERATIONS.md`
- `docs/operations/RUN-STATE.md`
- `docs/REQUIREMENTS.md`
