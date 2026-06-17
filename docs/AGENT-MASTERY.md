# Hashall Agent Mastery Reference

**Version:** 1.2.0
**Audience:** CLI agents bootstrapping into any hashall session
**Read this before touching anything. Complete section 8 before dispatching any task.**

---

## 1. What This Repo Is

Hashall manages a large torrent seeding library spread across two ZFS storage pools, keeping every torrent seeding cleanly from its canonical path in both rTorrent (the active seeder) and qBittorrent (a passive deprecated mirror). The active mission is repairing ~2000+ items with wrong or legacy paths while migrating seed-only content from an old storage dataset to a new canonical one, without breaking any media library links or losing any data.

---

## 2. Architecture

```
src/hashall/
  cli.py                  Main CLI entry point — all hashall subcommands
  client_drift.py         RT/qB path-drift detection and repair
  save_path_repair.py     Moves files from staging dirs to canonical paths
  save_path_inference.py  Infers canonical path from qB category/tags/path
  qbittorrent.py          qB API client (pause guard, set_location, fastresume)
  payload.py              Payload sync, orphan GC, hash computation
  orphan_sweep.py         Relocates untracked seeding content to orphans dir
  rehome/
    executor.py           Orchestrates rsync → hardlink → stop → patch → start
    planner.py            REUSE / MOVE / BLOCK decision logic

docs/
  REQUIREMENTS.md         Full system requirements and architecture (authoritative)
  RT-QB-STATE-POLICY.md  Client state policy and repair decision trees
  SPRINT.md              Active sprint slices and evidence baseline
  OPS.md                 Live issue tracker (47 open items as of 2026-06-17)
  RUNBOOK.md             Canonical repair procedures
  review/R1-R5-*.md      j09 cold-read audit findings for all 5 mutation tools

~/.hashall/
  catalog.db              SQLite — all file/payload/torrent state
  seed-root-state.json    Authoritative list of active seeding roots

/dev/tools/traktor/config/tracker-registry.yml   Tracker identity registry
/dump/docker/gluetun_qbit/.../BT_backup/         qB fastresume files
```

---

## 3. Key Invariants

### Storage topology

```
/stash/media/                    ZFS pool — warm, active
  torrents/seeding/              stash seeding root
  movies/ shows/ books/          ARR media libraries (Radarr, Sonarr, Readarr)

/pool/data/media/torrents/       ZFS pool, legacy dataset — migration SOURCE only
  seeding/                       being vacated; never write here as a target

/pool/media/torrents/seeding/    ZFS pool, active dataset — canonical cold target
```

`/data/media/` is a bind mount to `/stash/media/` — same device, same filesystem. RT and qB report container paths (`/data/media/...`); on the host these are `/stash/media/...`.

Kernel device IDs (may change on reboot — use `fs_uuid` for durable identity):
- stash / `/data/media/` = device 49
- pool-media = device 45
- pool-data = device 48

### Hardlink rule

**Hardlinks cannot cross ZFS pool or dataset boundaries.** stash ↔ pool = different pools. pool-data ↔ pool-media = different datasets. No cross-boundary hardlinks, ever.

### Placement policy

Content with any file hardlinked to a media library (`/stash/media/movies/`, `/shows/`, `/books/`) **SHOULD** stay on stash. This is a strong preference, not an absolute block:
- Staying on stash preserves library links **and** saves pool space (shared inodes = zero extra bytes)
- Moving to pool breaks library links **and** forces a full byte-copy (adds space cost on pool)
- Operator can explicitly authorize exceptions

Content with `~noHL` (no library hardlinks, seed-only) **SHOULD** be on pool-media.

`~noHL` is **advisory only** — a qbit_manage scan at a point in time. Re-verify external consumer status at plan time. A new ARR import can create a hardlink after the tag was applied.

The placement unit is the **inode-sharing group** — all torrents whose files share inodes on the same filesystem. If any file in any member of the group has a library hardlink, the whole group SHOULD stay on stash.

### Client roles

**rTorrent (RT)** — active seeder, path authority. RT's path wins every dispute. RT items must always be in an active state (`stalledUP`, `uploading`, or downloading). Nothing in RT should be stopped or paused.

**qBittorrent (qB)** — passive deprecated mirror. Kept alive for tag/category/path metadata only. Will be shut down after RT migration completes. qB items must always be `stoppedUP`. Any qB item found actively uploading or downloading is a hard violation — stop it immediately.

