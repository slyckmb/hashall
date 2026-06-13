---
id: J03-T06
job: 3-pending-repairs
slug: rt-health-investigation
task_type: discovery
status: done
brief_revision_id: 1
created_by: lead
agent_start_timestamp: 2026-06-12T16:37:00Z
completed_at: 2026-06-12T17:00:00Z
brief_freeze_violation: "false"
---

# TASK-LOG: J03-T06 — RT Health Investigation

## Summary

```
🟪 task-log=J03-T06_rt-health-investigation 🟪

status="done"
task_id="J03-T06"
task_type="discovery"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="All 18 RT DL items enumerated; 2 qB bad-state items found; 18 tracker issues enumerated; disk checks and XMLRPC seeds queries completed."
artifacts="full per-item data below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none"
next="future TBD by lead after current task log"

rt_dl_count=18
qb_bad_state_count=2
tracker_issue_count=18
```

## Data Sources

- RT cache: `/home/michael/.cache/silo-rt/torrents.json` (4889 items; fresh)
- qB cache: `/home/michael/.cache/silo-qb/torrents-info.json` (4889 items; fresh)
- RT XMLRPC: `http://127.0.0.1:18000/` (reachable)
- Disk checks: direct stat/ls on every RT DL item's directory

## Findings Overview

### RT State Distribution (all 4889)
| State | Count |
|---|---|
| stalledUP | 4867 |
| stoppedDL | 8 |
| stalledDL | 6 |
| pausedDL | 3 |
| stoppedUP | 3 |
| uploading | 1 |
| downloading | 1 |

### qB State Distribution (all 4889)
| State | Count |
|---|---|
| stoppedUP | 4853 |
| stoppedDL | 34 |
| stalledUP | 2 |

### RT Tracker Issue Breakdown
| Type | Count | Notes |
|---|---|---|
| deleted | 11 | "Torrent has been deleted." — all aither.cc torrents (Euphoria S03, War.Machine, Killers.Flower.Moon) |
| auth_err | 4 | "InfoHash not found." — onlyencodes torrents (SNL episodes) |
| other | 3 | "Passkey not found" (1: nebulance), "unregistered torrent" (2: torrentleech, filelist) |

---

## SECTION 1: RT DL ITEMS

### Item 1: Hunter's Code Book 4
```
hash=6b6043cacaada917da6d05cc551765f4530ca55a
name=Hunter's Code Book 4
state=stoppedDL
progress=0.0
size_bytes=550477747
directory=/data/media/torrents/seeding/abtorrents/Hunter's Code Book 4
label=cross-seed
tracker_url=https://t.myanonamouse.net/tracker.php/WJBHd0g3jx4QLYLR6Kk7cfg3c6DY4bCc/announce
is_cross_seed=yes
data_on_disk=no
file_count=0
nlinks_sample=0
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/abtorrents
seeds_available=0
```

### Item 2: River Monsters S07
```
hash=127c38342cfedaf4016b8079be13c5f7883b9cfe
name=River Monsters S07 1080p AMZN WEB-DL DDP2 0 H 264-NTb
state=stalledDL
progress=0.9992
size_bytes=21950408183
directory=/data/media/torrents/seeding/TorrentDay/River Monsters S07 1080p AMZN WEB-DL DDP2 0 H 264-NTb
label=torrentday
tracker_url=http://td.jumbohostpro.eu/tNtOztQuQIzYElZyDuuJIeLJW8chntAH/announce
is_cross_seed=no
data_on_disk=yes
file_count=7
nlinks_sample=12
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/TorrentDay
seeds_available=0
```

### Item 3: How.Its.Made.S23 (cross-seed)
```
hash=04aa5f3339d3ccfd1f14dd114db16c92aa87f74a
name=How.Its.Made.S23.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
state=pausedDL
progress=0.0
size_bytes=30289981436
directory=/data/media/torrents/seeding/YUSCENE (API)/How.Its.Made.S23.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
label=cross-seed
tracker_url=https://yu-scene.net/announce/69d0c9ad5859ca8e6009041bac73875e
is_cross_seed=yes
data_on_disk=yes
file_count=13
nlinks_sample=1
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/YUSCENE (API)
seeds_available=0
```

