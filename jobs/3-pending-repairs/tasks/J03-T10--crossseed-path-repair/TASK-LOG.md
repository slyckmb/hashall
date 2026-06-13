# J03-T10 — Cross-Seed Path Repair — TASK LOG

## Summary

| Item | Outcome |
|------|---------|
| Greenland (seedpool) `4e4a7bc1...` | ✅ **ok** — repaired, seeding |
| Greenland (darkpeers) `e3f92c1c...` | ✅ **ok** — repaired, seeding |
| Greenland (reelflix) `73d05a65...` | ✅ **ok** — repaired, seeding |
| How.Its.Made.S22 `145548eb...` | ✅ **ok** — repaired, seeding |

All 4 items: **100% complete, hash-checked, actively seeding.**

---

## Per-Item Artifacts

### GROUP A — Greenland (seedpool)

```
hash=4e4a7bc1f4284da8b20ce3663b5be1847664f61c
name=Greenland (seedpool)
file_found=yes
file_found_at=/data/media/torrents/seeding/cross-seed/seedpool (API)/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
file_nlinks=10 (pre-repair) → 13 (post-repair, shared across /data/media + /stash/media)
canonical_path=/data/media/torrents/seeding/seedpool/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
hardlink_created=yes
empty_dir_removed=yes (rmdir on YUSCENE (API) artifact dir)
rt_repointed=yes
rt_repoint_path=/data/media/torrents/seeding/seedpool
recheck_issued=yes
post_recheck_state=1 (started, active=1, checked=1, pct=100%)
outcome=ok
```

### GROUP A — Greenland (darkpeers)

```
hash=e3f92c1c1d8dcde7042f0f849d15d13c1a480d2a
name=Greenland (darkpeers)
file_found=yes (same inode as seedpool copy)
file_found_at=/data/media/torrents/seeding/cross-seed/seedpool (API)/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
file_nlinks=10 (pre) → 13 (post)
canonical_path=/data/media/torrents/seeding/darkpeers/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
hardlink_created=yes
empty_dir_removed=N/A (same artifact handled in seedpool entry — single rmdir)
rt_repointed=yes
rt_repoint_path=/data/media/torrents/seeding/darkpeers
recheck_issued=yes
post_recheck_state=1 (started, active=1, checked=1, pct=100%)
outcome=ok
```

### GROUP A — Greenland (reelflix)

```
hash=73d05a65527a9044f924b0b119810fbf46ff3081
name=Greenland (reelflix)
file_found=yes (same inode as seedpool copy)
file_found_at=/data/media/torrents/seeding/cross-seed/seedpool (API)/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
file_nlinks=10 (pre) → 13 (post)
canonical_path=/data/media/torrents/seeding/reelflix/Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
hardlink_created=yes
empty_dir_removed=N/A
rt_repointed=yes
rt_repoint_path=/data/media/torrents/seeding/reelflix
recheck_issued=yes
post_recheck_state=1 (started, active=1, checked=1, pct=100%)
outcome=ok
```

### GROUP B — How.Its.Made.S22

```
hash=145548eb360d03ffa6343f56ee94ba8ca7ea8f1c
name=How.Its.Made.S22 (TorrentDay)
file_found=yes
file_found_at=/data/media/torrents/6e52f92827a42df9/How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG/
file_nlinks=28 (source, shared hash-named copies) → 30 (post-repair)
canonical_path=/data/media/torrents/seeding/TorrentDay/How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG/
hardlink_created=yes (26 files, 13 unique inodes)
empty_dir_removed=N/A (no empty dir artifact — partial FILES replaced)
rt_repointed=yes (already at canonical path, re-verified)
recheck_issued=yes
post_recheck_state=1 (started, active=1, checked=1, pct=100%)
outcome=ok
```

---

## Actions Performed

| # | Action | Detail |
|---|--------|--------|
| 1 | Located Greenland 37GB file | Found at `/data/media/torrents/seeding/cross-seed/seedpool (API)/...` with nlinks=10 on device 49 (`stash/media` filesystem). Also found on `/pool/media` but separate inode (device 45, nlinks=5). |
| 2 | Located How.Its.Made.S22 source | Found at `/data/media/torrents/6e52f92827a42df9/How.Its.Made.S22.../` with nlinks=28. Also linked at `/data/media/torrents/7b75bba8bea11720/...` (same inodes). |
| 3 | Created canonical dirs | `seedpool/`, `darkpeers/`, `reelflix/` under `/data/media/torrents/seeding/` |
| 4 | Hardlinked Greenland x3 | `ln` from source to each canonical path. nlinks: 10→13 |
| 5 | Removed empty subdir | `rmdir` on `/data/media/torrents/seeding/YUSCENE (API)/Greenland...mkv` (was a dir, not file) |
| 6 | Repointed RT x3 | `d.directory.set` for each Greenland hash to canonical tracker path |
| 7 | Issued recheck x3 | `d.check_hash` for each Greenland hash |
| 8 | Started Greenland x3 | `d.start` to trigger hash checking (stopped torrents don't hash) |
| 9 | Replaced S22 partial data | Removed 26 partial download files (nlinks=1), hardlinked 26 files from source (nlinks 28→30) |
| 10 | Rechecked S22 | `d.check_hash` — passed at 100% |
| 11 | Started S22 | `d.start` — now active+seeding |
| 12 | Verified all | All 4 torrents: state=1, active=1, checked=1, pct=100% |

## Constraints Compliance

- ✅ No `rm -rf` used (only `rm` on individual partial files, `rmdir` on empty dir)
- ✅ No `mv` or `cp` used (only `ln` for hardlinks)
- ✅ Only listed items modified
- ✅ RT XMLRPC reachable throughout
- ✅ Empty subdirs removed with `rmdir` (not `rm`)

## Source Data Details

### Greenland — All paths with the same inode (device 49, inode 69092):
- `/data/media/torrents/seeding/cross-seed/seedpool (API)/...` nlinks=10
- `/data/media/torrents/seeding/cross-seed/YUSCENE (API)/...` nlinks=10
- `/data/media/torrents/seeding/cross-seed/OnlyEncodes (API)/...` nlinks=10
- `/data/media/torrents/seeding/_movie/...` nlinks=10
- `/data/media/torrents/seeding/movies/...` nlinks=10
- `/data/media/torrents/seeding/hawke-uno/...` nlinks=10
- `/data/media/torrents/seeding/YOiNKED (API)/...` nlinks=10
- `/data/media/torrents/4e4a7bc1f4284da8/...` nlinks=10
- `/data/media/torrents/e3f92c1c1d8dcde7/...` nlinks=10
- Corresponding copies on `/stash/media/...` (same filesystem via bind mount)
- `/pool/media/...` copies are on a different device (45) with nlinks=5

### How.Its.Made.S22 — Source inodes (13 unique episodes, each hardlinked to 2 names):
- Found at `/data/media/torrents/6e52f92827a42df9/How.Its.Made.S22.../` nlinks=28
- Same inodes at `/data/media/torrents/7b75bba8bea11720/How.Its.Made.S22.../`
- 26 file entries (13 episodes × 2 names each)
- All episodes complete, previously downloaded via ARR

## Timestamps
- Start: 2026-06-12 ~22:09 UTC
- Investigations complete: ~22:11 UTC
- Hardlinks created: ~22:12 UTC
- Repoints + rechecks: ~22:12-22:15 UTC
- All verified seeding: ~22:17 UTC
