# Unified Tool Exploration: Single-Pass Placement + Path

**Task:** j41-t01
**Date:** 2026-06-26
**Author:** agent (deepseek-v4-flash)
**Status:** complete

---

## 1. Root Cause Analysis

### How Independent Runs Cause Damage

The rehome planner and save_path_inference each solve exactly one dimension of the two-dimensional torrent placement problem. When they operate independently — either sequentially without coordination, or in isolation — each produces incomplete repair actions that can break the other dimension.

**rehome alone** (`src/rehome/planner.py:696` `plan_demotion`):

Steps through external consumer detection (BLOCK if hardlinks exist outside seeding domain), then checks whether pool already has the payload (REUSE) or needs a copy (MOVE). The MOVE target is computed at `planner.py:270` `_compute_pool_move_target`: it takes `source_root_path`, computes the relative path under `stash_seeding_root`, and rebases it onto `pool_payload_root` or `pool_seeding_root`.

**Damage:** rehome only validates the *device* dimension (stash vs. pool). It does not check whether the seeding-root-relative path structure matches the canonical path formula from §4.4.2 of REQUIREMENTS.md. A torrent already at a non-canonical path (e.g., `/stash/media/torrents/seeding/torrentleech/Show` when it should be `cross-seed/TorrentLeech (API)/Show`) gets moved to `/pool/media/torrents/seeding/torrentleech/Show` — preserving the wrong path structure on the target device. The torrent ends up on the correct filesystem but with a broken path, causing stoppedDL because RT/qB cannot find the content at the canonical path.

**save_path_inference alone** (`src/hashall/save_path_inference.py:338` `infer_canonical_save_path`):

Computes the full canonical path from qB metadata: category → leaf subdir, tracker tags for cross-seed provider, device from `~noHL` tag. Produces `InferredSavePath` with `canonical_save_path`, `device`, `subdir`.

**Damage:** save_path_inference determines device placement solely from the `~noHL` tag (save_path_inference.py:367-398). It has no concept of external consumer detection via inode analysis across library roots. A torrent without `~noHL` but whose content genuinely has no ARR hardlinks will be told its canonical path is on stash — when the correct placement is pool. Conversely, a torrent with `~noHL` that was tagged before an ARR import will be told it goes to pool — but it actually has library hardlinks and must stay on stash. The tag is `advisory only` per §4.1.1. Blindly trusting it produces wrong-device plans.

### Combined failure mode

When rehome moves 2k+ items and save_path_inference later computes canonical paths for a different set of ~4k items, each tool's repairs undo or conflict with the other tool's decisions:

