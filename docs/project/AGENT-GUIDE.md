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
- SHA256 migration for file hashes (still SHA1 at file level)
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

- File-level hashing uses **SHA1** today. SHA256 migration is pending.
- Payload hash is **SHA256 of (path, size, sha1)**; payload hash is NULL if any SHA1 missing.
- Hardlinks only within the same filesystem; executor blocks cross-filesystem links.
- Rehome promotion is **reuse-only** (no blind copy).

---

## Next Work (High Priority)

1. SHA256 migration (schema + migration command + dual-write/transition plan)
2. Implement `src/hashall/diff.py`
3. Keep docs aligned as code changes

---

## Sprint 2 & 3 Checklist (Agent Execution)

### Sprint 2: SHA256 Migration

1. Schema changes
   - Add `sha256` column to per-device tables
   - Add indexes for sha256 lookups
   - Decide on dual-write period (SHA1 + SHA256)

2. Hashing updates
   - Implement hash function abstraction (SHA1/SHA256)
   - Update scan pipeline to compute SHA256 (and optionally SHA1)
   - Ensure payload hash still uses SHA256 over `(path, size, sha1)` until migration completes

3. Migration command
   - New CLI command to backfill SHA256 for files with only SHA1
   - Must be resumable and safe on interruption
   - Provide progress + dry-run mode if feasible

4. Validation
   - Spot-check or verify subset of SHA256 hashes
   - Report mismatches

5. Docs
   - Update `docs/REQUIREMENTS.md` and `docs/architecture/schema.md`
   - Update `docs/tooling/cli.md` if new commands are added

### Sprint 3: Diff Engine + Polish

1. Implement `src/hashall/diff.py` TODO logic
2. Add unit tests for diff behavior
3. Optional polish tasks (if time):
   - Performance tuning
   - UX improvements
   - Minor tooling refinements
