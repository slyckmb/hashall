# Hashall Docs Index

Purpose: minimal, canonical documentation set for CLI agents.

## Agent Start Gate

Every agent must read `AGENTS.md` first and emit the required
`HASHALL_CONTEXT_ACK` before analysis, edits, or live operations.

Critical setup facts:

- `/data/media` and `/stash/media` are equivalent mount aliases for the same
  `stash/media` filesystem. Do not count them as separate copies.
- Path-sensitive work must use canonical path/device identity, not raw string
  path comparisons.
- `docs/operations/RUN-STATE.md` is the current live-state source of truth; old
  sections and archived docs are historical unless the current run state says
  otherwise.
- Live qB/RT mutation requires dry-run, tiny pilot, post-check, and human
  inspection gates.

## Canonical (required)

1. `docs/REQUIREMENTS.md` - Product and safety requirements.
2. `docs/architecture/SYSTEM.md` - Architecture and data model.
3. `docs/tooling/CLI-OPERATIONS.md` - Core CLI usage and command workflows.
4. `docs/tooling/REHOME-RUNBOOK.md` - Rehome safety and operational runbook.
5. `docs/operations/RUN-STATE.md` - Current living operational state and next actions.
6. `docs/project/AGENT-PLAYBOOK.md` - Agent read order, rules, test strategy.
7. `docs/project/PLAN.md` - Active roadmap and backlog.
8. `docs/project/KNOWN-TEST-FAILURES.md` - Pre-existing test failures: root causes and fix plans.
9. `README.md` - Project overview and onboarding.

## Active Continuity Docs

- `docs/handoff.md` - Compact-safe current handoff summary.
- `docs/next-agent.md` - Compact-safe recovery checklist.
- `docs/NEXT-AGENT-PROMPT.md` - Prompt-safe compact recovery summary.
- `docs/CROSS-REPO-QB-HELPER-INSTRUCTIONS.md` - Cross-repo instruction set for agents that should consume hashall qB helper/cache tooling.
- `docs/ops-log.md` - Rolling operational log when recent context matters.

## Hygiene

Validate active-doc links with:

`python3 scripts/check_doc_links.py`

## Archive

Historical and superseded docs live in `docs/archive/`.
Active-tree duplicates should be archived rather than left behind as compatibility stubs.