Path dispute rule: if RT and qB disagree on save_path, RT wins → repoint qB to RT's path. RT is wrong only if: its path doesn't follow category rules, the path doesn't physically exist, or there is a documented reason.

### Canonical path formula

```
<seeding-root>/<category>/<item-payload-name>
```

Seeding root = stash or pool-media based on placement policy. The `<category>/<item-payload-name>` part is identical on both — only the root prefix changes.

Category by origin:
- ARR post-import (ATM moved): `tv/`, `movies/`, `books/`, `music/`
- cross-seed injection: `cross-seed/<prowlarr-tracker-name>/` (Prowlarr display name is canonical — do not rename to short key)
- qbit_manage tracker: `<tracker-name>/` per tracker-registry.yml

Staging dirs are NOT canonical — always temporary: `_rehome-unique/<hash>/`, `_qb-finish/`, `_qb-unique-repair/`, `_qb-repair-v2/`

### Cross-seed item identification (operator-confirmed 2026-06-17)

An item is a cross-seed item if it has **qB category = `cross-seed`**. The cross-seed tool hardlinks files from an existing seeding item and places them under `cross-seed/<prowlarr-tracker-name>/`.

**To identify the canonical tracker name for a cross-seed item — use the traktor registry first:**

The traktor registry at `/home/michael/dev/tools/traktor/config/tracker-registry.yml` is the authoritative one-stop source. It tracks all three identifiers per tracker:
- `tracker_key` — short canonical key (e.g., `darkpeers`)
- `prowlarr_display_name` — Prowlarr indexer display name (e.g., `Darkpeers (API)`) — what cross-seed uses as the on-disk directory name
- `tracker_url_pattern` — announce URL pattern for runtime lookup from RT

Resolution priority:
1. **Traktor registry** — look up announce URL from RT XMLRPC → match `tracker_url_pattern` → get both `tracker_key` and `prowlarr_display_name`
2. **qB tracker tag** — qbit_manage assigns tags from announce URLs; use as fallback if RT unavailable
3. **Current save_path** — parse directory name as last resort; unreliable if path is damaged

Both `prowlarr_display_name` and `tracker_key` are acceptable on-disk directory names. Do NOT rename an existing `prowlarr_display_name` path to `tracker_key` form — cross-seed re-creates the display-name path on the next injection cycle.

**`cross-seed/<tracker>/` IS the canonical form for cross-seed items.** Do not remove the `cross-seed/` prefix.

**Implication for Slice 12b:** The sprint description "legacy prefix removal" is stale — it predates the §4.4 policy confirmation. `canonical-tree-report` correctly does not flag `cross-seed/<tracker>/` items as non-canonical (82 total non-canonical items; none in this pattern). Slice 12b as written should be treated as superseded unless the operator explicitly reauthorizes it with a revised path transformation.

### Two distinct path-routing mechanisms (operator-confirmed 2026-06-17)

There are two completely different mechanisms that determine where a torrent's files land, and they produce different path schemas. Confusing them has been the root cause of multiple rogue-code incidents.

**Mechanism 1 — Explicit save_path (cross-seed items, ATM OFF):**
- The cross-seed tool assigns `category=cross-seed` AND explicitly sets `save_path` to `<seeding-root>/cross-seed/<prowlarr-tracker-name>/` at injection time.
- ATM is OFF for all cross-seed items. qB respects the explicit path and does not move the torrent.
- Canonical result: `seeding/cross-seed/<prowlarr-tracker-name>/<item>/`

**Mechanism 2 — ATM-managed (regular items, ATM ON):**
- qBittorrent's Automatic Torrent Management maps `category → base save path` using the category's configured directory in qB settings.
- A torrent with `category=tv` and ATM ON lands at `seeding/tv/<item>/`.
- A tracker-tagged item with `category=darkpeers` and ATM ON lands at `seeding/darkpeers/<item>/`.
- Canonical result: `seeding/<category-or-tracker-key>/<item>/` — NO `cross-seed/` prefix.

**The two schemas must never be mixed.** `seeding/<tracker>/` is NOT a valid path for a cross-seed item. `seeding/cross-seed/<tracker>/` is NOT a valid path for an ATM-managed item.

### Cross-seed path history and known damage (2026-06-17)

Cross-seed's config link folder has had two names over time:

