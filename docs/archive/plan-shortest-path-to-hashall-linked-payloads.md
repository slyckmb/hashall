# Plan: From Current `hashall` (Unified Catalog + “Conductor”) to Seed Data Management (stash↔pool)

**Goal:** Implement Michael’s seeding data management vision with the **shortest, simplest path**:

- Treat **payload** (torrent content tree) as the unit of movement and identity.
- Support **many torrents (different infohashes) → one payload** (intentional multi-variant seeding).
- Enforce stash/pool rules:
  - Stay on `/stash` if any **external consumers** (hardlink children outside seeding domain).
  - Eligible to move to `/pool` if **sibling-only** hardlinks (or none) and policy says so.
  - Prefer **reuse existing payload on destination** over copying.
  - Promotion (`/pool`→`/stash`) is allowed **only if payload already exists on stash** (no blind copying).

**Constraints / Principles:**

- One DB: `~/.hashall/catalog.db` (no separate payload DB).
- `hashall` stays the **truth + safe execution** layer.
- A small external CLI handles **qBittorrent policy + orchestration**.
- Every stage ends with:
  - updated docs
  - tests (where applicable)
  - a commit with detailed Conventional Commit message(s)

---

## Current State (Baseline)

- `hashall` unified catalog (device-scoped tables, incremental scans, hardlink/duplicate aggregates)
- “Conductor” plans and executes safe same-device hardlink operations (plan→review→execute)

---

# Stage 1 — Rename and Clarify the Execution Engine (No Behavior Change)

### Objective

Stop calling it “Conductor”. Make the CLI reflect reality: it’s a **hardlink planning/execution engine**.

### Work

1. Rename CLI surface:
   - `hashall conductor` → `hashall link`
   - Keep legacy alias for one release (optional) but make docs canonical on `link`.
2. Update help text and docs to describe:
   - `hashall scan` = truth gathering
   - `hashall link` = safe same-device hardlink plan/apply
   - explicitly NOT the stash/pool orchestrator

### Deliverables

- Updated CLI entrypoints + docs
- Changelog entry

### Docs to Update

- `docs/tooling/cli.md` (command rename + examples)
- `docs/conductor-guide.md` → rename to `docs/tooling/link-guide.md` (or keep filename but content updated)
- `docs/architecture/architecture.md` (component naming + roles)

### Tests

- CLI help/dispatch smoke tests
- Backward compatibility tests if alias retained

### Commit Message(s)

- `refactor(cli): rename conductor to link; keep behavior unchanged`
- `docs: update command references from conductor to link`
- `test(cli): add coverage for link subcommand routing`

---

# Stage 2 — Add Payload Identity as a First-Class Primitive (Inside hashall)

### Objective

Introduce **payload groups** and a **payload_hash** (tree signature) so the system can detect:

- “same payload already exists on /pool”
- “these torrents are siblings (different infohashes, same bytes)”
- “payload duplicates on same device” (future optimization)

### Definition

- **payload_hash** = hash over canonical manifest:
  - list of `(relpath_within_payload_root, size, sha1)` sorted by relpath
  - hash algo can be SHA256 over a tab-delimited manifest string
- **torrent_hash (infohash)** is not identity of bytes; it maps to a payload.

### Minimum Schema Additions (in catalog.db)

Add tables (names can vary, but keep semantics):

- `payloads`:
  - `payload_id` (pk)
  - `payload_hash` (unique or indexed)
  - `device_id`
  - `root_path` (relative to mount point)
  - `file_count`, `total_bytes`
  - `last_built_at`
- `torrent_instances`:
  - `torrent_hash` (pk)
  - `payload_id` (fk)
  - `device_id`
  - `save_path`, `root_name` (or canonical resolved root)
  - `category`, `tags` (string/json)
  - `last_seen_at`
    Optionally:
- `payload_members` (only if needed early; can be deferred):
  - `payload_id`, `relpath`, `size`, `sha1`, `inode`, `path`

### New Commands (inside hashall)

- `hashall payload sync --qbit-url ...` (or `--qbit-config ...`)
  - pulls qBittorrent inventory and file lists
  - maps each torrent to an on-disk payload root
  - computes payload_hash using catalog file sha1/size
  - stores `torrent_hash → payload_id` mapping
- `hashall payload show <torrent_hash>`
  - prints payload_id, payload_hash, device, root_path, counts
- `hashall payload siblings <torrent_hash>`
  - lists all torrent hashes sharing the same payload_id

