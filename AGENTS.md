# AGENTS — Repo Entry Point

**Global defaults**: `~/.agent/AGENTS_GLOBAL.md`

This repo doc is intentionally thin and points to the global guide, which defines:
- Environment detection (glider vs surfer)
- Path conventions
- Command routing (heavy ops on glider)
- `mkvenv` usage
- Safety rules and baseline protocol

## Baseline Protocol

- If `.agent/baseline.md` exists, read it first — objective facts about repo state.
- Do not ask the user whether things were dirty before; use the baseline.
- Do not commit, delete files, or modify `.gitignore` without explicit approval.

## Mandatory Hashall Context Gate

Before analysis, planning, or edits, every agent must read and follow the active
repo context. Do not rely on memory, branch names, or raw path strings.

Required read order:

1. `SESSION.md` when present.
2. `docs/operations/RUN-STATE.md` for current live state, stop/freeze notes, and
   superseded evidence.
3. `docs/README.md` for the canonical active-doc set.
4. `docs/architecture/SYSTEM.md` for storage, identity, and pathing invariants.
5. `docs/project/PLAN.md` for current goals and backlog priorities.
6. `docs/project/AGENT-PLAYBOOK.md` for agent workflow and verification rules.

Conditional required docs:

- Read `docs/tooling/CLI-OPERATIONS.md` before running or changing CLI workflows.
- Read `docs/tooling/REHOME-RUNBOOK.md` before rehome, move, cleanup, or deletion work.
- Read `docs/operations/RT-QB-DRIFT-HANDOFF.md` before qB/RT drift, cache, or client-sync work.
- Read `docs/NEXT-AGENT-PROMPT.md` when recovering from compacted or unclear context.

After reading the required context, explicitly acknowledge compliance to the user
before proceeding:

```text
HASHALL_CONTEXT_ACK docs=SESSION,RUN-STATE,README,SYSTEM,PLAN,AGENT-PLAYBOOK status=OK
```

If any required file is missing, stale, contradictory, or too large to inspect
safely, stop and report the gap instead of proceeding.

## Critical Invariants

- `/data/media` and `/stash/media` are equivalent mount aliases for the same
  `stash/media` filesystem. Never treat them as independent copies, owners, or
  evidence streams.
- Any path-sensitive audit must canonicalize aliases and/or verify filesystem
  identity with mount source, `st_dev`, inode, `fs_uuid`, or the repo's pathing
  helpers before drawing conclusions.
- Use existing alias-aware helpers such as `hashall.pathing.canonicalize_path`
  and `hashall.pathing.remap_to_mount_alias`; do not add new raw string-prefix
  logic for ownership or cleanup decisions.
- qB/RT placement policy is evidence-based:
  ARR-library hardlink anchor present means stash placement; no verified ARR
  hardlink anchor means pool placement; qB `~noHL` is advisory only.
- Always confirm actual filesystem/catalog state before destructive decisions.
- One mutating qB/RT workflow at a time. Dry-run, tiny pilot, post-check, and
  human inspection gates are required before widening.
- Current live qB and RT caches are silo-owned unless `RUN-STATE.md` says
  otherwise.

If live observations conflict with these invariants, freeze mutation, record the
conflict in `SESSION.md`, and ask for human review.