### Item 4: Greenland.2020 (cross-seed, seedpool)
```
hash=4e4a7bc1f4284da8b20ce3663b5be1847664f61c
name=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
state=stoppedDL
progress=0.0
size_bytes=36697229052
directory=/data/media/torrents/seeding/YUSCENE (API)
label=cross-seed
tracker_url=https://seedpool.org/announce/2bd51ec86605394ea51e48bf7fd9b9a9
is_cross_seed=yes
data_on_disk=yes
file_count=115
nlinks_sample=5
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/YUSCENE (API)
seeds_available=0
```

### Item 5: NOVA.S50 (cross-seed, pool)
```
hash=2d4016de430ff7348872a5f328245a667b3f3360
name=NOVA.S50.1080p.x265-ELiTE
state=stalledDL
progress=0.0
size_bytes=17969434946
directory=/pool/media/torrents/seeding/DigitalCore (API)/NOVA.S50.1080p.x265-ELiTE
label=cross-seed
tracker_url=http://speed.connecting.center/2a4d44c77caed5aefd385fcb31fd7662/announce
is_cross_seed=yes
data_on_disk=yes
file_count=19
nlinks_sample=1
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/DigitalCore (API)
seeds_available=0
```

### Item 6: Greenland.2020 (cross-seed, darkpeers)
```
hash=e3f92c1c1d8dcde7042f0f849d15d13c1a480d2a
name=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
state=stoppedDL
progress=0.0
size_bytes=36697229052
directory=/data/media/torrents/seeding/YUSCENE (API)
label=cross-seed
tracker_url=https://darkpeers.org/announce/72525a46b98b9e30813865496505276f
is_cross_seed=yes
data_on_disk=yes
file_count=115
nlinks_sample=5
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/YUSCENE (API)
seeds_available=0
```

### Item 7: How.Its.Made.S24 (cross-seed)
```
hash=002e5db0ad4bee86419ccf244d212f6d1150d1e8
name=How.Its.Made.S24.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
state=pausedDL
progress=0.0
size_bytes=30279919119
directory=/data/media/torrents/seeding/OnlyEncodes (API)/How.Its.Made.S24.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
label=cross-seed
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
is_cross_seed=yes
data_on_disk=yes
file_count=13
nlinks_sample=1
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/OnlyEncodes (API)
seeds_available=0
```

### Item 8: How.Its.Made.S22 (cross-seed, actively DOWNLOADING)
```
hash=145548eb360d03ffa6343f56ee94ba8ca7ea8f1c
name=How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
state=downloading
progress=0.4589
size_bytes=30128043857
directory=/data/media/torrents/seeding/TorrentDay/How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
label=cross-seed
tracker_url=http://td.jumbohostpro.eu/tNtOztQuQIzYElZyDuuJIeLJW8chntAH/announce
is_cross_seed=yes
data_on_disk=yes
file_count=26
nlinks_sample=1
qb_state=stoppedUP
qb_save_path=/data/media/torrents/seeding/TorrentDay
seeds_available=0
```
**NOTE**: Cross-seed item actively downloading (45% progress). Hardlink source likely missing/moved. qB has it as stoppedUP.

### Item 9: The.Muppet.Christmas.Carol (rehome-unique)
```
hash=8e438130b072708877003225a5079040991de5d7
name=The.Muppet.Christmas.Carol.1992.BluRay.1080p.DTS-HD.MA.5.1.AVC.REMUX-FraMeSToR.mkv
state=stoppedDL
progress=0.0
size_bytes=26828733784
directory=/pool/media/torrents/seeding/_rehome-unique/8e438130b0727088
label=-
tracker_url=https://reelflix.cc/announce/8ff49516be2032a2016e04ca9a1dc2bb
is_cross_seed=no
data_on_disk=yes_dir_empty
file_count=0
nlinks_sample=0
qb_state=stoppedDL
qb_save_path=/pool/media/torrents/seeding/_rehome-unique/8e438130b0727088
seeds_available=0
```