### Notes

- If catalog lacks sha1 for members (stale scan), command should emit:
  - “needs scan” status and refuse to compute payload_hash (or compute partial with explicit warning flag)

### Deliverables

- Schema migration(s)
- `hashall payload` subcommand(s)
- Minimal qBittorrent client module (read-only)

### Docs to Update

- `docs/architecture/architecture.md` (payload concept + tables + flow)
- `docs/architecture/schema.md` (new tables)
- `docs/tooling/cli.md` (new commands + examples)
- `docs/tooling/quick-reference.md` (short recipes)

### Tests

- Unit: payload_hash determinism (ordering, normalization)
- Unit: many torrents map to one payload
- Integration-ish: mock qbit responses → writes expected rows

### Commit Message(s)

- `feat(payload): add payloads + torrent_instances tables and migrations`
- `feat(payload): implement payload sync and sibling lookup`
- `docs: describe payload identity and mapping to torrent hashes`
- `test(payload): verify payload_hash determinism and sibling mapping`

---

# Stage 3 — External Orchestrator MVP: “Demote One Torrent” (stash→pool)

### Objective

Build the smallest tool that achieves real value:

- Choose ONE torrent (or payload) and safely move/re-home it from stash to pool when eligible.
- Prefer reuse: if payload already exists on pool (same payload_hash), **do not copy**.

### New Tool (external repo)

Create a new CLI tool (separate from hashall) for policy + orchestration.

**Recommended name options (function-tied, intuitive):**

- `rehome` (move to a new home)
- `resettle` (re-locate)
- `handoff` (transfer ownership)
  Pick one and stick with it; examples below use `rehome`.

### What `rehome` does (MVP)

Inputs:

- target `--torrent-hash` OR `--payload-hash`
- config for qBittorrent API
- configured mount roots for `/stash` and `/pool` (or discover via hashall devices table)

Actions (MVP demotion flow):

1. Ensure catalog is fresh:
   - require recent `hashall scan /stash` and `hashall scan /pool` (or instruct user to run; for MVP, just check `devices.last_scan_completed`)
2. Ensure payload mapping exists:
   - call `hashall payload sync` (or require it; MVP can call it)
3. Classification check (minimal rule):
   - Determine if payload has any hardlink children outside seeding domain on stash.
   - If yes → **BLOCK** (explain why).
4. If eligible:
   - Look up payload_hash on pool:
     - If exists: choose canonical pool root as target.
       - Build torrent “view” on pool (directory structure + hardlinks) if necessary.
     - If not exists:
       - Move payload root from stash to pool (single move).
       - Then build views for sibling torrents if needed.
5. Relocate torrent in qBittorrent:
   - set new save path to pool view/root
6. Verify:
   - file count + total bytes match
   - (optional) spot-check a few inodes or sample hashes
7. Cleanup:
   - if move occurred, stash copy is gone by definition; if reuse occurred, remove redundant stash view only after verification.

### How `rehome` builds views (MVP)

Start simple:

- For same-device view building (within pool): use filesystem hardlink creation.
- You may directly call `hashall link` later, but MVP can implement minimal view creation itself if needed.
  Preferred approach:
- Add `hashall link` helpers later; MVP can just do `ln` operations with explicit dryrun.

### Deliverables

- New repo: `rehome`
- CLI: `rehome plan --demote --torrent-hash ...` and `rehome apply PLAN --dryrun/--force`
- Plan format: JSON (easy) with explicit steps
- Greppable logs + summary

### Docs to Update

- New: `docs/tooling/REHOME.md` in rehome repo
- Update hashall docs to mention external orchestrator integration:
  - `docs/architecture/architecture.md` and/or `docs/tooling/quick-reference.md`

### Tests

- Unit tests for:
  - eligibility rule computation (external hardlinks)
  - payload reuse vs move decision
  - plan serialization/determinism
- Integration tests with mocked qbit API + temp filesystem trees (if feasible)

### Commit Message(s)

- `feat(cli): add rehome plan/apply for single-torrent demotion`
- `feat(policy): block demotion when external hardlink consumers exist`
- `docs: add end-to-end demotion workflow and safety notes`
- `test: add fixtures for reuse-vs-move planning`

---

# Stage 4 — Expand to Payload-Centric Operations (Demote Many / Sibling Sets)

### Objective

Move from “one torrent” to “one payload” as the unit of work:

