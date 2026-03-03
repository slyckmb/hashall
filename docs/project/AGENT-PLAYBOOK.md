# Agent Playbook (Canonical)

Last updated: 2026-02-28
Status: canonical

## Purpose

Single entry guide for CLI agents to develop, operate, and maintain this repository.

## Read Order

1. `README.md`
2. `docs/README.md`
3. `docs/REQUIREMENTS.md`
4. `docs/architecture/SYSTEM.md`
5. `docs/tooling/CLI-OPERATIONS.md`
6. `docs/tooling/REHOME-RUNBOOK.md`
7. `docs/operations/RUN-STATE.md`
8. `docs/project/PLAN.md`

## Code Entry Points

- Hashall CLI: `src/hashall/cli.py`
- Payload logic: `src/hashall/payload.py`
- Rehome CLI: `src/rehome/cli.py`

## Test Strategy

Run targeted tests first:

```bash
pytest tests/test_link_*.py -v
pytest tests/test_payload.py -v
pytest tests/test_rehome*.py -v
```

Then run focused tests for touched areas.

## Repo Layout Rules

- Code: `src/`
- Runtime scripts: `bin/`
- Tests: `tests/`
- Manual test helpers: `tests/manual/`
- Benchmarks: `benchmarks/`
- Active docs: `docs/`
- Historical docs: `docs/archive/`

Root compatibility wrappers are allowed for stable operator commands only.

## Documentation Rules

- Update canonical docs, not deprecated duplicates.
- Keep compatibility stubs brief and pointer-only.
- Archive superseded material under `docs/archive/`.
- Run `python3 scripts/check_doc_links.py` after docs edits.

## Safety Rules

- Dry-run before mutating operations.
- Do not run parallel mutating qB workflows.
- Treat stale plans as invalid after state changes.