### Item 10: Dexter.S02 (stalledDL 99%)
```
hash=245f2bce6afaf96b0a48ad216366c4281fdd864f
name=Dexter.S02.720p.x265-ZMNT
state=stalledDL
progress=0.9997
size_bytes=8339890797
directory=/data/media/torrents/seeding/TorrentLeech/Dexter.S02.720p.x265-ZMNT
label=speedcc
tracker_url=http://speed.connecting.center/2a4d44c77caed5aefd385fcb31fd7662/announce
is_cross_seed=no
data_on_disk=yes
file_count=13
nlinks_sample=3
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/TorrentLeech
seeds_available=0
```

### Item 11: Dexter.S07 (stalledDL 99%, pool)
```
hash=e36553b12dc118d8c52575a1d6711532882ae1c3
name=Dexter.S07.720p.x265-ZMNT
state=stalledDL
progress=0.9996
size_bytes=5757836898
directory=/pool/media/torrents/seeding/speedcd/Dexter.S07.720p.x265-ZMNT
label=speedcc
tracker_url=http://speed.connecting.center/2a4d44c77caed5aefd385fcb31fd7662/announce
is_cross_seed=no
data_on_disk=yes
file_count=13
nlinks_sample=1
qb_state=stoppedDL
qb_save_path=/pool/media/torrents/seeding/speedcd
seeds_available=0
```

### Item 12: The.Conjuring (cross-seed)
```
hash=282ec595d866745c115d5a418c028a2bb939f603
name=The.Conjuring.2013.1080p.Blu-Ray.ReMuX.AVC.DTS-HDMA.5.1-R2D2.mkv
state=stoppedDL
progress=0.0
size_bytes=23787379307
directory=/data/media/torrents/seeding/movies/The.Conjuring.2013.1080p.Blu-Ray.ReMuX.AVC.DTS-HDMA.5.1-R2D2
label=cross-seed
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
is_cross_seed=yes
data_on_disk=no
file_count=0
nlinks_sample=0
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/movies/The.Conjuring.2013.1080p.Blu-Ray.ReMuX.AVC.DTS-HDMA.5.1-R2D2
seeds_available=0
```

### Item 13: Greenland.2020 (movies, reelflix)
```
hash=73d05a65527a9044f924b0b119810fbf46ff3081
name=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
state=stoppedDL
progress=0.0
size_bytes=36697229052
directory=/data/media/torrents/seeding/YUSCENE (API)
label=movies
tracker_url=https://reelflix.xyz/announce/8ff49516be2032a2016e04ca9a1dc2bb
is_cross_seed=no
data_on_disk=yes
file_count=115
nlinks_sample=5
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/YUSCENE (API)
seeds_available=0
```

### Item 14: Transformers.Rise.Beasts (stalledDL 99%)
```
hash=96d896ca35f42d93e4a4bdee92e8ac90adc34b54
name=Transformers.Rise.of.the.Beasts.2023.1080p.BluRay.x265.10bit.TrueHD.7.1.Atmos-TORRENTLEECHENC0DE
state=stalledDL
progress=0.9999
size_bytes=21082531706
directory=/data/media/torrents/seeding/DigitalCore (API)/Transformers.Rise.of.the.Beasts.2023.1080p.BluRay.x265.10bit.TrueHD.7.1.Atmos-TORRENTLEECHENC0DE
label=digitalcore
tracker_url=https://tracker.digitalcore.club/announce/11267cfb9ba7a8d52c1fb1107b19b5ba
is_cross_seed=no
data_on_disk=yes
file_count=3
nlinks_sample=4
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/DigitalCore (API)
seeds_available=0
```

### Item 15: Magic.City.S01 (pausedDL)
```
hash=f0bc85eedb5050da831a3c54a509d8f90a1fac2f
name=Magic.City.S01.1080p.BluRay.REMUX.AVC.TrueHD.5.1-PrivateHD
state=pausedDL
progress=0.0
size_bytes=106474639951
directory=/pool/media/torrents/seeding/other/Magic.City.S01.1080p.BluRay.REMUX.AVC.TrueHD.5.1-PrivateHD
label=yuscene
tracker_url=https://yu-scene.net/announce/69d0c9ad5859ca8e6009041bac73875e
is_cross_seed=no
data_on_disk=no
file_count=0
nlinks_sample=0
qb_state=stoppedUP
qb_save_path=/data/media/torrents/seeding/other
seeds_available=0
```

