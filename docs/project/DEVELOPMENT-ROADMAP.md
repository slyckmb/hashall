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

## Active Work (Short Stages)

### Stage 7 — Operational Readiness (Required)
- Validate preferred mount behavior across remount scenarios (bind mounts + mount path changes)
- Build/run a controlled sandbox validation loop (scan/diff/verify)
- Confirm catalog rebuild procedure after DB cleanup

### Stage 8 — Subtree Treehash Integration
- Integrate `treehash.py` into a subtree comparison workflow
- Add tests for subtree comparisons and regression coverage

### Stage 9 — Torrent View Building (Siblings as Hardlink Views)
- Implement advanced view building for renamed files/complex layouts
- Ensure sibling torrents can be represented as hardlink views

## Nice-to-Haves (Defer Until Core Is Proven)

**hashall:**
- Web UI for browsing catalog
- Automated deduplication schedules
- Advanced filters (size/date/patterns)
- Cloud integration (S3, Backblaze)

**rehome:**
- Parallel batch processing (process multiple payloads concurrently)
- Advanced payload view building (handle renamed files, different layouts)
- Fuzzy payload matching (similar but not identical content)
- Automated rehoming schedules (e.g., demote all `~noHL` tagged torrents weekly)
- Undo/rollback capability

**Integration:**
- Automated rehoming based on qbit_manage tags
- \*arr webhook integration (auto-promote on import)
- Notifiarr notifications

---

## Non-Goals (For Now)

- Web UI
- Automation/scheduler
- Fuzzy payload matching
- Advanced view building
