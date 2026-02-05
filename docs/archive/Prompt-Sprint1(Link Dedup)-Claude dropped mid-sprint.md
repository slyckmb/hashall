# PROMPT — CLI Agent Handoff (pick up where prior agent stopped)

You are a CLI coding agent working in: ~/dev/work/hashall

Goal: Resume Sprint 1 “Link Deduplication” where the prior agent left off. Tasks 1.2 (analyze) and 1.3 (plan) are already implemented and tested. Your job is to finish Sprint 1 by implementing Task 1.4 (show-plan) and Task 1.5 (execute), then finalize progress docs.

Context you can rely on (from transcript):

- Unified catalog is now ~/.hashall/catalog.db; per-device DBs were merged and deleted. quick_hash exists; sha1 nullable; WAL enabled. :contentReference[oaicite:12]{index=12}
- `hashall link analyze` exists and works; implementation lives in src/hashall/link_analysis.py; CLI wired in src/hashall/cli.py. :contentReference[oaicite:13]{index=13} :contentReference[oaicite:14]{index=14}
- `hashall link plan` exists and works; implementation lives in src/hashall/link_planner.py; it writes to link_plans and link_actions. :contentReference[oaicite:15]{index=15} :contentReference[oaicite:16]{index=16}
- There are unit tests for analysis and planning; run and keep them passing. :contentReference[oaicite:17]{index=17} :contentReference[oaicite:18]{index=18}

Operating instructions:

1. Start by reading these files in-repo:
   - docs/gap-analysis/SPRINT-1-TASK-BREAKDOWN.md (authoritative requirements for Tasks 1.4 / 1.5)
   - docs/gap-analysis/IMPLEMENTATION-GUIDE.md (implementation patterns)
   - src/hashall/migrations/0008_add_link_tables.sql (schema expectations)
   - src/hashall/cli.py, src/hashall/link_planner.py (style + DB access patterns already used)
     (These were referenced/read previously; confirm details before implementing.) :contentReference[oaicite:19]{index=19}

2. Implement Task 1.4 — CLI: `hashall link show-plan`
   Requirements (derive exact shape from task breakdown doc; do not invent fields that don’t exist):
   - Must load an existing plan from DB.
   - Should support selecting a plan by id and/or name (match task spec).
   - Output should include:
     - plan header (id, name, device_id, status)
     - totals (opportunities, actions_total, total_bytes_saveable)
     - actions list grouped or sorted sensibly (e.g., largest savings first)
     - each action should show canonical_path, duplicate_path, file_size, bytes_to_save, status
   - Consider `--format text|json` if the spec wants it; otherwise keep text-only but structure output cleanly.
   - Add tests: new tests/test_link_show_plan.py (or fold into planner tests) using a temp sqlite DB with minimal schema + rows.

3. Implement Task 1.5 — CLI: `hashall link execute`
   Hard requirement: safe-by-default.
   - Add `--dry-run` (or whatever the task spec says) that performs all validation and prints what WOULD happen, but does not modify the filesystem or DB statuses.
   - Execution mode should:
     - iterate pending link_actions for a given plan
     - for each action:
       - validate canonical exists, duplicate exists
       - validate same filesystem (hardlink constraint) — if not, mark failed with a clear message
       - perform hardlink: replace duplicate with hardlink to canonical (ensure you do not clobber canonical)
       - update link_actions row: status=completed/failed and store any error text
     - update link_plans status and rollups after execution (completed/partial/failed per spec)
   - Make it idempotent:
     - if an action is already completed, skip cleanly
     - if duplicate is already hardlinked to canonical, treat as completed (or per spec)
   - Add tests:
     - Use tempfile dirs and create small files to simulate canonical/duplicate.
     - Validate both dry-run and real execution pathways.
     - Include failure tests: missing files, cross-device (simulate if possible), permission failure (optional).

4. Finish documentation:
   - Update docs/gap-analysis/SPRINT-1-PROGRESS.md to reflect completion of Tasks 1.3–1.5.
   - The prior update attempt was truncated; rewrite the relevant section cleanly.

