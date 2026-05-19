# Backlog (Ranked Priorities)

Last updated: 2026-05-19
Status: canonical

Extracted from PLAN.md. For current-sprint work see `docs/SPRINT.md`.

## P0 — Shared Migration Constructor

Refactor migration around two phases: donor acquisition + shared attach/repoint.
- `REUSE`: donor already exists at target.
- `MOVE`: donor is transferred externally first, then handed to shared attach path.
- Both lanes must: build/verify target payload layout → offline fastresume patch qB → restart qB if needed → recheck → verify seed-ready → sync catalog → track cleanup provenance.
- `qB setLocation` must not be used in the mainline path.
- **Status:** implemented in code for REUSE and MOVE; MOVE unproven live.

## P1 — Finish Pool REUSE

Continue remaining REUSE groups in small batches with the offline constructor.
Gates before each apply:
- no `MV`/`moving` reviews
- no download-like flips
- final qB states in `stoppedup`/`stalledup`
- `catalog OK` results
- cleanup provenance cites `/pool/data/media/torrents/seeding/...` not legacy `/pool/data/seeds/...`

Note: planner reports `0 MOVE groups available` at current safety level, but raw inventory
still shows old-path payloads.

## P2 — Make MOVE Safe

MOVE code path is refactored but unproven live. Next gate: controlled live MOVE pilot.
Scale only after: no `MV/moving`, no download-like flip, cleanup messaging correct, planner agrees.

## P3 — Refresh / Identity Stability

- Keep `hashall refresh --verbose` healthy across stash, pool-media, pool-data, spare.
- Preserve stable `fs_uuid`; keep `device_id` limited to runtime metadata.
- Update catalog rows immediately for known migration changes (not waiting on next full refresh).
- Recommended refresh command (after merging fast-refresh branch):
  ```bash
  make db-refresh-fast-gated-parallel
  ```

## P4 — qB Repair / Guard Hardening

- Keep `qb-start-seeding-gradual.sh` focused on resuming `stoppedUP` torrents.
- Guard: halt on newly flipped downloading-like torrents; not on preexisting ones.
- Continue post-apply verification and cache tooling coverage.

## P5 — ~noHL Readiness

After pool migration solid, move `~noHL` payloads from `/data/media/torrents/seeding`
→ `/pool/media/torrents/seeding`.
- First proving group: `Alien Romulus` (14 siblings, 7 marked `~noHL`)
- Reuse donor-acquisition + shared attach architecture.

## Canonical Tree Normalization

Non-canonical paths created by early rehome sessions. All items are seeding correctly but paths
do not match the canonical formula (§4.4.2). Target state: every torrent at
`<seeding-root>/<category>/<item-payload-name>`. Prowlarr display-name dirs (e.g.
`Darkpeers (API)/`) are **acceptable and must not be renamed** — cross-seed still injects
there; see §4.4.3.

**Baseline snapshot (2026-05-19, stash + pool-media payloads):**

| Class | Count | Path pattern | Cause | Remediation |
|---|---|---|---|---|
| 1 | 10 | `cross-seed/<40-hex-hash>/` | qB torrent hash used as tracker dir during early injection | Repoint client to canonical `cross-seed/<tracker-key>/` path; hardlink content if needed |
| 2 | 7 | `cross-seed/other/` | RT used `"other"` as tracker placeholder when announce URL was unresolved | Resolve tracker from announce URL → repoint to canonical tracker path |
| 3 | 14 | `cross-seed/_movie/`, `cross-seed/_<name>/` | Early rehome used underscore-prefixed pseudo-categories | Repoint to canonical tracker or media-type path |
| 4 | 12 | `_rehome-unique/<hash>/` on stash or pool | Temporary staging path never promoted to canonical | Promote to canonical path (content already at correct location); repoint clients |
| 5 | 47 | `_qb-unique-repair/`, `_qb-finish/` | qB repair staging paths never cleaned up after repair completed | Verify torrent healthy, move to canonical path, repoint clients |

Total non-canonical: ~90 payloads (out of ~5200). Class 6 (Prowlarr display names) is acceptable — do not touch.

**Safe remediation order** (later classes depend on earlier ones being stable):
1. **Class 4** (`_rehome-unique/`) — no data movement, pure repoint; lowest risk
2. **Class 2** (`cross-seed/other/`) — resolve tracker first via announce URL, then repoint
3. **Class 1** (`cross-seed/<hash>/`) — same: resolve tracker, then repoint
4. **Class 3** (`cross-seed/_<prefix>/`) — resolve intended category, then repoint
5. **Class 5** (`_qb-unique-repair/`, `_qb-finish/`) — verify torrent healthy first, then repoint
6. **Type A de-hitchhike** (multiple payload_hash sharing one dir) — highest risk; content-level split required; do last

**Other deferred structural renames** (directory-level, not per-torrent):
- `cross-seed-link/` → `cross-seed/` (legacy dir name; scan only)
- `orphaned_data/` → `orphans/` at `*/media/torrents/orphans`
- Drain `/pool/data` legacy seeding content to `/pool/media` (ongoing migration)
- Do not rename any directory until both clients agree on the policy-correct target path.

## Deferred Follow-Up

- `V for Vendetta` refresh-upgrade anomaly: refresh ended OK but root logged `files=0 bytes=0`.
  Investigate when active migration lane is idle.
- Orphan GC redesign: current code deletes DB entries only; needs redesign to RELOCATE
  files to `/stash/media/orphaned_data/` holding area before any deletion.
  Use: `HASHALL_ORPHAN_GC_MAX_PRUNE_COUNT=3000 HASHALL_ORPHAN_GC_MAX_PRUNE_FRACTION=0.5`

## Code Review Gate — config.py stale default (P2 prerequisite)

`src/rehome/config.py` DEFAULTS has `"default_dest_root": "/pool/data/seeds"`. This is wrong:
- `/pool/data/seeds` is a cross-seed `dataDir` scan path, **not** a rehome destination (see REQUIREMENTS.md §2.1)
- The active pool seeding root is `/pool/media/torrents/seeding` per `seed-root-state.json`
- If a user runs rehome without a `~/.hashall/rehome.toml` override, MOVE targets land at the wrong location

**Fix required before any live MOVE pilot:**
1. `src/rehome/config.py`: remove `/pool/data/seeds` as `default_dest_root`; replace with logic that reads the active seeding root from `seed-root-state.json` at runtime (or require explicit operator configuration with no silent fallback)
2. Audit all other source files that reference `/pool/data/seeds` as a seeding root or MOVE target and correct them
3. `src/rehome/seed_state.py`: remove `/pool/data/seeds` from the fallback known-roots list unless it is explicitly registered as a legacy migration source in the active `seed-root-state.json`

## Active Risks

- `MOVE` is refactored but unproven live; pilot validation is the stop gate.
- `config.py default_dest_root` is stale (`/pool/data/seeds`); live MOVE without toml override would target wrong pool location (see Code Review Gate above).
- Cleanup source path/provenance can drift to legacy `/pool/data/seeds/...` aliases.
- Large batch operations can hide qB/API transient failures; inspect after every run.
