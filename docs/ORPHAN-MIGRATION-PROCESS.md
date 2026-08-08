# Orphan Migration Process Spec

**OP-57, OP-60, OP-61 / j50** — Migrate orphan data from pool to external storage with hardlink guards, cross-device dedupe, and client repointing.

## Current State

| Location | Mount | Size | Used | Free | Content |
|----------|-------|------|------|------|---------|
| Pool orphan dir | `/pool/media` | 7.8T | 7.8T | **0** | `/pool/media/torrents/orphans/` — 3.9T |
| Hotspare | `/mnt/hotspare6tb` | 5.5T | 4.5T | 741G | `/mnt/hotspare6tb/orphan_data/` — 4.5T (rsync inflated) |
| WD6TB (stale) | `/mnt/wd6tb_bad` | 5.5T | 5.4T | 0 | Partial failed rsync, no `-H` flag |

Pool orphans documented in OP-54 (hardlink inflation stopped the WD6TB offload).

## Three-Way Classification

Every file under the orphan dir falls into one of three classes:

| Class | Condition | Pool orphans | Temp copy | Action |
|-------|-----------|-------------|-----------|--------|
| **A — Hardlinked to active seeder** | `inode.device_id` matches a file under a seeding root on the same filesystem. The orphan shares a hardlink with actively-seeding torrent content. | Keep on pool (shared inode, no unique space) | None needed (or delete from temp if inflated copy exists) | Delete from orphan dir. Seeder's hardlink retains the data. No transfer needed. |
| **B — Unique, on temp** | `nlinks=1` or all links within orphan dir. File exists on hotspare with matching size (and optionally SHA256). | Unique owner, wasteful | On hotspare at 4.5T (may be inflated due to `-H`-less rsync) | Delete from orphan dir. Data confirmed on hotspare. |
| **C — Unique, not on temp** | `nlinks=1` or all links within orphan dir. File NOT confirmed on hotspare. | Unique owner, wasteful | Not on hotspare | Rsync to hotspare with `-aH`, then delete from orphan dir. |

## Orchestration Steps

### Step 0: Hardlink-Guard Classification

Run `hashall orphan-validate --hardlink-guard` against the orphan dir (tool built in j49-t01):

```
/pool/media/torrents/orphans/
├── Class A — hardlinked_to_seeder: N files, N bytes
│   └── List of seeder paths sharing each inode
├── Class B — unique_on_temp: N files, N bytes
│   └── Verified against hotspare by path match + size
└── Class C — unique_not_on_temp: N files, N bytes
    └── Requires rsync
```

**Inputs:**
- Orphan dir: `/pool/media/torrents/orphans/`
- Seeding roots: `/pool/media/torrents/seeding/` (same-device inode check)
- Seeding roots: `/data/media/torrents/seeding/` (cross-device — only hardlinks impossible, logged for awareness)
- Temp storage: `/mnt/hotspare6tb/orphan_data/` (size-based match for Class B)

### Step 1: Repoint Active Items Pointing at Orphan Path

Before any deletion, identify any torrent client entries whose `save_path`/`directory` points into the orphan dir.

**RT:** Query `d.directory` for any hash where path starts with `/pool/media/torrents/orphans/`.
**qB:** Query content_path/save_path for the same prefix.

For each hit:
1. Determine the canonical path (use `hashall payload canonical-path --hash <HASH>`)
2. If the data at the orphan path is hardlinked to the canonical path (same inode), just repoint — no data move
3. If the data is unique at the orphan path, rsync from orphan path to canonical path (on stash if library dupe detected, on pool otherwise), then repoint
4. Repoint RT: `d.directory.set` (via `rt_apply_directory_repoint`)
5. Repoint qB: `set_location` + fastresume patch

**Known item:** f37b9983 — `His.Three.Daughters.2024` seeding from orphan path. Verified in earlier scan. Need to check for others.

### Step 2: Delete Class A (Hardlinked to Seeder)

```bash
# For each Class A file:
rm /pool/media/torrents/orphans/<tracker>/_qb-unique-repair/<hash>/<name>/<file>
```

Safe because the seeder retains the data via a separate hardlink under `/pool/media/torrents/seeding/`.

