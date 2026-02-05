# Development Roadmap (Active)

**Goal:** Provide the minimal next steps for CLI coders to finish the project.

---

## Completed (Code Verified)

- Link dedup pipeline: analyze → plan → show/list → execute
- Payload identity: sync/show/siblings
- Rehome: plan/apply (demote + promote reuse-only)
- Collision detection (fast-hash + auto-upgrade)
- SHA256 migration (schema, backfill, validation, docs)

---

## Active Work

### 1. Diff Engine (Medium Priority)

- Implement missing logic in `src/hashall/diff.py`
- Add tests for diff output

---

## Non-Goals (For Now)

- Web UI
- Automation/scheduler
- Fuzzy payload matching
- Advanced view building
