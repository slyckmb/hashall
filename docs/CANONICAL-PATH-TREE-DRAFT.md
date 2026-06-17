# Canonical Path Decision Tree — Draft Spec

**Author:** opencode (deepseek-v4-flash-free)
**Date:** 2026-06-17
**Status:** DRAFT — operator review in progress

---

## Operator Decisions (recorded 2026-06-17)

| Q | Decision |
|---|---|
| Q1 (authorize 2393-item repair?) | **TBD — big picture strategy first.** Goal is ONE move per item combining rehome + path fix. Tree must be finalized before any migration. |
| Q2 (tracker registry extension?) | **No extension needed.** Registry already tracks `prowlarr_display_name`, `tracker_key`, AND `tracker_url_pattern` — use as one-stop source. |
| Conflict 1 (Slice 12b vs §4.4) | **Resolved: §4.4 wins.** Slice 12b "legacy prefix removal" is superseded. 2393 items need prefix RESTORATION, not removal. |
| Conflict 2 (RT authority vs qB metadata) | **Resolved:** qB metadata (category + tags) → input to compute canonical target. RT save_path AND qB save_path → each diffed independently against canonical target. Neither client is assumed correct. The decision tree is the arbiter. "RT wins" only applies after the tree confirms RT is already at canonical. |
| Q7 (~noHL + cross-seed → pool or stash?) | **~noHL is advisory only, never authoritative.** Use as a hint only. Requires independent filesystem verification of ALL sibling payloads + both RT and qB save_paths before any pool rehome is authorized. |
| Q5 (hitchhiker group check in tree or planner?) | **In the planner/verification step.** The tree computes the target per item; the execution tool checks the full inode-sharing group before authorizing any move. |

**Remaining questions resolved:**

| Q | Decision |
|---|---|
| Conflict 3 (~noHL dry-run trust level) | **Two modes:** default dry-run simulates using tag + catalog data (fast). `--full-scan` flag triggers live filesystem hardlink check across all sibling payloads; results saved to disk for offline review and reuse in subsequent runs without rescanning. |
| Q4 (single-file formula) | **Torrent structure is authoritative.** Single-file torrent gets a release-name subdirectory ONLY if the torrent itself defines a folder internally. Bare-file torrent (no folder in torrent) lands at `<root>/<cat>/<filename>` directly — no subdirectory. Spurious folder around a bare-file torrent = RT artifact/bug, classify as NEEDS_REPAIR. |
| Q6 (Class 1 tracker resolution) | **qB is sufficient.** Use qB category + tags to derive the tracker name and build the path. RT announce URL lookup not needed for path derivation (may be used for verification separately). |

**All open questions resolved. Spec is ready for T02 finalization.**

---

---

## 1. Input Data Sources

| Field | Source | Used For |
|---|---|---|
| qB category | qB API / silo-qb cache | Item type classification, ATM category |
| qB save_path | qB API / silo-qb cache | Current save location, cross-seed tracker |
| qB tags | qB API / silo-qb cache | `~noHL` advisory, tracker tag fallback |
| RT path | RT XMLRPC / silo-rt cache | Path authority, current location |
| RT announce URL | RT XMLRPC | Cross-seed tracker resolution (torrent.tracker.url) |
| Catalog payload DB | `~/.hashall/catalog.db` | Payload identity, hardlink count, fs_uuid |
| seed-root-state.json | `~/.hashall/seed-root-state.json` | Active seeding roots, device aliases |
| tracker-registry.yml | traktor config | Tracker key ↔ display name ↔ URL pattern mapping |
| qbit_manage config.yml | qbm config | Tracker-key → category mapping |
| Filesystem (on-demand) | `os.stat()` | Hardlink external-consumer check, file existence |

---

## 2. Decision Tree

### Step 0: Pre-screen — Staging / Non-Canonical Paths

Check RT path for known staging directory patterns. If matched, classify as non-canonical and route to repair — do NOT attempt to resolve canonical path from current path.

