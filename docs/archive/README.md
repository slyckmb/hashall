# Hashall Documentation Archive

This directory contains historical documentation that has been superseded or completed.

---

## Directory Structure

### `sessions/`
Coding session summaries - detailed records of specific development sessions.

- **2026-01-30_bug-fixes-and-hardlinks.md** - Session that fixed critical bugs (#1-#3) and added hardlink support

### `assessments/`
Pre-fix assessments and analysis documents.

- **2026-01-30_readiness-assessment-pre-fixes.md** - Assessment that identified critical bugs (now fixed)
- **2026-01-30_issues-ranked-resolved.md** - Prioritized issue list (all critical issues now resolved)
- **2026-01-30_todo-and-polish-notes.md** - Working TODO list from early development

### `validation/`
Validation and testing reports that proved correctness.

- **conductor_validation.md** - Proof-of-concept validation for conductor integration (JSON export completeness)
- **real_world_conductor_validation.md** - Large-scale validation on real ZFS datasets (3.8k-57k files)

### `design/`
Design documents for features (may be partially obsolete due to architecture changes).

- **2026-06-25_smart-verify-design-v1.md** - Original smart-verify/treehash design (session-based architecture)

### `legacy/`
GPT session artifacts and historical snapshots.

- Various `*-summary.md` and `*-rehydration.md` files from GPT-assisted development sessions
- `dev_guardrails.md` - Development guidelines
- `gpt-*.md` - Simulation testing notes
- `reports/hashall_REPO_BRIEFING.md` - Historical repo snapshot

---

## Why Documents Were Archived

### Obsolete Due to Bug Fixes
Documents describing bugs that have since been fixed:
- Readiness assessment (issues #1-#3 resolved)
- Issues ranked (critical issues resolved)

### Obsolete Due to Architecture Change
Documents describing session-based model, now replaced by unified catalog:
- Smart-verify design v1 (sessions → unified catalog with device tables)
- TODO/polish notes (feature requests superseded)

### Completed Work
Documents describing work that has been completed:
- Session summaries (work is done, captured in git history)
- Validation reports (testing completed, results proven)

---

## Which Docs Are Current?

See the main `docs/` directory for current documentation:
- `architecture.md` - Current unified catalog design
- `docs/architecture/schema.md` - Concise schema summary (active)
- `cli.md` - Current CLI reference
- `docs/architecture/architecture.md` - Canonical unified catalog architecture (active)
- `symlinks-and-bind-mounts.md` - Canonical path handling
- `conductor-guide.md` - Deduplication workflow

---

## Accessing Archived Information

All archived documents are still readable and contain valuable historical context:
- **Session summaries** show the development process and decision-making
- **Assessments** document the bug discovery process
- **Validation reports** prove correctness at scale
- **Design docs** capture original thinking (some concepts still relevant)

If you need information from archived docs:
1. Check the deprecation header for context about why it was archived
2. See if current docs cover the same topic
3. Use archived docs for historical reference only

---

**Note:** All file moves preserve git history. Use `git log --follow <filename>` to see full history of moved files.
