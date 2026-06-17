# Hashall Agent Mastery Reference

**Version:** 1.0.0  
**Audience:** CLI agents bootstrapping into any hashall session  
**Read this before touching anything.**

---

## 1. What This System Does

Manages a large torrent seeding library across two ZFS storage pools. The core
mission is: every torrent seeding cleanly from its canonical path in both RT and
qB, with zero drift, zero staging artifacts, and no content at risk of loss.

Three active workstreams:
1. **Path normalization** — move content from legacy/broken paths to canonical paths
2. **Dataset migration** — move seed-only content from pool-data (legacy) to pool-media (canonical cold storage)
3. **Client drift repair** — keep RT and qB save_paths in agreement

---

## 2. Storage Topology

```
/stash/media/          (ZFS pool — warm/active)
  torrents/seeding/    ← stash seeding root
  movies/              ← Radarr library
  shows/               ← Sonarr library
  books/               ← Readarr/Speakarr library

/pool/data/            (ZFS pool — legacy, migration SOURCE)
  media/torrents/seeding/   ← pool-data seeding root (being vacated)

/pool/media/           (ZFS pool — cold, canonical TARGET)
  torrents/seeding/    ← pool-media seeding root (canonical for seed-only content)
```

**Container path alias:** `/data/media/` → `/stash/media/` (bind mount, same device)  
RT and qB both report paths as `/data/media/...` inside containers; on the host this is `/stash/media/...`.

**Device IDs (as seen by kernel, may change on reboot — use fs_uuid for durable identity):**
- stash = device 49 (or look up in devices table)
- pool-media = device 45 (or look up in devices table)
- pool-data = device 48 (or look up in devices table)

**Critical constraint:** Hardlinks CANNOT cross ZFS pool boundaries. stash and pool are different pools. pool-data and pool-media are different datasets within /pool — also separate filesystems. No hardlinks across any of these.

---

## 3. Placement Policy

### Where content SHOULD live

**Stash** — content with any hardlink to a media library (`/stash/media/movies/`, `/shows/`, `/books/`).  
**SHOULD** (strong preference, not absolute prohibition):
- Keeping on stash preserves existing library hardlinks AND saves pool space (no duplicate bytes)
- Moving to pool breaks library links AND forces a full byte-copy to pool (space cost)
- Exception: operator can explicitly authorize stash→pool with a library consumer if willing to pay the space and link-break cost

**Pool-media** — content that is seed-only, no library hardlinks, tagged `~noHL`.  
This is the canonical cold-storage seeding home. All seed-only content should converge here.

**Pool-data** — NOTHING new goes here. It is a migration source lane being vacated. Read from it, never write to it as a target.

### ~noHL tag

qbit_manage scans hardlinks and applies `~noHL` to torrents with no library hardlinks.  
`~noHL` = eligible for pool migration. But it is **advisory only** — a scan at a point in time.  
Always re-verify external consumer status at plan time. A new ARR import between qbm scan and your plan can create a new hardlink.

### Seeding root selection rule

```
Has any file in the inode-sharing group a hardlink to a media library?
  YES → SHOULD stay on stash
  NO  → SHOULD be on pool-media
```

The placement unit is the **inode-sharing group** (all torrents whose files share inodes on the same filesystem), not just the individual torrent.

---

## 4. Client Roles

**rTorrent (RT)** — active seeder, path authority.  
- RT is the operational truth. RT's path wins all disputes.
- RT must always be in an active state: `stalledUP`, `uploading`, or actively downloading.
- Nothing in RT should be `stoppedUP` or `stoppedDL` — fix immediately.

**qBittorrent (qB)** — passive deprecated mirror.  
- qB is kept alive only for its tag/category/path metadata. It will be shut down when the RT migration is complete.
- qB must NEVER actively upload or download. Every qB item should be `stoppedUP`.
- `qB downloading` = hard violation. Stop immediately. Investigate why.
- qB paths must match RT paths. When they differ, RT wins → repoint qB.

**Path dispute tiebreaker (§8.4 REQUIREMENTS.md):**
1. One client on wrong placement tier → repoint to correct tier
2. Both on correct tier but different paths → RT wins, repoint qB
3. RT path deemed incorrect only if: doesn't follow category rules, path doesn't physically exist, or documented reason

---

## 5. Canonical Path Formula

```
<seeding-root>/<category>/<item-payload-name>
```

Seeding root is determined by residency class (stash vs pool-media).  
The `<category>/<item-payload-name>` portion is identical on both — only the root prefix differs.

### Category rules (by origin)

| Origin | Category |
|--------|----------|
| ARR pre-import (awaiting import) | `sonarr/`, `radarr/`, etc. |
| ARR post-import (ATM moved it) | `tv/`, `movies/`, `books/`, `music/` |
| cross-seed injection | `cross-seed/<prowlarr-tracker-name>/` |
| qbit_manage tracker assignment | `<tracker-name>/` (from tracker-registry.yml) |

**Prowlarr display name is canonical for cross-seed** (e.g. `Darkpeers (API)` not just `darkpeers`).  
Do not rename existing cross-seed items to the short-key form — cross-seed would recreate the display-name path.

### Staging directories (NOT canonical)

These are temporary and must not be treated as permanent:
- `_rehome-unique/<hash>/` — unique per-item tree during rehome construction
- `_qb-finish/` — qB finish staging
- `_qb-unique-repair/`, `_qb-repair-v2/` — repair staging

---

## 6. Key Tools