| Era | Config root | On-disk form |
|-----|-------------|--------------|
| Old | `cross-seed-link/` | `seeding/cross-seed-link/<tracker>/<item>/` — legacy, `normalize_cross_seed_refactor_path` migrates these to `cross-seed/` |
| Current | `cross-seed/` | `seeding/cross-seed/<tracker>/<item>/` — canonical |

**Known damage (OP-16/OP-17, confirmed 2026-06-17):** `save_path_inference.py` `derive_policy_base_save_path` line 223 has a policy inversion — it returns bare `<tracker>/` for cross-seed category items instead of `cross-seed/<tracker>/`. Rogue hashall code using this function moved ~2000 cross-seed items OUT of `cross-seed/<tracker>/` into bare `<tracker>/` paths at the seeding root. Only FearNoPeer (~185 items, injected after the cross-seed config changed to the shorter `cross-seed/` root) remains at the correct `cross-seed/FearNoPeer/` paths.

**Do not treat bare `<tracker>/` paths as canonical for cross-seed category items.** They are damaged paths. No migration may proceed until OP-16 (code fix) is 4-gate validated.

### ~noHL tag — advisory only, never authoritative (operator-confirmed 2026-06-17)

`~noHL` is a tag applied by qbit_manage at a point in time based on reference data available to qbm at that moment. It is a HINT, not a fact. It can be wrong in multiple ways:

- **Staleness:** A new ARR import may have created a library hardlink AFTER the tag was applied. The tag won't update until qbm runs again.
- **qbm accuracy:** qbm's reference data about what files are in media libraries may itself be incomplete or out of date.
- **Scope:** The tag applies to the **qB item only** — it says nothing about sibling payloads in the same inode-sharing group. A sibling may have library hardlinks even if this item doesn't.
- **RT/qB path divergence:** qB and RT can report different save_paths for the same torrent. The tag is on the qB record; the actual file location may differ.

**`~noHL` may be used as a starting hint that pool placement is worth investigating — nothing more.**

Before any pool rehome is authorized for a `~noHL` item:
1. Re-verify via filesystem scan that NO file in the torrent has an external hardlink consumer in any media library path (`/stash/media/movies/`, `/shows/`, `/books/`, etc.)
2. Extend that check to **all sibling payloads** in the inode-sharing group on the same filesystem — if any sibling has a library hardlink, the whole group must stay on stash
3. Verify the item's actual on-disk location using BOTH RT save_path and qB save_path — they may differ; check both
4. Only after all three checks pass may pool placement be authorized for the group

### Single-file torrent path rule (operator-confirmed 2026-06-17)

The canonical path for a single-file torrent depends on what the **torrent itself defines internally**:

| Torrent internal structure | Canonical on-disk form |
|---|---|
| Bare file (no folder defined in torrent) | `<seeding-root>/<category>/<filename>` — file sits directly in category dir, NO subdirectory |
| Folder defined in torrent | `<seeding-root>/<category>/<folder-name>/<filename>` — subdirectory matches torrent's internal folder name |

**Spurious subdirectory = bug.** If a single bare-file torrent has a release-name folder around it that is NOT defined in the torrent, that folder was created by RT (known RT artifact) and is incorrect. Classify as NEEDS_REPAIR. Do not propagate the spurious folder to the canonical path calculation.

**How to check:** qB and RT both report whether a torrent has a top-level folder. If `content_path == save_path + "/" + filename` with no intermediate directory, the torrent has no internal folder.

### Single-file scan mode for placement verification (operator-confirmed 2026-06-17)

The unified path tool will support two scan modes for ~noHL verification:

- **Default (simulated):** Uses catalog DB + `~noHL` tag + known hardlink counts as a proxy. Fast. May produce false positives (stale tags). Suitable for dry-run planning.
- **`--full-scan` mode:** Performs live filesystem hardlink check on all files across all sibling payloads. Slow but accurate. Results are saved to disk (e.g., `~/.hashall/noHL-scan-<date>.json`) for offline review and reuse in subsequent runs without rescanning.

### Inode-sharing groups (hitchhiker groups) — placement is group-scoped

When two or more torrents share file data via hardlinks on the same filesystem, they form an inode-sharing group. Placement decisions (stash vs pool) apply to the **entire group**, not to individual items.

Example: `Aither/Show.S01/episode.mkv` and `Darkpeers/Show.S01/episode.mkv` are hardlinked to the same inode. Moving `Aither/Show.S01/` to pool would physically move the file bytes — leaving `Darkpeers/Show.S01/episode.mkv` pointing to a vacated location on stash.