- demote a payload once
- relocate all torrents (infohash variants) that map to that payload
- avoid redundant view creation

### Work

- Extend `rehome plan --demote` to accept:
  - `--payload-hash`
  - `--tag ~noHL` (optional) or `--category cross-seed` filters
- Add “batch demotion” mode with guardrails:
  - require explicit scope (payload hash, tag, or category)
  - never “slam everything” by default

### Deliverables

- Batch plan generation
- Parallelization optional (do not add until correctness is proven)

### Docs to Update

- rehome docs: batch examples + safe usage patterns
- hashall docs: payload sibling reasoning

### Commit Message(s)

- `feat(batch): support demoting all torrents for a payload_hash`
- `feat(filters): add tag/category scoping for batch planning`
- `docs: document batch demotion guardrails and examples`

---

# Stage 5 — Promotion Rules (pool→stash) Under “No Blind Copy” Constraint

### Objective

Implement promotion safely and simply:

- Allowed only if same payload already exists on stash (payload_hash match).
- If stash copy doesn’t exist, promotion is “blocked/manual”.

### Work

- Add `rehome plan --promote --torrent-hash ...`
- Logic:
  - compute payload_hash
  - if stash contains payload_hash:
    - rebuild stash view (hardlinks within stash)
    - relocate qbit
  - else:
    - emit blocked decision with explanation

### Deliverables

- Promote plan/apply support

### Docs to Update

- promotion behavior + blocked cases

### Commit Message(s)

- `feat(promote): add pool->stash promotion when payload exists on stash`
- `docs: document no-blind-copy promotion constraint and outcomes`

---

# Stage 6 — Follow-on Improvements (Edge Cases + Robustness)

## 6A. Payload “Variants” (Optional, Carefully Scoped)

Problem: same “movie” but different extras/layout → payload_hash differs.
Enhancement:

- define a **variant hash** that ignores:
  - `.nfo`, `.sfv`, `.txt`, `sample.*` (configurable)
- Store:
  - `payload_hash_strict`
  - `payload_hash_mediaonly` (or variant type)
    Use for “candidate detection” only; strict hash remains authoritative for automated actions.

Commits:

- `feat(payload): add optional media-only payload signature`
- `docs: explain strict vs variant payload matching and risks`

## 6B. Better External Consumer Detection

Improve “must stay on stash” rule:

- Precisely define “seeding domain root” and “external consumer paths”
- Consider bind mounts and alternate mountpoints (canonicalization)
- Provide debug output: list of offending paths/inodes

Commits:

- `feat(policy): improve external hardlink detection with canonical path reporting`
- `docs: define external consumer rule with examples`

## 6C. Harden View Reconstruction

- Handle multi-tracker torrents with subset file lists
- Handle renamed roots more gracefully
- Add idempotency: re-running apply doesn’t break, only repairs

Commits:

- `feat(view): make view creation idempotent and resilient to partial state`
- `test(view): add fixtures for subset-file torrents and renamed roots`

## 6D. Operationalization

- systemd timer templates for:
  - nightly scans
  - weekly reports of eligible demotions/promotions
- reporting: JSON + human text
- “resume failed plan” support

Commits:

- `feat(ops): add systemd timer examples and reporting commands`
- `docs: add operational runbook and troubleshooting`

---

# Agent Handoff Template (Use for Each Stage)

Each stage can be handed to a separate CLI agent using the same structure:

1. Read current docs:
   - hashall: `docs/architecture/architecture.md`, `docs/architecture/schema.md`, `docs/tooling/cli.md`
2. Implement stage scope only (no extra refactors).
3. Update docs as specified.
4. Add/extend tests.
5. Commit using Conventional Commits with:
   - WHAT changed
   - WHY (tie to stage objective)
   - NOTES on behavior compatibility / risk
6. Provide a short “Next agent” note in `docs/archive/project/DEVLOG.md` (or repo equivalent).

---

# “Shortest Path” Summary

1. Rename `conductor` → `link` (clarity, no behavior change)
2. Add `hashall payload` (payload_hash + torrent_instances mapping; same DB)
3. Build `rehome` MVP: demote one torrent/payload stash→pool with reuse-first logic
4. Expand to batch per payload_hash (siblings)
5. Add promotion (no-blind-copy)
6. Add edge-case coverage (variants, better external-consumer detection, robust view reconstruction)

This path gets a working stash→pool demotion loop fast, then iterates into completeness.

```

```
