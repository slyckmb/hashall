# Hashall Docs Index

Purpose: minimal, canonical documentation set for CLI agents.

## Canonical (required)

1. `docs/REQUIREMENTS.md` - Product and safety requirements.
2. `docs/architecture/SYSTEM.md` - Architecture and data model.
3. `docs/tooling/CLI-OPERATIONS.md` - Core CLI usage and command workflows.
4. `docs/tooling/REHOME-RUNBOOK.md` - Rehome safety and operational runbook.
5. `docs/operations/RUN-STATE.md` - Current living operational state and next actions.
6. `docs/project/AGENT-PLAYBOOK.md` - Agent read order, rules, test strategy.
7. `docs/project/PLAN.md` - Active roadmap and backlog.
8. `README.md` - Project overview and onboarding.

## Compatibility Stubs

Legacy names are retained as pointer stubs to avoid breaking workflows.
Historical content snapshots are preserved under:

- `docs/archive/2026-doc-reduction/snapshot/`

## Hygiene

Validate active-doc links with:

`python3 scripts/check_doc_links.py`

## Archive

Historical and superseded docs live in `docs/archive/`.
