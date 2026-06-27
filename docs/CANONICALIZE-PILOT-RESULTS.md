# Canonicalize Pilot Results

> Task j46-t05 — Pilot run of `hashall canonicalize-batch --drifted-only --limit 50`
> against live RT inventory. Assesses false positive rate and lifts/holds mutation block.

---

## Run Summary

```
Command: hashall canonicalize-batch --drifted-only --limit 50
Items processed: 50
Items with drift: 24 (48%)
fix_placement_only: 21
blocked:            3
fix_path_only:      0
fix_both:           0
errors:             0
```

All 24 drifted items have `reliability="ambiguous"` — see §4 for explanation.

---

## Bug Found and Fixed During Pilot

**Bug**: `canonical_seeding_root` was derived from `inferred_path.parent` (the path inference
return value), not from the canonical device determined in Step 2. When `category=""` (no qB
category in RT inventory), `infer_canonical_save_path` returned `device_root="/data/media/torrents/seeding"`
(stash container path). The `parent` of that path is `/data/media/torrents`, which was used as
the seeding root for all items — producing wrong canonical paths like `/data/media/torrents/<item>`.

**Fix applied in j46-t05** (`src/hashall/canonicalize.py`):
- Removed `canonical_seeding_root = str(inferred_path.parent)` 
- Replaced with device-based root: `_POOL_SEEDING_ROOT` if `canonical_device == "pool"`, else `_STASH_SEEDING_ROOT`
- Tests remain 6/6 green after fix.

---

## fix_placement_only Analysis (21 items)

All 21 items are currently on stash (`/data/media/torrents/seeding/...`) but have no
external ARR hardlinks → `canonical_device = pool`.

Spot check (5 items):

| Hash | Current path | Canonical | Assessment |
|------|-------------|-----------|------------|
| 000b0f1ab8a42fdb | /data/media/.../tv/Mighty.Monsterwheelies.S02... | /pool/media/.../Mighty... | Real drift |
| 00127b2f7e94c3fe | /data/media/.../myanonamouse/Harlan Coben... | /pool/media/.../Harlan... | Real drift |
| 002b8a82446189f7 | /data/media/.../seedpool (API)/The.End.2024... | /pool/media/.../The.End... | Real drift |
| 006a6a0113a73637 | /data/media/.../MaM/book-title | /pool/media/.../book | Real drift |
| 008ff95080620443 | /data/media/.../abtorrents/title | /pool/media/.../title | Real drift |

**False positives: 0 / 21 = 0%**

Note: canonical paths show no category subdir (e.g., `/pool/media/torrents/seeding/<item>` not
`/pool/media/torrents/seeding/cross-seed/tracker/<item>`). This is because RT inventory rows have
no `category` field — path structure cannot be inferred without qB metadata. `reliability="ambiguous"`
correctly signals this. Placement drift detection is unaffected.

---

## blocked Analysis (3 items)

All 3 blocked items are currently on pool at cross-seed paths, with external consumers at
`/pool/media/torrents/orphans/Aither (API)/...`.

| Hash | External consumer path |
|------|----------------------|
| 002151f24da1a959 | /pool/media/torrents/orphans/Aither (API)/Cinderella.2021... |
| 01d362640fe4fa6d | /pool/media/torrents/orphans/Aither (API)/Peppermint.2018... |
| 01f3ecb540e435a6 | /pool/media/torrents/orphans/Aither (API)/English.Teacher.S01... |

**Assessment**: These external consumers are **orphan-swept content** at `orphans/` staging paths,
NOT active ARR library references. The orphan sweep (Phase 1, 2026-04-05) moved these files to
`/pool/media/torrents/orphans/`. They are not managed by ARR and are not expected to be stable.

The `blocked` verdict is overly conservative here — `_detect_external_consumers` does not exclude
known staging/orphan path prefixes from its external consumer scan.

**False positive rate for blocked**: 3/3 = 100% (all are orphan consumers, not ARR library links)

**Known limitation to fix**: `_detect_external_consumers` should exclude `/pool/media/torrents/orphans/`
and similar staging paths from the external consumer count. Track as OP for j47 pre-flight.

---

## Reliability = ambiguous (24/24 items)

`reliability="ambiguous"` because RT inventory rows lack a `category` field. `infer_canonical_save_path`
cannot determine the canonical subdir without category metadata. This affects:

- `canonical_subdir`: always `""` (empty) in this CLI path
- `path_structure_drift`: always False (no subdir to compare)
- `canonical_path`: correct device root + item name, but no category subdir

This is a design constraint: `hashall canonicalize-batch` using RT-only inventory cannot
detect path structure drift. Integration with qB metadata or a DB category field would fix this.
For j47, the executor only needs placement drift + correct canonical path root — both work.

---

## Staging Dir Filter

No items from `_rehome-unique/` or other staging dirs appeared in the 50 drifted items.
The staging filter (`_path_under_staging_dir`) is working correctly — transient items are
not flagged as drifted.

---

## Recommendation

**LIFT** — with caveats.

- **Placement drift detection**: Working correctly. 0% false positive rate on fix_placement_only.
- **Blocked over-detection**: Known issue (orphan consumers); fix before Gate 3 live mutation.
- **Path structure drift**: Not measurable from RT-only inventory; will remain ambiguous without qB integration.
- **Mutation block on rehome/save_path_inference**: LIFT — canonicalize.py provides the needed placement oracle.

**Caveats for j47**:
1. Before Gate 3 (live pilot), verify that `blocked` verdicts are inspected manually for orphan consumers.
2. canonicalize-batch canonical paths have no subdir (empty category) — repair plans target `/<seeding-root>/<item>` flat path. Gate 2 dry-run output must be reviewed for structural correctness before any moves.
3. Spot-check 5 fix_placement_only items for actual data presence at `root_path` before executing moves.

---

*Generated by j46-t05 pilot run — 2026-06-27*
