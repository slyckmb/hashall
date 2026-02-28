# Project Plan (Canonical)

Last updated: 2026-02-28
Status: active

## Purpose

Unified roadmap + active backlog for development and operations.

## Near-Term Priorities

1. Stabilize qB stoppedDL recovery loop.
2. Reduce repeated verification cost while increasing first-pass precision.
3. Keep documentation canonical and low-friction for agent handoffs.

## Active Engineering Backlog

### Diff Engine and Core Completeness

- Implement remaining `src/hashall/diff.py` TODO logic.
- Add targeted tests for diff behavior and regression protection.

### Operational Hardening

- Improve long-running command progress visibility.
- Harden idempotent restart behavior in automation loops.
- Continue reducing stale-plan and stale-state failure modes.

### Data Integrity

- Maintain SHA256 backfill and verification coverage.
- Continue payload uniqueness and ownership audit workflows.

## Deferred / Nice-to-Have

- Additional UI/reporting polish.
- Extended automation around periodic audits.
- Lower-priority tooling cleanup beyond canonical workflows.

## Source Backlog

Legacy TODO content moved from root `TODO.md`:
- See `docs/archive/2026-doc-reduction/snapshot/docs/project/TODO.md` for preserved pre-consolidation details.
