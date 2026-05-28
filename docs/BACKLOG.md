# Backlog (Ranked Priorities)

Last updated: 2026-05-20
Status: canonical

Extracted from PLAN.md. For current-sprint work see `docs/SPRINT.md`.

---

## Agent Safety / Doc Gaps

Gaps discovered during the 2026-05-20 session when an agent ran `save-path-repair --execute`
without adequate context, causing 91 stoppedDL items (recovered via fastresume backup).
These tasks must be completed before any agent runs mutating path-repair operations again.

### Gap 1 — [DOC] Add save-path-repair section to RUNBOOK.md (BLOCKING for slice 12)

`hashall payload save-path-repair` has no RUNBOOK entry. An agent reading the runbook
before running the tool finds nothing. Required content:

- **Purpose:** scans `_rehome-unique/<hash>/` dirs, infers canonical save path via
  `save_path_inference.py`, moves files, patches qB fastresume, repoints RT.
- **Dry-run first:** always run `hashall payload save-path-repair --dry-run` and inspect
  every item before `--execute`. Never run `--execute` on cached/stale dry-run output.
- **Known bug — fastresume patched for 0-moved-files items:** `audit_repair_candidates()`
  matches a `<hash-prefix>/` dir to the first qB torrent whose info_hash starts with that prefix.
  If `files_moved == 0` AND the matched qB torrent's data is not under `_rehome-unique/`,
  fastresume is incorrectly patched to a non-existent canonical path → `missingFiles` on restart.
  Guard: skip fastresume patch if `files_moved == 0` and qB `save_path` does not contain
  `_rehome-unique`.
- **Known bug — `_resolve_full_hash()` prefix mismatch:** scans `_rehome-unique/<hash>/` where
  `<hash>` is 16–40 chars. Expands short hashes via `startswith` prefix match against ALL qB
  torrents. If the prefix matches more than one torrent, the wrong item gets patched.
  Guard: confirm prefix matches exactly one hash; abort if ambiguous.
- **`_scan_rehome_unique_hashes()` only finds top-level `_rehome-unique/`:** Does NOT find
  nested `_rehome-unique/` dirs like `cross-seed/hawke-uno/_rehome-unique/`. These must be
  handled manually.
- **Recovery procedure:** stop qB; restore `.bak-repair` fastresumes from
  `/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/`; restart qB; verify.
- **File:** `src/hashall/save_path_repair.py`

### Gap 2 — [DOC] Add external repo dependency map to AGENTS.md (BLOCKING for all agent work)

Agents need to know about external repos before touching tracker names, category slugs,
sys/docker configs, or qB management scripts. No single place lists these. Add to AGENTS.md:

| Resource | Path | Purpose |
|---|---|---|
| traktor registry | `/home/michael/dev/tools/traktor/config/tracker-registry.yml` (preferred) or `/home/michael/dev/work/glider/glider-docker/tracker-ctl/config/tracker-registry.yml` | Authoritative tracker key → URL, Prowlarr name, qB category, RT label |
| rt-tracker-manual-report.py | `~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py` | trk_warn report + action script; edits go in sys/docker repo, NOT hashall worktree |
| qbm config | `~/dev/sys/docker/qbit_manage/config.yml` | qB category → path mappings; uses `!ENV` YAML tags so PyYAML `safe_load` returns `{}` |
| cross-seed config | `~/dev/work/glider/glider-docker/cross-seed/config.js` | linkDirs, linkCategory, dataDirs |
| sys/docker repo | `~/dev/sys/docker/` | RT container config, systemd units, mirror scripts; separate git repo from hashall |

**Critical:** Before assigning a tracker name as a qB category, save-path segment, or SYSTEM_TAG,
look up the `tracker_url_pattern` in the traktor registry to get the authoritative `tracker_key`.
Do not guess from strings in paths, qB tags, or RT announce URLs.

### Gap 3 — [DOC] Fix SPRINT.md slice 12a description

