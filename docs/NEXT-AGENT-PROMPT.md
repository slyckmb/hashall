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

# NEXT AGENT PROMPT — Stage 6 (Preferred Mount Override + Validation)

You are the next CLI coder agent in `~/dev/work/hashall`.
Remote Codex override: adapt paths/commands per the preamble and `/Users/michaelbraband/.codex/AGENTS.md`.

## Context Snapshot (as of Feb 5, 2026)

**Branch:** `main`

**Stage 0 Commit:** `468b593 feat(hashall): add sha256 migration tooling and diff engine`
**Stage 1 Commit:** `8bfe2a6 chore(make): add unified scan-hierarchical target`
**Stage 2 Commit:** `c08fa9a feat(hash): cut over file hashing to sha256`
**Stage 3:** Diff engine considered complete; tests added for `diff_scan_sessions` (see `tests/test_diff_scan_sessions.py`).
**Stage 4:** Scan UX cleanup applied in `src/hashall/scan.py`; DB cleanup deleted local `.hashall` DBs; read-only backups under `/pool/backup/home/michael/.hashall` remain by design.
**Stage 5:** Sandbox diff test added (`tests/test_sandbox_diff_flow.py`) and requirements audit noted mount point drift limitations.
**Stage 6 (in progress):** Preferred mount point support added (migration + scan/diff updates + tests). Needs override mechanism and validation.

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

## Current Focus (Stage 6)

**Goal:** Add a safe CLI override mechanism for `preferred_mount_point` (query + update) and validate mount-point drift fixes end-to-end.

Checklist:
1. Implement CLI override to query/update `devices.preferred_mount_point` (read + set).
2. Add tests for override behavior and mount-point drift scenarios.
3. Validate scan/diff behavior after override.
4. Update docs if behavior changes (only with approval).

## Key Files

- `docs/REQUIREMENTS.md` (authoritative)
- `src/hashall/scan.py`
- `src/hashall/verify.py`
- `src/hashall/diff.py`
- `src/hashall/cli.py` (add query + update commands)
- `tests/` (add override + drift tests)
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
- Do NOT edit handoff prompts.
- Write a Stage 6 completion report to `out/STAGE6-REPORT.md` using the template in `docs/STAGE-REPORT-TEMPLATE.md`.
- Always update all affected documents for this stage with accurate status/context (only with approval).
- Pause for **Stage QC** and explicit approval before proceeding to commit.

## Commit Instructions (Required)

Follow this exact commit workflow:
- `/home/michael/dev/work/glider/global/prompts/SIMPLE-dones-todos-slug-name-plan-commit.md`

## Suggested Next Steps

1. Implement CLI surface for querying and setting preferred mount point.
2. Implement override and add tests.
3. Validate mount-point drift resolution end-to-end.
4. Document gaps and remediation plan if any remain.

Preferred test command (glider):
- `cd /home/michael/dev/work/hashall && if [ -z "$VIRTUAL_ENV" ]; then . /home/michael/dev/work/glider/linux-common/dotfiles/bash/bash_venv && mkvenv; fi && pytest tests/test_scan*.py -v`

## If You Need DBs or Scan Locations

User reported that `make scan-hierarchical` previously ran:
`/home/michael/.venvs/hashall/bin/python ./hashall-auto-scan "." --per-device`
This created unintended per-device DBs in root. A follow-up plan is desired:
- search default directory/device roots and collect DB locations
- discuss renaming targets and whether to introduce a true hierarchical scan
- possible data migration from root device DBs to master DB

(Do not delete any DBs without explicit approval.)