**Rule:** Before authorizing any pool rehome, enumerate the full inode-sharing group for all files in the torrent. If any member of the group has an external library hardlink, the whole group stays on stash. The group check must happen at the planning step, before any execution.

### Migration moratorium (operator directive 2026-06-17)

**No mutations from rehome or save_path_inference until OP-18 exploration is complete and 4-gate validated.**

Two tools have each caused mass displacement at scale:

| Tool | Dimension | Damage caused |
|------|-----------|---------------|
| `rehome/planner.py` + `executor.py` | WHERE (stash vs pool placement) | Original chaos — buggy executor displaced thousands of items |
| `save_path_inference.py` | WHAT PATH (category formula) | OP-16 policy inversion stripped `cross-seed/` prefix from ~2000 items |

Running them independently in any order risks compounding damage — one broken result becomes input to the other. OP-18 explores building one unified, validated tool that resolves both dimensions per item before any execution: placement policy → seeding-root, category → path formula → full target path, diff vs actual, migrate, sync qB.

Until OP-18 is resolved:
- Do not run `hashall save-path-repair --execute`
- Do not run `hashall rehome apply` or any rehome executor path
- Do not run `hashall client-drift apply --apply` for cross-seed category items
- Dry-run and audit commands remain permitted

### Cross-device guard (j10 + j12 — resolved)

`set_location` in `qbittorrent.py` pauses the torrent, checks `st_dev`, and blocks if source and target are on different devices. **j12 added a bypass:** if files already exist at the target path (confirmed via `_files_exist_at_target`), the cross-device block is skipped — qB updates metadata only, no physical copy. Both HIGH drift items (NOVA.S50, Magic.City.S01) cleared via this bypass. Drift `high=0` as of 2026-06-17.

---

## 4. Key Commands

```bash
# Audit RT/qB path agreement (always use ANCHOR_SCAN=200000, not default 0)
make client-drift-audit ANCHOR_SCAN=200000

# Preview drift repairs for specific hashes
hashall client-drift apply --dry-run --hash <prefix> --anchor-scan-max-files 200000

# Execute drift repairs (gate-validated items only)
hashall client-drift apply --apply --hash <prefix> --anchor-scan-max-files 200000

# Full catalog refresh (scan + payload sync + drift baseline)
make db-refresh-fast-gated-parallel

# Sync qB torrent metadata to catalog
hashall payload sync

# Show canonical path class breakdown (how many items in each class)
hashall canonical-tree-report

# Preview staging→canonical path repairs
hashall save-path-repair --dry-run

# Execute staging→canonical path repairs (gate-validated only)
hashall save-path-repair --execute

# Preview tracker issue replacements (deleted bucket)
make trk-warn-dry BUCKET=deleted

# Replace individual tracker-deleted items with escalating search
make trk-warn-replace-individual BUCKET=deleted
```

---

## 5. High-Risk Files

| File | Risk | Why |
|------|------|-----|
| `src/hashall/qbittorrent.py` | HIGH | `set_location` triggers physical file moves if pause guard fails; caused 90-torrent missingFiles incident |
| `src/hashall/cli.py` | HIGH | `repoint_both_to_pool` — wrong operation order leaves RT committed but qB stale; fixed in j10, fragile |
| `src/hashall/save_path_repair.py` | HIGH | `_resolve_full_hash` 0-match returns wrong path → files moved to wrong location; fixed in j10 |
| `src/hashall/client_drift.py` | HIGH | Apply path has no cross-device check at call site; relies entirely on qbittorrent.py guard |
| `src/hashall/rehome/executor.py` | HIGH | Rollback skips ATM restoration (OP-30); resume races with recheck state (OP-31) |
| `~/.hashall/catalog.db` | CRITICAL | Single source of truth for all payload/torrent state; corruption = manual recovery |
| `/dump/docker/.../BT_backup/*.fastresume` | CRITICAL | qB session state; wrong patch causes stoppedDL on restart (Feb-2026 incident: 2103 torrents) |
| `~/.hashall/seed-root-state.json` | HIGH | Consumed by all orchestration tools; wrong seeding root = wrong move target |

---

## 6. Active Session State

**Session goal:** `Post-12b repair: T1 operator review → T2a-T2e path repairs toward zero mismatches`

**T1 (operator review) = DONE.** j09 cold-read audit (5 tools, 47 findings) + j10 critical bug fixes (3 bugs fixed, all tests green) committed to CR branch and merged to main.

