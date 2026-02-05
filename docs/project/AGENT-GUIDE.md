# Agent Guide - Hashall (CLI Coders)

**Purpose:** Fast, minimal context to continue implementation safely.

---

## What This Project Is
Hashall is a unified file catalog and payload-identity system that enables safe **rehome** orchestration (stash ↔ pool) and hardlink deduplication.

**Primary objective:** Rehome must be safe, deterministic, and auditable. Hashall provides the catalog, payload identity, and safety checks that rehome depends on.

---

## Current Status (Truth From Code)

**Complete:**
- Link dedup pipeline: `link analyze`, `link plan`, `link list-plans`, `link show-plan`, `link execute`
- Payload identity: `payload sync`, `payload show`, `payload siblings`
- Rehome orchestration: `rehome plan`, `rehome apply` (demote + promote reuse-only)
- Collision detection (fast-hash + auto-upgrade logic)

**Not complete:**
- `src/hashall/diff.py` TODO logic

---

## Where to Look (Canonical Docs)

**Requirements (authoritative):**
- `docs/REQUIREMENTS.md`

**Operator usage:**
- `docs/tooling/cli.md`
- `docs/tooling/link-guide.md`
- `docs/tooling/REHOME.md`

**Architecture / schema:**
- `docs/architecture/architecture.md`
- `docs/architecture/schema.md`
- `docs/architecture/COLLISION-DETECTION-IMPLEMENTATION.md`

**Roadmap (active only):**
- `docs/project/DEVELOPMENT-ROADMAP.md`

---

## Code Entry Points

**Hashall CLI:** `src/hashall/cli.py`
**Payload system:** `src/hashall/payload.py`
**Link dedup:**
- `src/hashall/link_analysis.py`
- `src/hashall/link_planner.py`
- `src/hashall/link_query.py`
- `src/hashall/link_executor.py`

**Rehome:**
- `src/rehome/cli.py`
- `src/rehome/planner.py`
- `src/rehome/executor.py`

---

## Tests to Run (Targeted)

```bash
pytest tests/test_link_*.py -v
pytest tests/test_payload.py -v
pytest tests/test_rehome.py tests/test_rehome_promotion.py tests/test_rehome_stage4.py -v
```

---

## Known Constraints / Design Facts

- File-level hashing uses **SHA256** (SHA1 retained for legacy compatibility).
- Payload hash is **SHA256 of (path, size, sha256)**; payload hash is NULL if any SHA256 missing.
- Hardlinks only within the same filesystem; executor blocks cross-filesystem links.
- Rehome promotion is **reuse-only** (no blind copy).

---

## Next Work (High Priority)

1. Implement `src/hashall/diff.py`
2. Keep docs aligned as code changes

---

## Sprint 2 & 3 Checklist (Agent Execution)

### Sprint 2: SHA256 Migration (Complete)

- Schema now includes `sha256` in per-device tables + indexes
- Scan pipeline writes SHA256 and keeps SHA1 for legacy
- `sha256-backfill` + `sha256-verify` CLI commands implemented
- Payload hash uses `(path, size, sha256)`
- Docs updated for SHA256 as primary hash

### Sprint 3: Diff Engine + Polish (Remaining)

1. Implement `src/hashall/diff.py` TODO logic
2. Add unit tests for diff behavior
3. Optional polish tasks (if time):
   - Performance tuning
   - UX improvements
   - Minor tooling refinements