1. rehome moves payload to pool at a structurally-wrong path (correct device, wrong subdir structure)
2. save_path_inference computes the correct canonical path but may target the wrong device
3. Some items end up with correct path on wrong filesystem → stoppedDL (path doesn't exist)
4. Other items end up with wrong path on correct filesystem → stoppedDL (same result)
5. Neither tool alone can diagnose the other dimension's error — they have no shared state

---

## 2. Tool Inventory

### rehome planner (`src/rehome/planner.py`)

| Aspect | Details |
|---|---|
| **Key class** | `DemotionPlanner` (line 220), `PromotionPlanner` (line 1137) |
| **Placement logic** | `plan_demotion` (line 696): external consumer detection → BLOCK/REUSE/MOVE |
| **Target path logic** | `_compute_pool_move_target` (line 270): preserve source seed-root-relative path, rebase onto pool root |
| **WHAT it knows** | Seeding roots (stash/pool), device IDs, library roots, hardlink-anchor detection (inode scan across all paths), scan coverage, payload identity (payload_hash, siblings) |
| **WHAT it does NOT know** | Canonical path formula (§4.4.2), category→subdir mapping, ARR_CATEGORY_FINAL_MAP, CATEGORY_DIR_ALIASES, cross-seed provider resolution, tracker registry, system tags vs. tracker tags |
| **External consumer detection** | `_detect_external_consumers` (line 325): queries catalog files tables by inode, checks if any hardlink path is outside seeding domain → authoritative BLOCK gate |
| **Device from path** | `_placement_kind` in `client_drift.py` (line 925): sting pool_roots vs stash_roots prefixes |

### save_path_inference (`src/hashall/save_path_inference.py`)

| Aspect | Details |
|---|---|
| **Key function** | `infer_canonical_save_path` (line 338) |
| **Path logic** | Combines device root + subdir derived from category/tags |
| **WHAT it knows** | APPROVED_SAVE_ROOTS, ARR_CATEGORY_FINAL_MAP, CATEGORY_DIR_ALIASES, SYSTEM_TAGS, tracker registry keys (via `_load_tracker_registry_keys`), staging dirs, cross-seed provider extraction |
| **WHAT it does NOT know** | External consumer presence (no inode scan), library roots, payload identity (hash/siblings), catalog state, scan coverage, REUSE vs MOVE |
| **Device from tags** | `~noHL` tag → pool; absence + cross-seed path hints → dynamic; else stash (lines 367-398) |
| **Category rules** | ARR pre-import (transient), cross-seed (provider from path/tags), qbm config lookup, default to category name |

### Shared gaps (neither tool has)

| Gap | Impact |
|---|---|
| Cross-validation of placement AND path against the canonical spec | Each tool trusts its own output for the dimension it doesn't check |
| Runtime state of the other client (RT vs qB save_path for same hash) | rehome does not validate that qB save_path matches the canonical path after move; save_path_inference does not know the actual RT directory |
| Fastresume state | Neither reads fastresume files to cross-check the current save_path that qB actually uses internally |

---

## 3. Gap Analysis (Split-Brain Mechanics)

### How the split-brain manifests

The two tools share no call site, no intermediate data structure, and no validation gate. The gap is structural:

```
rehome flow:
  payload on stash
  → check external consumers (placement dimension only)
  → compute pool target: relative_path = source - stash_seeding_root
  → target = pool_root / relative_path
  → rsync + repoint
  ✓ correct device
  ✗ relative_path may be structurally wrong

save_path_inference flow:
  qB metadata (category, tags, current save_path)
  → infer category → leaf subdir
  → infer device from ~noHL tag
  → canonical = device_root / subdir
  ✓ correct path structure within selected device
  ✗ device may be wrong (~noHL advisory, no consumer check)
```

### What each tool lacks that the other has

| Required dimension | rehome has it? | save_path_inference has it? |
|---|---|---|
| External consumer detection (authoritative BLOCK gate) | ✅ `_detect_external_consumers` | ❌ |
| Device placement from inode analysis | ✅ `_placement_kind` via catalog | ❌ (only `~noHL` tag) |
| Library roots for ARR hardlink check | ✅ | ❌ |
| Seeding domain definition | ✅ | ✅ (APPROVED_SAVE_ROOTS) |
| Canonical path formula (category → subdir) | ❌ (just preserves relative path) | ✅ |
| Category → media type mapping (ARR_FINAL_MAP) | ❌ | ✅ |
| Cross-seed provider resolution (path + tags + registry) | ❌ | ✅ |
| Category aliases (MaM ↔ myanonamouse) | ❌ | ✅ |
| System tag filtering | ❌ | ✅ |

### Concrete failure examples

1. **Wrong subdir on correct device:** A cross-seed torrent at `/stash/media/torrents/seeding/torrentleech/Show.S01` (stash, flat tracker name) — rehome moves to `/pool/media/torrents/seeding/torrentleech/Show.S01`. But canonical path per §4.4.3 is `cross-seed/TorrentLeech (API)/Show.S01`. RT/qB cannot find content. The `rehome` executor never calls `infer_canonical_save_path` to learn the correct target subdir.

2. **Wrong device with correct subdir:** A torrent without `~noHL` tag but with no actual ARR hardlinks — save_path_inference says device=stash, subdir=tv. The correct placement is pool (no external consumer). If a later repair uses this path, it relocates to `/stash/.../tv/` when it should be `/pool/.../tv/`.

3. **Mutual blind spot:** rehome moves a torrent to pool. Later, save_path_inference runs and says "canonical path is stash/cross-seed/provider/..." because the `~noHL` tag was applied after the move. This triggers a promotion plan that tries to bring it back to stash — undo loop.

---

## 4. Unified Tool Design Sketch

### Name

`hashall canonicalize-torrent` — single entry point for determining the canonical placement + path of any torrent.

### Inputs

```python
@dataclass
class CanonicalizeRequest:
    # qB metadata (from cache snapshot)
    category: str
    tags: str
    save_path: str
    content_path: str
    state: str
    torrent_hash: str

    # RT metadata (from cache snapshot, optional)
    rt_directory: str

    # Catalog context (resolved by the tool)
    payload_id: int | None
    payload_hash: str | None
    device_id: int | None

    # Configuration
    seeding_roots: list[str]
    library_roots: list[str]
    pool_device: int
    stash_device: int
    tracker_registry_path: str | None
    qbm_config_path: str | None
```

### Processing Pipeline

```
Input metadata
  │
  ├─ Step 1: Resolve catalog identity
  │   payload_hash, device_id, sibling info
  │
  ├─ Step 2: Determine canonical device (WHERE)
  │   Use rehome's _detect_external_consumers (authoritative)
  │   Fallback: save_path_inference's ~noHL heuristic
  │   Validation: check consistency with current device path
  │
  ├─ Step 3: Determine canonical subdir (WHAT)
  │   Use save_path_inference's infer_canonical_save_path logic:
  │   - ARR category → final media type
  │   - cross-seed → provider from path/tags/registry
  │   - tracker category → subdir alias check
  │
  ├─ Step 4: Build canonical path
  │   canonical_path = device_seeding_root / subdir / item_name
  │
  ├─ Step 5: Cross-validate
  │   - Does current device match canonical device? If not → drift report
  │   - Does current path structure match canonical path? If not → drift report
  │   - Is REUSE possible (payload already exists on canonical device)?
  │   - Combined verdict: ok | fix_path | fix_placement | fix_both
  │
  └─ Output: CanonicalizeVerdict
```

### Key Decision Points

1. **External consumer check** (authoritative placement): Query catalog files table for inodes shared with library roots. This is the BLOCK gate for demotion. Must happen before any path computation because it determines the seeding root prefix.

2. **Category → subdir resolution** (authoritative path): Use the registry-backed save_path_inference logic. If cross-seed, resolve provider from current path first, then tags, then registry URL matching. Apply ARR_FINAL_MAP and alias lookups.

3. **Validation gate**: After computing canonical path, compare against current save_path on both qB and RT. Generate structured drift dimensions: `placement_drift` and/or `path_structure_drift`. Only emit a fix plan if at least one dimension is wrong.

4. **REUSE detection**: Before planning any data movement, check if the canonical path already exists on the canonical device with matching file count/bytes. This is the existing REUSE logic from `DemotionPlanner`.

5. **Combined repair path**: When BOTH placement and path are wrong, generate a single plan that fixes both at once — move to canonical path on correct device. When only ONE dimension is wrong, generate a targeted repair (repoint only, no data movement).

### Validation Gates

| Gate | Inputs | Output |
|---|---|---|
| G1: Placement consistency | device from external consumers vs. current device | pass | drift: wrong_device |
| G2: Path structure | canonical subdir from category vs. current subdir | pass | drift: wrong_subdir |
| G3: Full path match | canonical_path vs. current paths (both clients) | pass | drift: path_mismatch |
| G4: Payload existence on canonical device | payload_hash × device_id in catalog | reuse_possible | need_move |
| G5: Tag/state preconditions | ~noHL advisory vs. external consumer verdict | consistent | advisory_mismatch |

### Output

```python
@dataclass
class CanonicalizeVerdict:
    canonical_device: Literal["stash", "pool"]
    canonical_path: str
    seeding_root: str
    subdir: str
    item_name: str
    
    # Drift dimensions
    placement_drift: bool          # current device != canonical device
    path_structure_drift: bool     # current subdir != canonical subdir
    full_path_drift: bool          # current path != canonical path
    
    # Feasibility
    reuse_possible: bool           # payload already exists at canonical path?
    move_required: bool            # need byte copy to canonical device?
    
    # Evidence
    external_consumers_found: list[ExternalConsumer]
    inference_notes: list[str]
    reliability: Literal["reliable", "transient", "ambiguous"]
```

---

## 5. Feasibility & Scope

### Verdict: Build as a new module that wires existing functions together

This is primarily a **wiring and validation orchestration** problem, not a new algorithmic challenge. The core capabilities already exist:

- External consumer detection: `rehome.planner.DemotionPlanner._detect_external_consumers`
- Canonical path inference: `save_path_inference.infer_canonical_save_path`
- Device placement from path: `client_drift._placement_kind`
- Payload existence check: `rehome.planner.DemotionPlanner._payload_exists_on_pool`
- View target construction: `rehome.normalize._build_target_view_targets`

**What does NOT exist and must be built:**

1. A unified orchestrator that calls both sets of functions, merges their outputs, and cross-validates
2. A structured drift report that separates placement drift from path structure drift
3. A combined repair plan generator (fix_both, fix_placement_only, fix_path_only)

### Scope Estimate

| Component | Location | Est. lines | Est. files | Complexity |
|---|---|---|---|---|
| Orchestrator module | `src/hashall/canonicalize.py` | 200-350 | 1 new | Medium (wiring) |
| Verdict data model | Same module | 50-80 | — | Low |
| Combined plan generator | Same module | 150-250 | — | Medium |
| CLI entry point | `src/hashall/cli.py` or new click cmd | 30-60 | 1 edit | Low |
| Unit tests | `tests/` | 200-400 | 1-2 new | Medium |
| Integration test harness | — | 100-200 | 1 | Medium |
| **Total** | | **730-1340** | **3-5 new/edited** | **Low-Medium** |

The key algorithmic risk is cross-validating the two dimensions without false positives — e.g., a torrent in `_rehome-unique/<hash>/` is in a staging state, not a path-structure error. The existing `_STAGING_DIRS` filter (save_path_inference.py:196) handles this for path inference; the unified tool must apply the same filter before flagging drift.

---

## 6. Recommendation

### Go: Build unified tool first, block j39 longer

**Rationale:**

The split-brain is structural — the two tools never share a call site and have no cross-validation. Every repair action by one tool that touches the other tool's dimension will produce stoppedDL. With ~4k items in the RT inventory and history showing 2k+ items damaged by rehome alone, running either tool independently risks breaking the other dimension.

**Implementation plan:**

1. Write `src/hashall/canonicalize.py` with the pipeline above (~500 lines)
2. Add CLI: `hashall canonicalize <hash> [--detail]` for single-torrent inspection
3. Add batch mode: `hashall canonicalize-batch [--drifted-only]` to report all drift
4. Emit combined repair plans consumable by `lane1_execute` (for path-only fixes) and `rehome apply` (for placement+path fixes)
5. After the unified tool exists and drift is zeroed, lift the mutation block on both rehome and save_path_inference

**Risk of "proceed with existing tools + better validation gates":**

Better validation gates would help at the edges but don't solve the root problem: the two tools still operate independently on different dimensions. A validation gate in rehome that checks "does the target path match canonical?" just adds a cross-check call to save_path_inference. That cross-check IS the core of the unified tool. Better to build it cleanly as a single orchestrator than to retro-fit cross-references into two tools that were never designed for it.

**Estimated effort:** 3-5 coding sessions (including testing and CLI integration).
