# Development Roadmap (Active)

**Goal:** Provide the minimal next steps for CLI coders to finish the project.

---

## Completed (Code Verified)

- Link dedup pipeline: analyze → plan → show/list → execute
- Payload identity: sync/show/siblings
- Rehome: plan/apply (demote + promote reuse-only)
- Collision detection (fast-hash + auto-upgrade)

---

## Active Work

### 1. SHA256 Migration (Highest Priority)

**Why:** File-level hashing is still SHA1. Migration is required to standardize on SHA256.

**Required deliverables:**
- Schema update (sha256 column + indexes)
- Migration command (incremental, resumable)
- Dual-write period (compute SHA1 + SHA256)
- Validation tool (spot-checks)
- Docs update

### 2. Diff Engine (Medium Priority)

- Implement missing logic in `src/hashall/diff.py`
- Add tests for diff output

---

## Non-Goals (For Now)

- Web UI
- Automation/scheduler
- Fuzzy payload matching
- Advanced view building

