# Hashall Docs Index

Purpose: minimal, canonical documentation set for CLI agents and developers.

## Agent Start Gate

Every agent must read `AGENTS.md` first and emit the required
`HASHALL_CONTEXT_ACK` before analysis, edits, or live operations.

Critical invariants:

- `/data/media` and `/stash/media` are equivalent mount aliases for the same
  `stash/media` filesystem. Do not count them as separate copies.
- Path-sensitive work must use canonical path/device identity, not raw string comparisons.
- `docs/operations/RUN-STATE.md` is the live-state source of truth; archived docs are historical.
- Live qB/RT mutation requires dry-run, tiny pilot, post-check, and human inspection gates.

## Canonical Docs (required read order)

| # | File | Purpose |
|---|---|---|
| 1 | `SESSION.md` | Live session goal + step (chatrap-managed) |
| 2 | `docs/SPRINT.md` | Current sprint focus, active repair queue, done-this-sprint |
| 3 | `docs/operations/RUN-STATE.md` | Live evidence baseline, freshness snapshot |
| 4 | `docs/ARCHITECTURE.md` | Storage model, pathing invariants, data components |
| 5 | `docs/REQUIREMENTS.md` | Product and safety requirements (full) |
| 6 | `docs/BACKLOG.md` | Ranked backlog priorities beyond the sprint |

## Reference Docs (read when relevant)

| File | When to read |
|---|---|
| `docs/RUNBOOK.md` | Before any CLI workflow, rehome, move, cleanup, or deletion |
| `docs/operations/RT-QB-DRIFT-HANDOFF.md` | Before qB/RT drift, cache, or client-sync work |
| `docs/RECOVERY.md` | When recovering from compacted or unclear context |
| `docs/project/KNOWN-TEST-FAILURES.md` | Pre-existing test failures, root causes, fix plans |
| `docs/CROSS-REPO-QB-HELPER-INSTRUCTIONS.md` | Cross-repo instruction set for qB helper/cache tooling |
| `docs/ops-log.md` | Rolling operational log when recent context matters |

## Hygiene

Validate active-doc links with:

```bash
python3 scripts/check_doc_links.py
```

## Archive

Historical and superseded docs live in `docs/archive/`.
Active-tree duplicates should be archived rather than left as stubs.