### Item 16: The.Diary.of.a.Teenage.Girl (stalledDL 98%)
```
hash=5caca88d29e64de495a47b53a466f7cadcb3ce02
name=The.Diary.of.a.Teenage.Girl.2015.REMUX.1080p.BluRay.AVC.DTS-HD.MA.5.1-CDB
state=stalledDL
progress=0.9842
size_bytes=24547253912
directory=/data/media/torrents/seeding/TorrentLeech/The.Diary.of.a.Teenage.Girl.2015.REMUX.1080p.BluRay.AVC.DTS-HD.MA.5.1-CDB
label=torrentleech
tracker_url=https://tracker.tleechreload.org/a/fa267c9efcdf6a63090fa087a6de40ed/announce
is_cross_seed=no
data_on_disk=yes
file_count=7
nlinks_sample=3
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/TorrentLeech
seeds_available=0
```

### Item 17: Smart Brevity (stoppedDL)
```
hash=815e28c8cce2ef07ace15529485442046f39fffa
name=Jim VandeHei and Mike Allen Roy Schwartz - Smart Brevity (2022)
state=stoppedDL
progress=0.0
size_bytes=177613878
directory=/data/media/torrents/seeding/MaM/Jim VandeHei and Mike Allen Roy Schwartz - Smart Brevity (2022)
label=abtorrents
tracker_url=https://usefultrash.net:2345/d77e6661c2af90f67e2a32377a6cc205/announce
is_cross_seed=no
data_on_disk=no
file_count=0
nlinks_sample=0
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/MaM
seeds_available=0
```

### Item 18: Fly.Me.To.The.Moon (rehome-unique)
```
hash=ef48a9203545aa798775fba7e9a3e7ca396032fe
name=Fly.Me.To.The.Moon.2024.REPACK.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX.mkv
state=stoppedDL
progress=0.0
size_bytes=9334752811
directory=/data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79
label=-
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
is_cross_seed=no
data_on_disk=yes_dir_empty
file_count=0
nlinks_sample=0
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79
seeds_available=0
```

---

## SECTION 2: qB BAD-STATE ITEMS

### qB Item 1: Love and Monsters (stalledUP in qB)
```
hash=8c3e841e16a48bde86a33b11a492063ec911379a
name=Love and Monsters 2020 REPACK BluRay 1080p DTS-HD MA 7 1 AVC REMUX-FraMeSToR
qb_state=stalledUP
qb_save_path=/data/media/torrents/seeding/TorrentDay
qb_progress=1
rt_state=stalledUP
```
**NOTE**: This is stalledUP in both qB and RT. Cross-seed item (category=cross-seed). qB must NOT actively upload — should be stoppedUP in qB.

### qB Item 2: V for Vendetta (stalledUP in qB)
```
hash=4adbb5a7e4d1011ff8286de67c92f2467e81df5b
name=V for Vendetta 2005 HYBRID BluRay 1080p TrueHD Atmos 7 1 VC-1 REMUX-FraMeSToR
qb_state=stalledUP
qb_save_path=/data/media/torrents/seeding/TorrentDay
qb_progress=1
rt_state=stoppedUP
```
**NOTE**: stalledUP in qB but stoppedUP in RT. Cross-seed item (category=cross-seed). Should be stoppedUP in qB.

---

## SECTION 3: TRACKER ISSUES

