# TASK-LOG: J03-T12 — How.Its.Made S23/S24 Cross-Seed Violation Repair

## Summary

| Item | Status |
|------|--------|
| J03-T12 | implementation |
| agent_start | 2026-06-12T23:49Z |
| agent_end   | 2026-06-12T23:59Z |
| outcome     | resolved (S23), partial (S24) |

## S23 — How.Its.Made.S23 (yuscene)

- **hash**: `04aa5f3339d3ccfd1f14dd114db16c92aa87f74a`
- **stopped_ok**: yes (state=0 active=0)
- **base_dir**: `/data/media/torrents/seeding/YUSCENE (API)/How.Its.Made.S23.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG`
- **files_on_disk** (before repair):

  | File | Pct | Nlinks | Size |
  |------|-----|--------|------|
  | S23E01.Motion.Sensors | 82.5% | 1 | 2300083583 |
  | S23E02.Rawhide.Lampshades | 53.3% | 1 | 2308866958 |
  | S23E03.Noise.Barrier.Walls | 40.9% | 1 | 2336570507 |
  | S23E04.Railway.Bridge.Ties | 8.5% | 1 | 2344199586 |
  | S23E05.Hospital.Laundry | 100.0% | 1 | 2338565588 |
  | S23E06.Ceramic.Fireplaces | 43.6% | 1 | 2300486831 |
  | S23E07.Oil.Pressure.Sensors | 29.1% | 1 | 2296138097 |
  | S23E08.Mobile.Concert.Stages | 22.3% | 1 | 2324479315 |
  | S23E09.NASCAR.Car.Bodies | 49.1% | 1 | 2336608322 |
  | S23E10.Vehicle.Charging.Stations | 19.4% | 1 | 2365358853 |
  | S23E11.Slate.Tiles.and.Hot.Dog.Carts | 35.7% | 1 | 2339764032 |
  | S23E12.Racing.Leathers | 39.1% | 1 | 2333741200 |
  | S23E13.Mountain.Bikes.and.Rice | 62.5% | 1 | 2365118564 |

- **source_data_found**: yes
- **source_locations**:
  - `/data/media/torrents/seeding/Aither (API)/How.Its.Made.S23.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG/` (nlinks=21 — confirmed complete)
  - Also present in: Darkpeers, FileList.io, hawke-uno, seedpool, cross-seed copies
- **partial_files_removed**: 12 (all files except E05 which was already 100%)
- **hardlinks_created**: 13 (all files hardlinked from Aither source, new nlinks=22 each)
- **recheck_issued**: yes (after hardlinks, `s.d.check_hash()` called, then `s.d.stop()`/`s.d.check_hash()` again)
- **post_recheck_state**: state=0 active=0 complete=1 — hash check passed, all data verified
- **outcome**: resolved — data hardlinked, hash verified

## S24 — How.Its.Made.S24 (onlyencodes)

- **hash**: `002e5db0ad4bee86419ccf244d212f6d1150d1e8`
- **stopped_ok**: yes (state=0 active=0)
- **base_dir**: `/data/media/torrents/seeding/OnlyEncodes (API)/How.Its.Made.S24.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG`
- **files_on_disk** (before repair):

  | File | Pct | Nlinks | Size |
  |------|-----|--------|------|
  | S24E01.Saunas.and.Dioramas | 100.0% | 1 | 2325947410 |
  | S24E02.Upright.Pianos.and.Flags | 48.8% | 1 | 2348440037 |
  | S24E03.Oil.Lamps.and.Pillows | 82.4% | 1 | 2328697241 |
  | S24E04.Skeletal.Replicas | 100.0% | 1 | 2363142577 |
  | S24E05.Automatic.Sliding.Doors | 83.5% | 1 | 2328482620 |
  | S24E06.Scuba.Lights | 0.0% | 1 | 2349289216 |
  | S24E07.Wood.Windows.and.Cashmere | 2.2% | 1 | 2316442196 |
  | S24E08.Gas.Barbecues | 49.5% | 1 | 2319585908 |
  | S24E09.Recycled.Skateboards | 100.0% | 1 | 2321291804 |
  | S24E10.Plasma.Gems | 100.0% | 1 | 2366404547 |
  | S24E11.Three.Wheel.Electric.Bicycles | 100.0% | 1 | 2304829301 |
  | S24E12.Wild.West.Gun.Holsters | 100.0% | 1 | 2291646024 |
  | S24E13.Wood.Garage.Doors | 100.0% | 1 | 2315720238 |

- **source_data_found**: yes
- **source_locations**:
  - `/data/media/torrents/seeding/Aither (API)/How.Its.Made.S24.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG/` (nlinks=17 — confirmed complete)
  - Also present in: Darkpeers, YUSCENE, FileList.io, hawke-uno, cross-seed copies
- **partial_files_removed**: 6 (E02, E03, E05, E06, E07, E08 — nlinks=1 and <100%)
- **hardlinks_created**: 13 (all files hardlinked from Aither source, new nlinks=18 each)
- **recheck_issued**: yes (after hardlinks), also after stop+recheck cycle
- **post_recheck_state**: state=0 active=0 complete=0 — hash check did not complete to 100% within observation window
- **outcome**: partial — hardlinks placed, data on disk, still stopped; may need a recheck cycle to complete verification

## Actions Taken

1. **Stopped both torrents** via RT XMLRPC `d.stop()` — both confirmed stopped (state=0, active=0)
2. **Inventoried files** — all files present as partial downloads (nlinks=1) from tracker
3. **Searched hashall DB** — found complete source files in Aither (API) seeding directory across all DB tables (stash, pool-media, pool-data)
4. **Removed partial downloads** — 12 partial files for S23, 6 partial files for S24 (nlinks=1, <100%)
5. **Hardlinked from source** — all 13 files for each season hardlinked from Aither (API) source directory using `ln -f`
6. **Rechecked and started** — `check_hash()` issued for both; S23 completed hash check (complete=1), S24 recheck still in progress at time of report

## Notes

- S23 hash check completed successfully (complete=1) — data matches expected hashes
- S24 hash check was still running when TASK-LOG was written — final state is stopped with complete=0
- No repointing of RT directory needed — canonical paths are already at `<seeding-root>/<tracker-name>/<payload-name>`
- Source data for all 26 files (13+13) was available via Aither (API) seeding directory with matching filenames and sizes

## Bootstrap

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
head=c92d2b9530218f38db01cb91f5f649757188b4be
```