```
RT path contains:
│
├─ _rehome-unite (Class 4)
│   → Needs: save-path-repair or manual rehome
│   → Classification: NEEDS_REPAIR
│
├─ _qb-finish / _qb-unique-repair / _qb-repair-v2 (Class 5)
│   → Needs: per-item state investigation, then repoint
│   → Classification: NEEDS_REPAIR
│
├─ cross-seed-link/ (legacy, pre-normalization)
│   → normalize_cross_seed_refactor_path available
│   → Classification: NORMALIZE_PREFIX → re-enter tree
│
└─ none of the above
    → Proceed to Step 1
```

### Step 1: Classify Item Type

Primary classifier is **qB category** (from qB API or silo-qb cache). This is the authoritative
discriminant between the two routing mechanisms (ATM-managed vs explicit save_path).

```
qB category:
│
├─ cross-seed
│   → Type: CROSS_SEED
│   → Routing: Mechanism 2 (explicit save_path)
│   → ATM: OFF
│
├─ sonarr / radarr / lidarr / readarr / speakarr (ARR pre-import categories)
│   → Type: ARR_PRE_IMPORT
│   → Routing: Mechanism 1 (ATM-managed)
│   → ATM: ON
│   → Final category: ARR_CATEGORY_FINAL_MAP (sonarr→tv, radarr→movies, etc.)
│
├─ tv / movies / books / ebooks / audiobooks / music (ARR post-import categories)
│   → Type: ARR_POST_IMPORT
│   → Routing: Mechanism 1 (ATM-managed)
│   → ATM: ON
│   → Category is final
│
├─ [tracker-name] (e.g., abtorrents, theempire, myanonamouse, thegeeks, etc.)
│   → Type: QBM_TRACKER_TAGGED
│   → Routing: Mechanism 1 (ATM-managed)
│   → ATM: ON
│   → Tracking mechanism: qbit_manage assigned this category
│
├─ [other explicit category] (e.g., prowlarr, lazylibrarian)
│   → Type: OTHER_EXPLICIT
│   → Routing: Mechanism 1 (ATM-managed)
│   → Use category name as leaf subdirectory
│
└─ Uncategorized / empty
    → Type: UNCATEGORIZED
    → Fall back to Step 1b (tag-based classification)
```

#### Step 1b: Tag-Based Fallback (uncategorized only)

When qB category is `Uncategorized` or empty:

```
qB tags (filtering out SYSTEM_TAGS):
│
├─ Single tracker tag found
│   → Use tag as category
│   → Type: QBM_TRACKER_TAGGED
│
├─ Multiple tracker tags found
│   → Prefer tag matching known qbit_manage categories
│   → Otherwise first alphabetically
│   → Type: QBM_TRACKER_TAGGED (ambiguous)
│
├─ No tracker tag found
│   → Classification: UNKNOWN
│   → Needs: human review
│
└─ Cross-seed tag present (but category != cross-seed)
    → Treat as CROSS_SEED, use tag-based tracker resolution
```

### Step 2: Determine Seeding Root (WHERE)

The WHERE decision determines which seeding root the item belongs on.

```
External hardlink consumer exists within library paths?
│
├─ YES
│   → Seeding root: STASH (/data/media/torrents/seeding)
│   → Rationale: Moving would break media library hardlinks
│   → Note: Check applies to whole inode-sharing group, not single item
│
└─ NO or unknown (no external consumer found)
    │
    ├─ ~noHL tag present AND no_arr_library_hardlink_anchor_found?
    │   → Seeding root: POOL (/pool/media/torrents/seeding)
    │   → Rationale: Content has no library link, tag confirmed seed-only
    │   → Note: ~noHL is advisory — should re-verify at plan time
    │         (tag reflects past state, not current)
    │
    ├─ Content is CROSS_SEED type?
    │   → Seeding root: POOL (preferred) or STASH
    │   → Default: pool (cross-seed items are seed-only by nature)
    │   → Exception: if cross-seed item has arr library link, stay on stash
    │
    └─ Otherwise
        → Seeding root: STASH (default)
        → Rationale: Default placement for non-flagged content
        → Pool eligibility can be re-evaluated during batch planning
```