**Edge case — intra-orphan hardlinks:** If a Class A file has nlinks > 1, some of those links may be within the orphan dir (other orphans hardlinked to the same inode). The first `rm` decrements the link count. Only the last `rm` of that inode frees data. Because the seeder also has a hardlink, the data is never lost, but intra-orphan links pointing to a Class A inode become broken. Detect this by scanning orphan dir for all files sharing Class A inodes — delete all orphan links in one pass.

### Step 3: Delete Class B (Unique on Temp, Verified)

```bash
# For each Class B file confirmed on hotspare:
rm /pool/media/torrents/orphans/<path>
```

**Verification method:** Match by relative path from orphan dir root → hotspare orphan_data root. If path exists on hotspare with the same size, consider Class B. To avoid false positives (same size, different content), optionally SHA256 the first + last MB as a spot-check.

**Stale WD6TB:** The WD6TB has 5.4T of the same data (rsync without `-H`, hardlinks inflated). It's full and was the original failed target. Do not rely on it for verification. Use the hotspare as the authoritative temp copy.

### Step 4: Rsync Class C (Unique Not on Temp)

```bash
rsync -aH --info=progress2 \
  --files-from=<class_c_filelist> \
  /pool/media/torrents/orphans/ \
  /mnt/hotspare6tb/orphan_data/
```

`-H` is critical — preserves intra-orphan hardlinks so the temp copy size matches `du` estimate, not the inflated count.

**Capacity check:** Hotspare has 741G free. Sum Class C bytes from Step 0. If Class C exceeds 741G, either:
- Re-check Class B verification (maybe some are on hotspare under a different path)
- Or split into batches: rsync what fits, delete from pool, re-check, repeat

**After rsync:** Verify with `rsync -aH --dry-run --delete --itemize-changes` that source and target are identical for Class C paths.

### Step 5: Second Delete Pass (Class C After Confirmation)

```bash
# After rsync + verification:
rm /pool/media/torrents/orphans/<class_c_path>
```

### Step 6: Clean Up Hotspare Copies of Class A

Class A data was inflated on hotspare (hardlinks expanded by the `-H`-less rsync). After Step 2 deletes Class A from pool orphan dir, the hotspare still has copies that are now redundant (the data stays on pool via seeders).

```bash
# For each Class A path on hotspare:
rm /mnt/hotspare6tb/orphan_data/<class_a_path>
```

This frees space on hotspare for future use.

### Step 7: Verify Pool Free Space

```bash
df -h /pool/media
```

Expected: significant space freed (up to 3.9T minus whatever Class A stays on pool).
Pool should drop below 100%, enabling j42 (Lane 2 strategy) to proceed.

## Client Repointing Detail

### RT Repoint

```python
from hashall.rtorrent import rt_apply_directory_repoint
rt_apply_directory_repoint(
    torrent_hash,
    canonical_save_path,
    rpc_url="http://localhost:18000/RPC2",
    restart=True,
    check_before_start=True,
)
```

`check_before_start=True` prevents leeching (j28 fix — see OP-30).

### qB Repoint

If cross-device (stash→pool or pool→stash): `set_location` fails. Use fastresume patch + container restart.
If same-device: `set_location` works directly.

```python
# Same-device:
qbit.set_location(hash, new_path)
# Then trigger recheck:
qbit.recheck(hash)
```

```python
# Cross-device (fastresume patch):
# 1. Stop qB container
# 2. Read fastresume from BT_backup
# 3. Update save_path
# 4. Write fastresume back
# 5. Start qB container
# 6. Trigger recheck
```

### Repoint Order