SPRINT.md says "Class 4 repairs: `_rehome-unique/<hash>/` — pure repoint, no data movement".
This is wrong for items with actual data. Investigation found three groups:

- **Group A (items with data):** data IS in `_rehome-unique/` — requires `mv` to canonical path,
  then RT repoint + qB fastresume patch. NOT a pure repoint.
- **Group B (empty dirs):** `_rehome-unique/<hash>/` dir exists but is empty — safe to delete,
  then repoint clients to wherever data actually lives. No data movement.
- **Group C (nested staging):** `cross-seed/<tracker>/._rehome-unique/<hash>/` — nested under
  a tracker dir; not found by `_scan_rehome_unique_hashes()`.

Update SPRINT.md slice 12a to reflect this reality. Before any Class 4 repair, run:
`ls -la <seeding-root>/_rehome-unique/` and categorize each item as A/B/C.

### Gap 4 — [DOC] Add canonical tree repair execution protocol to RUNBOOK.md

BACKLOG.md describes the 5-class taxonomy and remediation order. RUNBOOK.md has no execution
steps. Agents planning Class 1–5 repairs find no safe command sequence. Add:

- **Required prereq for all cross-seed path repairs:** look up tracker key from
  `tracker-registry.yml` by matching announce URL against `tracker_url_pattern` entries.
  Never infer tracker key from path strings alone.
- **Class 4 repair sequence:** categorize item (Group A/B/C, see Gap 3) → Group A: `mv
  <src>/<hash-dir>/ <seeding-root>/<tracker-key>/<item-name>/`, RT repoint, qB fastresume patch;
  Group B: delete empty dir, confirm clients already point elsewhere; Group C: manual.
- **Class 1/2/3 repair sequence:** `python3 -c "import subprocess; ..."` to get announce URL →
  look up tracker key in registry → `mv` dir → RT `rt repoint --apply` → qB fastresume patch
  (NOT `set_location` — that triggers a physical move).
- **qB repoint rule:** always patch fastresume offline (stop qB → patch → restart), NOT
  `set_location` API. `set_location` triggers a physical data move.

### Gap 5 — [CODE] save_path_inference.py SYSTEM_TAGS is hardcoded, not from registry

`src/hashall/save_path_inference.py` maintains a hardcoded `SYSTEM_TAGS` frozenset of tag names
that are NOT tracker identifiers. During the 2026-05-20 session, `speed` was added as a system
tag without consulting the traktor registry — it may be the wrong exclusion.

Fix: either (a) load non-tracker tag list from tracker-registry.yml at runtime, or (b) add a
prominent code comment citing §4.4.4 of REQUIREMENTS.md and the registry path, so any future
additions are checked against the registry first. Add a test that validates SYSTEM_TAGS against
the known non-tracker tags (private, cross-seed, ~noHL, ~share_limit, etc.).

### Gap 6 — [CODE] save-path-repair safety hardening (prerequisite for slice 12 execution)

Two code-level safety bugs must be fixed before `save-path-repair --execute` is run again:

**Bug A — fastresume patch for 0-moved-files items:**
In `execute_repair()`, skip the fastresume patch step when `repair_action.files_moved == 0`
AND the matched qB torrent's current `save_path` does NOT contain `_rehome-unique`.
Currently, when a hash prefix matches a qB torrent whose data is not in `_rehome-unique/`,
the fastresume is overwritten to point to a non-existent canonical path → `missingFiles`.

**Bug B — ambiguous prefix match in `_resolve_full_hash()`:**
When the dir name is fewer than 40 chars, `_resolve_full_hash()` matches via `startswith`.
If multiple qB torrents share that prefix (unlikely but possible), the wrong item is picked.
Fix: if the prefix matches more than one full hash, raise an error rather than silently
using the first match.

These bugs are in `src/hashall/save_path_repair.py`. Fix and add unit tests before running
any live Class 4 or Class 5 repair.

---

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
