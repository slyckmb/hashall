# Remote Codex Adaptation (Preamble)

This prompt was written for a local CLI agent. If you are a remote Codex app agent:
- Read `/Users/michaelbraband/.codex/AGENTS.md` first
- Treat `~` as remote (`/home/michael`)
- Run heavy operations on glider via `ssh glider-tunnel`
- Edit files via the mounted mirror under `/Users/michaelbraband/glider/...`
- Use `mkvenv` for per-repo venvs (see global guide)
- If `mkvenv` is unavailable in a non-interactive shell, source it first:
  - `. /home/michael/dev/work/glider/linux-common/dotfiles/bash/bash_venv`
- Venv check (glider):
  - `if [ -z "$VIRTUAL_ENV" ]; then . /home/michael/dev/work/glider/linux-common/dotfiles/bash/bash_venv && cd /home/michael/dev/work/hashall && mkvenv; fi`

# NEXT AGENT PROMPT — Stage 3 (Diff Engine + Polish)

You are the next CLI coder agent in `~/dev/work/hashall`.
Remote Codex override: adapt paths/commands per the preamble and `/Users/michaelbraband/.codex/AGENTS.md`.

## Context Snapshot (as of Feb 5, 2026)

**Branch:** `main`

**Stage 0 Commit:** `468b593 feat(hashall): add sha256 migration tooling and diff engine`
**Stage 1 Commit:** `8bfe2a6 chore(make): add unified scan-hierarchical target`
**Stage 2 Commit:** `c08fa9a feat(hash): cut over file hashing to sha256`

## What’s Done (Stage 2)

- Full cutover to **SHA256** as primary file hash.
- Payload hash now uses `(path, size, sha256)`.
- Link dedup (analysis/planner/executor) now groups and verifies with SHA256.
- Diff/verify/treehash updated to prefer SHA256 with SHA1 legacy fallback.
- Docs updated to reflect SHA256 as primary (SHA1 legacy only).
- Tests updated and passing.

**Tests run (all passed, no re-run unless requested):**
- `pytest tests/test_payload.py -v`
- `pytest tests/test_link_*.py -v`
- `pytest tests/test_rehome.py tests/test_rehome_promotion.py tests/test_rehome_stage4.py -v`
- `pytest tests/test_treehash.py -v`

## Current Focus (Stage 3)

**Goal:** Implement `src/hashall/diff.py` fully and add robust tests.

Checklist:
1. Implement diff behavior (or confirm it matches requirements).
2. Add unit tests for diff output (added/removed/changed + hardlink/inode handling).
3. Optional polish if time remains.
4. Update docs if behavior changes.

## Key Files

- `src/hashall/diff.py`
- `src/hashall/verify.py`
- `src/hashall/verify_trees.py`
- `tests/` (add new diff tests)
- `docs/REQUIREMENTS.md` (authoritative)
- `docs/architecture/architecture.md`
- `docs/architecture/schema.md`

## Notes / Constraints

- Hardlinks must remain within a single filesystem.
- Rehome promotion is reuse-only (no blind copy).
- SHA1 is legacy only; SHA256 is primary.
- `scan-hierarchical` target has been renamed to `scan-hier-per-device`; a new unified `scan-hierarchical` target exists.

## Handoff + Stage QC (Required)

Before handing off:
- Update **this file** (`out/NEXT-AGENT-PROMPT.md`) with:
  - What you changed (files + brief description)
  - Tests run (commands + pass/fail)
  - Anything left undone or blocked
  - Any new decisions or behavior changes
- Ensure all docs impacted by Stage 3 are updated with accurate status/context.
- Pause for **Stage QC** and explicit approval before proceeding to commit.

## Commit Instructions (Required)

Follow this exact commit workflow:
- `/home/michael/dev/work/glider/global/prompts/SIMPLE-dones-todos-slug-name-plan-commit.md`

## Suggested Next Steps

1. Re-read `docs/REQUIREMENTS.md` and `docs/tooling/cli.md` for diff expectations.
2. Inspect `src/hashall/diff.py` and `tests/` for gaps or missing coverage.
3. Implement tests first if behavior is unclear; then finalize diff logic.
4. Run targeted tests and report failures.

Preferred test command (glider):
- `cd /home/michael/dev/work/hashall && if [ -z "$VIRTUAL_ENV" ]; then . /home/michael/dev/work/glider/linux-common/dotfiles/bash/bash_venv && mkvenv; fi && pytest tests/test_diff*.py -v`

## If You Need DBs or Scan Locations

User reported that `make scan-hierarchical` previously ran:
`/home/michael/.venvs/hashall/bin/python ./hashall-auto-scan "." --per-device`
This created unintended per-device DBs in root. A follow-up plan is desired:
- search default directory/device roots and collect DB locations
- discuss renaming targets and whether to introduce a true hierarchical scan
- possible data migration from root device DBs to master DB

(Do not delete any DBs without explicit approval.)