### Issue 1: Euphoria S03E08 (aither - deleted)
```
hash=ccd12d5455efad859e7528efa3d63da59a01af2c
name=Euphoria.US.S03E08.In.God.We.Trust.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 2: SNL S51E04 (onlyencodes - InfoHash not found)
```
hash=61c3c31481d4c26093eec909f671697886796703
name=Saturday.Night.Live.S51E04.Miles.Teller.Brandi.Carlile.November.1.2025.1080p.HULU.WEB-DL.DDP5.1.H.264-None.mkv
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
issue_type=auth_err
rt_state=stalledUP
rt_progress=1.0
```

### Issue 3: Euphoria S03E07 (aither - deleted)
```
hash=491f271e660e8add0ee2207b4f8a408a53af4797
name=Euphoria.US.S03E07.Rain.or.Shine.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 4: SNL S51E02 (onlyencodes - InfoHash not found)
```
hash=05f8d888d6dcf9365e4b46e73786331ad919c9cc
name=Saturday.Night.Live.S51E02.Amy.Poehler.Role.Model.October.11.2025.1080p.HULU.WEB-DL.DDP5.1.H.264-None.mkv
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
issue_type=auth_err
rt_state=stalledUP
rt_progress=1.0
```

### Issue 5: Euphoria S03E02 (aither - deleted)
```
hash=6aba5d7d70bf775b3edd9961254090a86ba702d3
name=Euphoria.US.S03E02.America.My.Dream.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 6: Killers of the Flower Moon (darkpeers - deleted)
```
hash=67dce7012b7d7f241dabfa724d47db51917d6ac2
name=Killers.of.the.Flower.Moon.2023.1080p.BluRay.DDP5.1.x264-ZoroSenpai.mkv
tracker_url=https://darkpeers.org/announce/72525a46b98b9e30813865496505276f
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 7: Euphoria S03E05 (aither - deleted)
```
hash=1c55faa72e57efb8c42e91c53756d3a5538fb426
name=Euphoria.US.S03E05.This.Little.Piggy.with.Audio.Description.1080p.AMZN.WEB-DL.DDP5.1.H.264-Kitsune.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 8: How.Its.Made.S32 (torrentleech - unregistered)
```
hash=9e403665219e01b2f58e0bca7117454a70de82ef
name=How.Its.Made.S32.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
tracker_url=https://tracker.torrentleech.org/a/fa267c9efcdf6a63090fa087a6de40ed/announce
issue_type=other
rt_state=stalledUP
rt_progress=1.0
```

### Issue 9: Euphoria S03E04 (aither - deleted)
```
hash=fa60c4f5b5d9c74ddfd7c4c12bb7ffc18de472f7
name=Euphoria.US.S03E04.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 10: Euphoria S03E01 (aither - deleted)
```
hash=6de6b6d99cdb5c9af6b2c30c751b45fdbb3d3565
name=Euphoria.US.S03E01.Andale.REPACK.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 11: Legion S03 (filelist - unregistered)
```
hash=0782850032bfcd15d74bf1c022fbf61fe39e79c7
name=Legion.S03.1080p.AMZN.WEB-DL.DDP5.1.H.264-NTb
tracker_url=http://reactor.filelist.io/652beba7dfc087cbb79956bd6bd2992e/announce
issue_type=other
rt_state=stalledUP
rt_progress=1.0
```

### Issue 12: Euphoria S03E03 (aither - deleted)
```
hash=8ae4283bc0da4f7950368964360d6bb65ff587f3
name=Euphoria.US.S03E03.The.Ballad.of.Paladin.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 13: SNL S51E06 (onlyencodes - InfoHash not found)
```
hash=6d6d073572998c2a73d42deefbabdbc3ba931b83
name=Saturday.Night.Live.S51E06.Glen.Powell.Olivia.Dean.November.15.2025.1080p.HULU.WEB-DL.DDP5.1.H.264-None.mkv
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
issue_type=auth_err
rt_state=stalledUP
rt_progress=1.0
```

### Issue 14: SNL S51E11 (nebulance - Passkey not found)
```
hash=8f18b3923c3f96a11ede281caa711a058089db90
name=Saturday.Night.Live.S51E11.Teyana.Taylor.Geese.January.24.2026.1080p.HULU.WEB-DL.DDP5.1.H.264-None.mkv
tracker_url=https://tracker.nebulance.io/15fa243354827df1b4256a9089b4fa7f/announce
issue_type=other
rt_state=stalledUP
rt_progress=1.0
```