5. Verification checklist before you stop:
   - `python3 -m pytest tests/test_link_*.py -v` passes.
   - `python3 -m hashall link --help` shows analyze/plan/show-plan/execute.
   - Run a smoke flow (use stash as in transcript):
     - `python3 -m hashall link plan "Agent smoke" --device stash --dry-run`
     - create a real plan (no dry-run), then:
     - `python3 -m hashall link show-plan <id>`
     - `python3 -m hashall link execute <id> --dry-run`
   - Do NOT run real execute against Michael’s real stash data unless explicitly instructed. Prefer a temp sandbox for real execution tests.

Deliverable expectations:

- Small, reviewable commits.
- Keep CLI behavior consistent with existing style in src/hashall/cli.py.
- Don’t change existing flags/behavior for analyze/plan unless required by task spec.
- If you discover schema mismatches between migration and code assumptions, fix them explicitly (migration or code), and add a test covering it.

Now proceed.

/////////////

# PROMPT — CLI Agent Handoff (Corrected, Sprint 1 Complete)

You are a CLI coding agent working in: `~/dev/work/hashall`

This handoff corrects an earlier prompt that incorrectly assumed Sprint 1 was incomplete.
After rescanning the transcript, **Sprint 1 is functionally complete**.

Your role is **NOT** to implement missing Sprint 1 features.
Your role is to:

- Verify correctness
- Finish documentation
- Prepare for the next sprint(s) without altering completed behavior

---

## ✅ CONFIRMED COMPLETED (DO NOT RE-IMPLEMENT)

The following work was completed in this chat and is verified by tests:

### Sprint 1 — Link Deduplication (Complete)

1. **Unified catalog database**
   - `catalog-pool.db` + `catalog-stash.db` → `~/.hashall/catalog.db`
   - WAL enabled
   - `quick_hash` added
   - `sha1` nullable
   - Per-device DBs removed after migration

2. **Task 1.2 — Analyze**
   - `hashall link analyze`
   - Implemented in `src/hashall/link_analysis.py`
   - Tested and stable

3. **Task 1.3 — Plan**
   - `hashall link plan`
   - Writes `link_plans` + `link_actions`
   - Dry-run supported
   - Tested and stable

4. **Task 1.4 — Show / List Plans**
   - `hashall link show-plan`
   - `hashall link list-plans`
   - Read-only inspection of plans and actions
   - Tested and stable

5. **Task 1.5 — Execute**
   - `hashall link execute`
   - Safe-by-default, explicit execution required
   - Dry-run supported
   - Idempotent
   - Cross-filesystem hardlink protection
   - Robust per-action status tracking
   - Tested with temp filesystem fixtures

6. **Verification improvements**
   - Fast-hash sampling (first/middle/last 1 MB)
   - Integrated into analysis and planning

7. **Tests**
   - All tests passing
   - Total: 52 tests

⚠️ **Do not refactor, rename, or rework any of the above unless a failing test or documented bug is discovered.**

---

## 🎯 YOUR CURRENT MISSION

### Task 1.6 — Documentation (Primary)

Focus exclusively on documentation correctness and clarity.

1. Update or finalize:
   - `docs/gap-analysis/SPRINT-1-PROGRESS.md`
   - Any Sprint 1 references that still imply incomplete work

2. Ensure docs clearly state:
   - Sprint 1 is complete
   - Link deduplication is production-ready
   - Safety guarantees and execution model

3. Do **not** invent new features or CLI flags.

---

## 🔜 UPCOMING (DO NOT START UNLESS INSTRUCTED)

These are **future sprints**, not part of your active task:

- **Sprint 2** — SHA256 migration
- **Sprint 3** — Polish & refinements

You may:

- Leave TODO notes
- Draft planning notes in docs

You may NOT:

- Modify code paths
- Add migrations
- Change hashing behavior

---

## 🔍 VERIFICATION CHECKLIST

Before stopping:

- `python3 -m pytest` → all tests pass
- `hashall link --help` lists:
  - analyze
  - plan
  - show-plan
  - list-plans
  - execute
- Documentation accurately reflects completed state

---

## 🚫 HARD GUARDRAILS

- No filesystem mutations unless explicitly instructed.
- No behavior changes to Sprint 1 commands.
- No schema changes.
- No CLI redesign.
- If ambiguity exists, **stop and ask**.

Proceed carefully and conservatively.
