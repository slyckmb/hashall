# Hashall Development Log

This log tracks significant architectural changes, refactorings, and design decisions in the hashall project.

---

## 2026-01-31: Stage 1 - Rename "conductor" to "link"

### Summary

Renamed the deduplication subsystem from "conductor" to "link" across all documentation and scripts. This is a CLI/UX rename with no behavior changes.

### Rationale

The term "link" better describes the core functionality: creating **hardlinks** on the same device to deduplicate files. "Conductor" was too abstract and didn't clearly communicate what the subsystem does.

### Changes Made

#### Documentation
- Renamed `docs/conductor-guide.md` → `docs/link-guide.md`
- Updated all command references: `hashall conductor` → `hashall link`
- Updated table names in schema docs: `conductor_plans` → `link_plans`, `conductor_actions` → `link_actions`
- Updated all conceptual references to the subsystem from "conductor" to "link"

#### Scripts
- Renamed `scripts/conductor_plan.py` → `scripts/link_plan.py`
- Updated internal comments and output filenames
- Updated `scripts/analyze_export.py` docstring

#### Files Modified
- README.md
- docs/architecture.md
- docs/cli.md
- docs/quick-reference.md
- docs/schema.md
- docs/unified-catalog-architecture.md
- docs/link-guide.md (renamed from conductor-guide.md)
- scripts/link_plan.py (renamed from conductor_plan.py)
- scripts/analyze_export.py

### Command Mapping

| Old Command | New Command |
|------------|-------------|
| `hashall conductor analyze` | `hashall link analyze` |
| `hashall conductor plan` | `hashall link plan` |
| `hashall conductor show-plan` | `hashall link show-plan` |
| `hashall conductor execute` | `hashall link execute` |
| `hashall conductor status` | `hashall link status` |

### Database Schema

Planned table renames (not yet implemented in code):
- `conductor_plans` → `link_plans`
- `conductor_actions` → `link_actions`

### What's Next

**Stage 2+** (not part of this change):
- Implement CLI commands `hashall link ...` in `src/hashall/cli.py`
- Implement link module `src/hashall/link.py`
- Create database migration for table renames
- Add integration tests for link commands

### Compatibility Notes

- The actual CLI commands (`hashall link ...`) are not yet implemented - they exist only in documentation
- Standalone scripts `scripts/link_plan.py` and `scripts/analyze_export.py` continue to work as before
- No database changes were made in this stage
- No code in `src/hashall/` was modified (only docs and scripts)

### Key Insight

"Link" terminology:
- **Clear**: Describes what it does (creates hardlinks)
- **Accurate**: Only works on same-device files (hardlink constraint)
- **Distinct**: Differentiates from future orchestration/stash systems that may move files across devices

---

## Future Entries

Additional entries will be added here as the project evolves.
