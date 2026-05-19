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
2. `docs/SPRINT.md` for the current sprint goal and active repair queue.
3. `docs/operations/RUN-STATE.md` for live evidence baseline and stop/freeze notes.
4. `docs/ARCHITECTURE.md` for storage, identity, and pathing invariants.
5. `docs/REQUIREMENTS.md` for product and safety requirements.
6. `docs/BACKLOG.md` for ranked backlog priorities beyond the current sprint.

Conditional required docs:

- Read `docs/RUNBOOK.md` before running CLI workflows, rehome, move, cleanup, or deletion work.
- Read `docs/operations/RT-QB-DRIFT-HANDOFF.md` before qB/RT drift, cache, or client-sync work.
- Read `docs/RECOVERY.md` when recovering from compacted or unclear context.

After reading the required context, explicitly acknowledge compliance to the user
before proceeding:

```text
HASHALL_CONTEXT_ACK docs=SESSION,SPRINT,RUN-STATE,ARCHITECTURE,REQUIREMENTS status=OK
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
- **RT is the active seeder and path authority. qB is the passive backup mirror (paused/stopped).**
  When qB and RT paths differ for the same hash and both are on the correct placement tier,
  RT's path is canonical — repoint qB to match RT. See §4.4 and §8.4 of REQUIREMENTS.md.
  Exception: if RT's path is provably non-canonical (wrong category, missing, or structurally wrong),
  escalate for human review rather than auto-repointing.
- **Canonical path formula:** `<seeding-root>/<category>/<item-payload-name>`
  Category is determined by item origin (see §4.4.3 of REQUIREMENTS.md):
  - ARR-managed post-import: `<media-type>/` (tv/, movies/, books/, music/)
  - cross-seed: `cross-seed/<prowlarr-tracker-name>/`
  - qbit_manage tracker assignment: `<tracker-name>/`
- Always confirm actual filesystem/catalog state before destructive decisions.
- One mutating qB/RT workflow at a time. Dry-run, tiny pilot, post-check, and
  human inspection gates are required before widening.
- Current live qB and RT caches are silo-owned unless `RUN-STATE.md` says
  otherwise.

If live observations conflict with these invariants, freeze mutation, record the
conflict in `SESSION.md`, and ask for human review.