Repoint RT first (it's more resilient), then qB. After both repointed, run recheck on both.

## Edge Cases

| Edge case | Detection | Handling |
|-----------|-----------|----------|
| Orphan file nlinks > 1, all links within orphan dir | `stat().st_nlink > 1`, all paths in orphan dir | Class B/C (unique to orphan dir, no external consumer). Rsync with `-aH` preserves intra-orphan hardlinks on temp. |
| Orphan file nlinks > 1, some links in orphan + one in seeding | Inode overlap check | Class A. Delete all orphan links for this inode in one pass. Seeder's link keeps data. |
| qB has a torrent at orphan path but RT does not | `client-drift` audit | If unique orphan: migrate data to canonical path, add to RT, repoint qB. If hardlinked: repoint both to canonical path. |
| RT has a torrent at orphan path but qB does not | `client-drift` audit | Same approach — repoint RT to canonical, mirror to qB if desired. |
| Orphan path matches a known `~noHL` cross-seed item | Tag scan | Canonical path is pool. If library dupe exists, use `repoint_both_to_stash` (j48 tooling) |
| Hotspare out of space during Class C rsync | `df` before rsync | Abort rsync, reclassify remaining orphans, expand storage or run phased delete-then-rsync for future orphans only. |
| Orphan file has SHA256 match in library (stash) but no hardlink | `_Sha256ContentMatcher` (j48 t02) | Class B — library has the content. Delete from orphan dir. No need to keep on pool. |

## Pre-Deletion Evidence Checklist

Before any live deletion of orphan files, every candidate must satisfy this
checklist.  Each item requires explicit evidence captured before mutation.  Run
`hashall payload classify-orphan-dedup` as a pre-flight dry-run gate first.

| # | Check | Evidence Required | How to Verify |
|---|-------|-------------------|---------------|
| **E1** | **Path** | Absolute source path on origin device and absolute match path(s) on target device(s) confirmed | `stat <path>` on source; cross-reference against classify-orphan-dedup match_paths |
| **E2** | **Size** | File size in bytes matches across devices within classification group | `stat --format=%s` on source and each target; must be bit-identical |
| **E3** | **Hash basis** | SHA256 confirmed for all Class A / Class B candidates; quick-hash-only candidates must complete `hashall payload upgrade-collisions` before eligibility | Classification output shows `sha256_confirmed`; quick-hash-only candidates blocked until SHA256 upgrade |
| **E4** | **Link count** | `st_nlink` confirmed ≤ 2 if hardlinked to seeder (Class A), or = 1 if fully unique (Class B/C); intra-orphan hardlinks enumerated | `stat --format=%h` per file; `hashall orphan-validate --hardlink-guard` for batch |
| **E5** | **Device** | Source device alias + target device alias(s) recorded; cross-device `fs_uuid` verified distinct (prevents same-device false positives) | `df` on source/target mount points; `hashall device list` for catalog mapping |
| **E6** | **Active-client exclusion** | Zero RT `/data/media/...` or qB `save_path` entries point at orphan root path; orphan-audit confirms zero `torrent_instances` refs | `hashall payload orphan-audit --path-prefix <orphan_root>` shows `true orphans (eligible class)`; RT/qB state query confirms no active references |
| **E7** | **Rollback posture** | Hotspare copy confirmed for all Class B/C files before source deletion; restore procedure tested with a small pilot | Class B: `rsync --dry-run --itemize-changes` shows target identical to source. Class C: rsync completed and verified. Rollback: `rsync -aH` from hotspare back to orphan dir |
| **E8** | **Backup posture** | Pre-deletion snapshot captured: output of `hashall payload classify-orphan-dedup --json` + `hashall payload orphan-audit --json` saved to `~/.logs/hashall/orphan-dedup/<run_id>/` | Both JSON outputs saved to timestamped run directory; rsync verify between source and hotspare captured |

### Wet-Run Approval Gates

After the dry-run classification passes and all E1–E8 evidence is collected,
the operator must explicitly approve each phase before live deletion:

1. **Phase 0 — Dry-run approval**: Review classify-orphan-dedup output; confirm
   SHA256-confirmed group sizes are expected before any mutation.
2. **Phase 1 — Pilot deletion (1–3 files)**: Delete 1–3 SHA256-confirmed files;
   verify pool free space; verify hotspare still holds copies; verify no client
   impact.
3. **Phase 2 — Batch deletion (≤50 files per batch)**: Delete in small batches;
   re-run classify-orphan-dedup after each batch to confirm no drift.
4. **Phase 3 — Quick-hash upgrade + reclassify**: For quick-hash-only candidates,
   run `hashall payload upgrade-collisions` then re-run classify-orphan-dedup to
   promote them to SHA256-confirmed before deletion eligibility.

No batch proceeds to the next phase without explicit operator sign-off.

## Verification Gates

Between every step, verify:
1. No client points at orphan path after Step 1
2. Class A deletions don't break any seeder (verify seeder still has complete=1)
3. Step 3/5 deletions are recoverable from hotspare (or from seeders for Class A)
4. After all steps: pool has free space, hotspare has all unique orphans, no client references orphan paths