### Issue 15: War.Machine.2026 (aither - deleted)
```
hash=6eb07c0ee7da3a1189efa59738d7643289780b4d
name=War.Machine.2026.iNTERNAL.BluRay.1080p.REMUX.AVC.DTS-HD.MA.5.1-Aisha.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 16: Euphoria S03E06 (aither - deleted)
```
hash=b60c32b2bd8541855926aeb77577e5d7194c6dfb
name=Euphoria.US.S03E06.Stand.Still.and.See.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 17: SNL S51E18 (aither - deleted)
```
hash=e08fbf38909be9ff9626ca974e94b7396cbaf623
name=Saturday.Night.Live.S51E18.Olivia.Rodrigo.May.2.2026.1080p.HULU.WEB-DL.DDP5.1.H.264-None.mkv
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
issue_type=deleted
rt_state=stalledUP
rt_progress=1.0
```

### Issue 18: SNL S51E03 (onlyencodes - InfoHash not found)
```
hash=130b442ddc074aaa4857c5a1ac6b595089bfce5b
name=Saturday.Night.Live.S51E03.Sabrina.Carpenter.October.18.2025.1080p.HULU.WEB-DL.DDP5.1.H.264-None.mkv
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
issue_type=auth_err
rt_state=stalledUP
rt_progress=1.0
```

---

## Key Findings for Lead

### RT DL Items: Patterns & Anomalies

1. **No-data items (data_on_disk=no)** — 4 items have no data on disk:
   - `6b6043ca` Hunter's Code Book 4 (cross-seed, stoppedDL, 0%)
   - `282ec595` The Conjuring (cross-seed, stoppedDL, 0%)
   - `f0bc85ee` Magic City S01 (yuscene, pausedDL, 0%)
   - `815e28c8` Smart Brevity (abtorrents, stoppedDL, 0%)

2. **Empty rehome-unique dirs** — 2 items have empty directories in `_rehome-unique/`:
   - `8e438130` The Muppet Christmas Carol
   - `ef48a920` Fly Me To The Moon
   These directories exist but are empty (yes_dir_empty). Data was likely moved.

3. **Cross-seed items actively "downloading"** — 1 serious anomaly:
   - `145548eb` How.Its.Made.S22 (45% done, TorrentDay). Cross-seed items should NEVER download. Hardlink source may be missing or moved.

4. **StalledDL at 99% (5 items)** — Need seeds to finish:
   - `127c3834` River Monsters S07 (99.9%, TD, seeds=0)
   - `245f2bce` Dexter S02 (99.9%, speedcd, seeds=0)
   - `e36553b1` Dexter S07 (99.9%, speedcd, seeds=0)
   - `96d896ca` Transformers (99.9%, digitalcore, seeds=0)
   - `5caca88d` Diary Teenage Girl (98.4%, TL, seeds=0)
   All have seeds_available=0.

5. **Cross-seed items at 0% progress** — Most stoppedDL cross-seed items have data on disk (files present). For the shared "Greenland" entry in YUSCENE (API), there are 3 RT entries all pointing to the same directory with 115 files each, nlinks=5 (hardlinked).

### qB Bad-State Items

2 items in stalledUP (unacceptable in qB):
- `8c3e841e` Love and Monsters — stalledUP in both qB and RT (cross-seed)
- `4adbb5a7` V for Vendetta — stalledUP in qB but stoppedUP in RT (cross-seed)

Both are cross-seed items that should be stoppedUP in qB.

### Tracker Issues

- **11 deleted** (all aither.cc — Euphoria S03 episodes, War Machine, Killers Flower Moon, SNL S51E18)
- **4 auth_err** (all onlyencodes — SNL S51 episodes: InfoHash not found)
- **3 other**: 
  - `9e403665` How Its Made S32 — unregistered on torrentleech
  - `07828500` Legion S03 — unregistered on filelist
  - `8f18b392` SNL S51E11 — Passkey not found on nebulance

### Seeds Availability

All 6 stalledDL items have seeds_available=0 via XMLRPC (`d.peers_complete`). All are stalled at 98-99.9% with no seeders to finish.

---

```
🟪 task-log=J03-T06_rt-health-investigation 🟪
```