| Command | What it does |
|---------|-------------|
| `make client-drift-audit ANCHOR_SCAN=200000` | Full RT/qB path agreement audit |
| `hashall client-drift apply --dry-run` | Preview drift repairs |
| `hashall client-drift apply --apply` | Execute drift repairs |
| `hashall payload sync` | Sync qB torrent metadata to catalog |
| `make db-refresh-fast-gated-parallel` | Full catalog refresh |
| `hashall canonical-tree-report` | Show path class breakdown |
| `hashall save-path-repair` | Repair staging→canonical path moves |
| `make trk-warn-dry BUCKET=deleted` | Preview tracker issue replacements |

**Tool safety status (as of 2026-06-17, post j09/j10):**
- `client_drift apply --apply`: SAFE with j10 fixes (pause guard, qB-before-RT ordering)
- `save-path-repair --execute`: SAFE with j10 fixes (_resolve_full_hash no longer silently wrong)
- Both tools require three-gate validation before any production run

---

## 7. Three-Gate Validation (MANDATORY for any live mutation)

**No mutation command runs without passing all three gates.**

**Gate 1 — Code review:** Read every file the command touches. Check for bug patterns from j09/j10 audit. Confirm fixes are in place. Fix any found issues. Certify clean.

**Gate 2 — Simulated walkthrough:** Trace the exact execution path with real parameters. What does each function read, write, and leave behind on failure? Certify safe for dry-run.

**Gate 3 — Dry-run + limited pilot:** Run `--dry-run`, inspect output. Execute on ≤5 items. Verify post-state. Only then authorize full batch.

---

## 8. Critical Known Bugs (Audit j09, Fixed j10)

**Fixed in j10 — confirmed safe:**
- `_resolve_full_hash` now raises on 0-match (previously silently returned wrong path → files moved to wrong location)
- `set_location` now pauses torrent before calling API, checks cross-device before proceeding, resumes after
- `repoint_both_to_pool` now calls qB before RT (fail-fast: if qB fails, RT is untouched)

**Cross-device guard (known refinement needed, j12):**
- `set_location` blocks if qB's current save_path device ≠ target device
- Guard is correct for preventing unwanted copies
- Guard is too conservative when files already exist at target — needs existence check before blocking
- Affects: drift items where qB is on stash but data is already on pool (RT is seeding from pool)

**Rollback fragmentation (known, j11 planned):**
- Every mutation tool fails forward with no complete undo path
- Document: 7 criticals from j09, 42+ open OPs in docs/OPS.md

---

## 9. Active Work State (2026-06-17)

**Open slices:**

| Slice | Items | Status |
|-------|-------|--------|
| 12b | ~2125 `cross-seed/<tracker>/` legacy prefix | ⏳ pending — needs j12 cross-device guard fix first |
| 12c | 3 `cross-seed/<hash>/` items | ⏳ pending |
| Class 4 | 64 `_rehome-unique/<hash>/` staging items | ⏳ under investigation (grew from 10) |
| Class 5 | 15 `_qb-repair*/` staging items | ⏳ needs investigation |
| Drift | 4 items (2 HIGH, 2 LOW) | 🔄 in-progress (blocked on cross-device guard) |

**Drift baseline (2026-06-16):**
- torrent_instances: 5577
- Drift: 4 (high=2, low=2)
- NOVA.S50 (2d4016de) — qB on stash, RT on pool-media, files exist on pool-media
- Magic.City.S01 (f0bc85ee) — same pattern

---

## 10. Safety Rules (Active Every Session)

- `/data/media` and `/stash/media` are the same filesystem — always canonicalize
- Dry-run → limited pilot (≤5 items) → post-check before widening any batch
- One mutating qB/RT workflow at a time
- `~noHL` is advisory only — verify at plan time
- RT is always the path authority — qB follows RT, not the reverse
- Never commit source cleanup before target is verified live in both clients
- Never use `rm -rf` — individual files only, with verification
- Never hardlink across pool boundaries (stash ↔ pool)
- Always run `make client-drift-audit ANCHOR_SCAN=200000` (not default 0) for actionable evidence
- Three-gate validation required before any `--execute` or `--apply` command

---

## 11. Key File Locations

| File | Purpose |
|------|---------|
| `~/.hashall/catalog.db` | SQLite catalog — all file/payload/torrent state |
| `~/.hashall/seed-root-state.json` | Authoritative active seeding roots |
| `docs/REQUIREMENTS.md` | Full system requirements and architecture |
| `docs/RT-QB-STATE-POLICY.md` | Client state policy and repair decision trees |
| `docs/SPRINT.md` | Active sprint slices and evidence baseline |
| `docs/OPS.md` | Live issue tracker (47 open items) |
| `docs/RUNBOOK.md` | Canonical repair procedures |
| `docs/review/R1-R5-*.md` | j09 cold-read audit findings (all 5 tools) |
| `/dev/tools/traktor/config/tracker-registry.yml` | Tracker identity registry |
| `/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/` | qB fastresume files |

---

## 12. qB Fastresume Notes

- QB container: `qbittorrent_vpn`, API: `http://localhost:9003`
- `setLocation` API does NOT fix `qBt-downloadPath` artifact — use delete+readd instead
- Preferred relocation flow: stop → patch fastresume offline → start (not setLocation)
- `qBt-downloadPath` bug (Feb-2026): 2103 torrents went stoppedDL on restart — any torrent mid-download during that incident may still have this artifact
- `/stash` is NOT mounted in qBittorrent container — all stash content appears as `/data/media/...` in qB