**What is committed (CR branch `cr/hashall-20260530-000517-claude`, merged to main):**
- j09: R1–R5 audit findings for all 5 mutation tools (docs/review/)
- j10: `_resolve_full_hash` 0-match fix, `set_location` pause guard, `repoint_both_to_pool` order fix
- j11-T01: Gate 1+2 certification for drift fix (CERTIFIED SAFE FOR DRY-RUN)
- j11-T02: Gate 3 dry-run + pilot — BLOCKED by cross-device guard (working as designed)
- This file (AGENT-MASTERY.md)

**In-flight (j11, open):**
- T03: Class 4 investigation (64 `_rehome-unique/<hash>/` items — grew from 10, cause unknown)

**Open work (planned jobs):**

| Job | Goal | Blocked on |
|-----|------|-----------|
| j12 | Refine cross-device guard — check file existence at target before blocking | Ready to start |
| j12 | Re-run Gate 3 drift fix after guard refinement — execute 2 HIGH items | j12 guard fix |
| j13 | Slice 12b — rename `cross-seed/<tracker>/` + repoint both clients (~2125 items) | j12 complete |
| j14 | Slice 12c — `cross-seed/<hash>/` items (3) | j13 complete |
| j15 | Class 4 repair (64 staging items) | j11-T03 investigation |

**Drift baseline (2026-06-16):**
- torrent_instances: 5577 | drift: 4 (high=2, low=2)
- NOVA.S50 `2d4016de` — qB on stash, RT on pool-media, files exist on pool-media → blocked by cross-device guard
- Magic.City.S01 `f0bc85ee` — same pattern

---

## 7. Safety Rules

**Never:**
- Run `--execute` or `--apply` without passing all three gates (code review → walkthrough → dry-run + pilot)
- Use `rm -rf` — individual file removes with verification only
- Hardlink across ZFS pool or dataset boundaries (stash ↔ pool, pool-data ↔ pool-media)
- Let qB actively upload or download — stop it immediately if found in that state
- Commit source cleanup before target is verified live in both clients
- Treat `~noHL` as authoritative — always re-verify at plan time
- Ignore a cross-device guard block — investigate why, don't bypass
- Expand task scope beyond what the brief specifies
- Commit to main or any branch other than the active job branch

**Always:**
- Run `make client-drift-audit ANCHOR_SCAN=200000` (not default 0) before any drift repair
- Dry-run first → limited pilot (≤5 items) → post-check → then widen batch
- Repoint qB to RT, never RT to qB, unless RT path is demonstrably wrong
- Use offline fastresume patch (stop → patch → start) for relocation — not `setLocation` alone
- Verify post-state after any pilot: run the audit again, confirm target items left drift report

**Three-gate validation (mandatory for all live mutations):**
- Gate 1 — Code review: read every touched file, confirm j10 fixes present, certify no bugs
- Gate 2 — Walkthrough: trace execution with real params, certify safe for dry-run
- Gate 3 — Dry-run + pilot ≤5 items: inspect output, verify post-state, then authorize full batch

---

## 8. Mastery Self-Check

Answer all 7 before dispatching any task. Answers come from this document only.

**Q1.** A torrent's MKV file is hardlinked to `/stash/media/movies/`. Where should it live and why — and is this a hard rule or a preference?

**Q2.** RT says a torrent is at `/pool/media/torrents/seeding/tv/Show.S01/`. qB says it's at `/data/media/torrents/seeding/cross-seed/Aither (API)/Show.S01/`. Which path wins, and what action do you take?

**Q3.** You are about to run `hashall save-path-repair --execute` on 200 items. What are the three steps you must complete first, in order?

**Q4.** `set_location` is called with qB save_path on device 49 and a target path on device 45. It blocks. Under what condition is this block too conservative, and what does j12 fix?

**Q5.** A cross-seed torrent injected from Prowlarr shows up with category directory `Darkpeers (API)`. Should you rename it to `darkpeers` (the short registry key)? Why or why not?

**Q6.** You find a qB torrent in `stalledUP` state. What must you do, and how fast?

**Q7.** The drift audit default runs with `ANCHOR_SCAN=0`. Why is that wrong, and what value should you use?

---

*Answers to all 8 questions are contained in sections 1–7 above. If you cannot answer a question without opening another file, re-read the relevant section before proceeding.*