#### Placement Constraints

| Class | Preferred Root | Can Go To Pool? | Must Stay On Stash? |
|---|---|---|---|
| ARR_POST_IMPORT | Stash | Only if no library hardlinks | If library hardlinks exist |
| ARR_PRE_IMPORT | Stash | No (pending import) | Yes |
| CROSS_SEED | Pool | Yes (default) | Only if library hardlinks exist |
| QBM_TRACKER_TAGGED | Stash | If ~noHL and no library links | If library hardlinks exist |
| Class 4 (repair target) | Pool (after repair) | Yes (that's the goal) | N/A |

**Current on-disk stakes:** From qB cache (4898 items):
- `~noHL` tagged: 1702 items → pool candidates (pending hardlink re-verify)
- No `~noHL`: 3196 items → stash candidates (or needs investigation)

### Step 3: Determine Category Subdirectory (WHAT PATH)

The WHAT PATH formula determines the seeding-root-relative portion of the canonical path.

#### 3a: CROSS_SEED items

Cross-seed items use Mechanism 2: explicit save_path with `cross-seed/<tracker>/` prefix.

```
How to resolve the tracker name:
│
├─ Current save_path already has cross-seed/<tracker>/ structure
│   → Canonical subdir: cross-seed/<current-tracker>/
│   → Reliability: RELIABLE (path is evidence)
│   → Count: 8 items (correct)
│
├─ Current save_path has bare <tracker>/ (no cross-seed prefix — OP-17 damage)
│   → Canonical subdir: cross-seed/<tracker>/
│   → Status: DAMAGED — needs cross-seed/ prefix restoration
│   → Count: 2393 items
│
├─ Tracker name resolvable from qB tags
│   → Filter out SYSTEM_TAGS + ~-prefixed + rehome_* tags
│   → If one tag remains: use as tracker name
│   → If multiple remain: prefer qbm-category match, else alphabetically
│
├─ Tracker name resolvable from RT announce URL via tracker-registry.yml
│   → Query RT XMLRPC: d.tracker.url(hash)
│   → Match against tracker_url_pattern in registry
│   → tracker_key field is canonical tracker name
│
└─ Tracker cannot be resolved
    → Subdir: cross-seed/<hash>/ (Class 1) or cross-seed/unknown/
    → Needs: human review or registry update
    → Count: 3 items (Class 1, cross-seed/<hash>/)
```

**Canonical formula:** `cross-seed/<prowlarr-display-name>/`

Both short registry key (`darkpeers`) and Prowlarr display name (`Darkpeers (API)`)
are acceptable. Do NOT rename existing display-name paths to short-key form — cross-seed
re-creates the display-name path on the next injection.

**Known aliases:**
| Display Name | Registry Key | Both Canonical? |
|---|---|---|
| MyAnonamouse | myanonamouse | Yes |
| Darkpeers (API) | darkpeers | Yes |
| YUSCENE (API) | yuscene | Yes |
| TorrentLeech | torrentleech | Yes |

#### 3b: ARR items (pre-import and post-import)

ARR items use Mechanism 1: ATM maps category → seeding-root subdirectory.

```
ARR category:
│
├─ Pre-import: sonarr → tv
│                radarr → movies
│                lidarr → music
│                readarr → books (or ebooks?)
│                speakarr → audiobooks
│   → Canonical subdir: <final-category>/
│   → Reliability: TRANSIENT (ATM will change it after import)
│
├─ Post-import: tv / movies / books / ebooks / audiobooks / music
│   → Canonical subdir: <category>/
│   → Reliability: RELIABLE (final ATM state)
│
└─ Note: ATM behavior may change the subdirectory between pre-import and
         post-import. The tree should resolve to the POST-IMPORT form.
         Use ARR_CATEGORY_FINAL_MAP for pre-import categories.
```

#### 3c: QBM_TRACKER_TAGGED items

These have ATM ON with a tracker-name category assigned by qbit_manage.

```
qB category = <tracker-name> (e.g., abtorrents, theempire, myanonamouse)
│
├─ Tracker name matches a key in qbit_manage config.yml
│   → Canonical subdir: <category>/
│   → Reliability: RELIABLE
│
├─ Tracker name has alias in CATEGORY_DIR_ALIASES
│   → Use the canonical alias form (e.g., myanonamouse → MaM — but BOTH are canonical per §4.4.3)
│
└─ Unknown tracker name
    → Subdir: <category>/ (use verbatim)
    → Note: May need verification against tracker-registry.yml
```

#### 3d: OTHER_EXPLICIT items

```
Any explicit category not matching above classifiers:
│
→ Canonical subdir: <category>/
→ Reliability: RELIABLE
→ Examples: prowlarr, lazylibrarian, qigong
```

#### 3e: UNCATEGORIZED / UNKNOWN items

```
qB category = Uncategorized or empty
│
├─ Tag-based resolution succeeded (Step 1b)
│   → Use resolved category as subdir
│
├─ cross-seed tag present (but category mismatch)
│   → Treat as cross-seed, resolve tracker from tags
│   → Canonical subdir: cross-seed/<tracker>/
│
└─ No resolution possible
    → Subdir: UNKNOWN
    → Needs: human review
    → Example: bare hash paths like 0ce22331ff34433e/ (1 item)
```

### Step 4: Assemble Full Canonical Path

```
<seeding-root>/<category-subdir>/<item-payload-name>/
```

Where:
- **seeding-root:** Result from Step 2
- **category-subdir:** Result from Step 3 (including cross-seed/ prefix where applicable)
- **item-payload-name:** RT torrent name (d.name) or qB torrent name

**Path translation rules:**
- Host path: `/data/media/...` = container path (no translation needed)
- Host path: `/stash/media/...` = container `/data/media/...` (bind mount)
- Pool path: `/pool/media/torrents/seeding/...` = no container equivalent (RT direct)

**Single-file torrents:**
`<seeding-root>/<category-subdir>/<filename>` (no item-name subdirectory)

**Multi-file torrents:**
`<seeding-root>/<category-subdir>/<release-name>/` (item-name subdirectory)

### Step 5: Diff vs Actual

Diff BOTH RT save_path and qB save_path independently against the computed canonical path. Neither client is assumed correct. The canonical path from Step 4 is the arbiter.

```
For each client (RT, qB) independently:

client_path matches canonical?
│
├─ YES → client is CANONICAL
│
└─ NO → classify mismatch:
    │
    ├─ Root differs only (same relative path, different seeding root)
    │   → Mismatch type: ROOT_DRIFT
    │   → Action: Rehome (move files if needed, repoint client)
    │
    ├─ Category subdir differs (root correct)
    │   → Mismatch type: CATEGORY_DRIFT
    │   → Action: Rename directory / repoint client
    │   → Examples: cross-seed/ prefix missing (OP-17), wrong tracker name
    │
    ├─ Both root and subdir differ
    │   → Mismatch type: FULL_DRIFT
    │   → Action: Rehome + category repair
    │
    ├─ Staging/non-canonical structure (Class 4/5)
    │   → Mismatch type: STAGING_REPAIR
    │   → Action: save-path-repair or manual repair
    │
    └─ Item name differs (hash in name, etc.)
        → Mismatch type: NAME_DRIFT
        → Needs: human review

Then combine per-client results:

RT=CANONICAL, qB=CANONICAL   → No action
RT=CANONICAL, qB=drift       → Repoint qB to canonical (= RT path)
RT=drift,     qB=CANONICAL   → Repoint RT to canonical (= qB path); investigate RT drift
RT=drift,     qB=drift,      → Move files to canonical; repoint both clients
  same path
RT=drift,     qB=drift,      → Move files to canonical; repoint both clients
  different paths               DO NOT use either client path as move target
```

---

## 3. Scope Estimate (from qB cache, 4898 items)

| Branch | Count | % of Total | Classification |
|---|---|---|---|
| CROSS_SEED — correct path (cross-seed/<tracker>/) | 8 | 0.2% | CANONICAL |
| CROSS_SEED — bare <tracker>/ (OP-17 damaged) | 2393 | 48.9% | NEEDS REPAIR: add cross-seed/ prefix |
| CROSS_SEED — cross-seed/<hash>/ (Class 1) | 3 | 0.1% | NEEDS REPAIR: resolve tracker name |
| ARR_POST_IMPORT (tv, movies, books, music) | ~786 | 16.0% | CANONICAL (assuming correct paths) |
| ARR_PRE_IMPORT (sonarr, radarr, readarr, speakarr) | ~14 | 0.3% | CANONICAL (transient state) |
| QBM_TRACKER_TAGGED (tracker-name categories) | ~1295 | 26.4% | VERIFY (assumed canonical, may need audit) |
| OTHER EXPLICIT (prowlarr, lazylibrarian, qigong) | ~25 | 0.5% | VERIFY (assumed canonical) |
| UNCATEGORIZED with bare hash paths | ~5 | 0.1% | NEEDS HUMAN REVIEW |
| Class 4 (cross-seed/_rehome-unique/) | ~42 | 0.9% | NEEDS REPAIR: rehome from staging |
| Class 5 (_qb-finish, _qb-unique-repair) | ~3 | 0.1% | NEEDS INVESTIGATION |
| Cross-seed → regular category (e.g., cross-seed → movies) | ~32 | 0.7% | INVESTIGATE (mixed routing) |
| UNKNOWN / UNCATEGORIZED | ~292 | 6.0% | NEEDS CLASSIFICATION |

> **Note:** ~noHL distribution: 1702 items (34.8%) have `~noHL` tag → pool candidates
> (pending hardlink re-verify). 3196 items (65.2%) do not have `~noHL`.

---

## 4. Known Conflicts and Ambiguities

### Conflict 1: 12b vs OP-17 — cross-seed/<tracker>/ IS canonical or NOT?

**The conflict:**
- **Slice 12b** frames `cross-seed/<tracker>/` as a "legacy prefix" needing removal
- **OP-17** documents that 2393 items have `cross-seed/` prefix stripped by a bug and need restoration
- **REQUIREMENTS.md §4.4** confirms `cross-seed/<tracker>/` IS canonical

**Resolution needed:** Slice 12b direction is invalid if §4.4 stands. 2393 items need
`cross-seed/` prefix restoration, NOT removal. The operator must formally resolve this
before any cross-seed path mutation.

### Conflict 2: RT path authority vs qB metadata for path inference

**The tension:**
- `REQUIREMENTS.md §8.4` says: RT's path wins in disputes (unless provably wrong)
- `save_path_inference.py` uses qB metadata (category, tags) as primary inference source
- When RT path and qB metadata disagree about the canonical path, which wins?

**Resolution needed:** The decision tree should specify: qB metadata determines what path
*should* be. RT's current path determines what path *is* (authority). If they differ,
RT's path is the reference point, and the tree computes the diff to determine repair
action. Do NOT use RT's path as input to canonical path derivation.

### Conflict 3: ~noHL policy vs plan-time re-verification

**The tension:**
- `REQUIREMENTS.md §4.4.5` uses `~noHL` tag as seeding root selector during inference
- `REQUIREMENTS.md §4.1.1` says `~noHL` is advisory — plan-time external consumer check is authoritative
- 1702 items have `~noHL` but some may have acquired library hardlinks since tagging

**Resolution needed:** The operator must confirm: should the decision tree trust `~noHL`
during dry-run/audit, or require a filesystem scan (expensive but accurate)?

### Conflict 4: ARR pre-import vs post-import category mapping

**The issue:**
- `sonarr → tv` mapping via ARR_CATEGORY_FINAL_MAP is marked "transient" reliability
- At inference time, we don't know if ARR has already imported the item
- Wrong mapping could send an item to the wrong TV path if ARR moved it

**Resolution needed:** Need a runtime check: does the current save_path use pre-import
or post-import subdirectory? Use RT/qB current path as evidence.

---

## 5. Open Questions for Operator

### Q1: Rule for ATM-off cross-seed save_path resolution

When cross-seed injects with ATM OFF, it sets `save_path` explicitly to
`<root>/cross-seed/<prowlarr-name>/<item>/`. But 2393 damaged items have
the `cross-seed/` prefix missing. The repair direction under §4.4 is clear
(restore prefix). **Authorize `cross-seed/` prefix restoration for all damaged
items?** This would be the largest single repair action.

### Q2: What about items with category=cross-seed but save_path at regular category?

32 items have cross-seed category but their save_path falls under tv/, movies/,
or other regular categories. These are routing-ambiguous. **How to classify?**

### Q3: Tracker-registry as source of truth for tracker-name→display-name mapping?

The tracker-registry.yml has `tracker_url_pattern`, `tracker_key`, but not
`prowlarr_display_name`. If cross-seed used a different name than the registry
key, the tree can't verify correctness. **Can the registry be extended with
a `prowlarr_display_name` field?**

### Q4: Single-file vs multi-file formula

§4.4.2 says single-file is `<root>/<cat>/<filename>` and multi-file is
`<root>/<cat>/<release-dir>/`. But some single-file torrents also have a
release-name subdirectory (injected by ARR or cross-seed that way).
**Does the tree enforce the strict formula or accept the subdirectory
structure that the injecting tool created?**

### Q5: Hitchhiker group constraints on placement

If torrent A needs to move to pool but its hitchhiker sibling torrent B has
an external library hardlink, both must stay on stash. **Should the tree
include a hitchhiker group check at the placement level, or leave it to
the planning tool?**

### Q6: cross-seed/hash/ (Class 1) — tracker resolution priority

3 items at `cross-seed/<40-hex-hash>/`. The tracker can be resolved via:
(a) RT announce URL → registry lookup
(b) qB tags
(c) Current save_path inference

**Which is authoritative?** (a) is most reliable but requires live RT.
(b) may be stale or wrong. (c) is obviously wrong for Class 1.
Recommend: (a) with (b) as fallback.

### Q7: What about items with category cross-seed that have ~noHL?

Should they stay on stash (~noHL doesn't force pool) or move to pool
(cross-seed items prefer pool)? **If cross-seed AND ~noHL, which wins?**

---

## Appendix A: Key Source References

| Rule | Document | Section | Lines |
|---|---|---|---|
| Canonical path formula | REQUIREMENTS.md | §4.4.2 | 529–553 |
| Category rules (by origin) | REQUIREMENTS.md | §4.4.3 | 555–588 |
| Path inference precedence | REQUIREMENTS.md | §4.4.5 | 597–644 |
| Placement policy (WHERE) | REQUIREMENTS.md | §4.1.1 | 334–374 |
| Two routing mechanisms | AGENT-MASTERY.md | §3 | 122–137 |
| Migration moratorium | AGENT-MASTERY.md | §3 | 152–168 |
| RT path authority | REQUIREMENTS.md | §8.4 | 1194–1206 |
| Non-canonical classes | SPRINT.md | §slices | — |
| OP-16 / OP-17 damage | OPS.md | OP-16, OP-17 | — |
| OP-18 unified tool | OPS.md | OP-18 | — |
| ARR_CATEGORY_FINAL_MAP | save_path_inference.py | — | 23–29 |
| SYSTEM_TAGS | save_path_inference.py | — | 53–62 |
| ~noHL pool inference | save_path_inference.py | — | 334–336 |
| Class 1–5 definitions | SPRINT.md | table | — |
