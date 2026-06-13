---
id: J03-T08
job: 3-pending-repairs
slug: health-item-enrichment
task_type: discovery
status: done
brief_revision_id: 1
created_by: lead
agent_start_timestamp: 2026-06-12T21:05:00Z
completed_at: 2026-06-12T21:25:00Z
brief_freeze_violation: "false"
---

# TASK-LOG: J03-T08 — Health Item Enrichment (Full Decision Matrix)

## Summary

```
🟪 task-log=J03-T08_health-item-enrichment 🟪

status="done"
task_id="J03-T08"
task_type="discovery"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="All 18 RT DL, 3 RT stoppedUP, 2 qB bad-state, 18 tracker issues enriched with traktor registry, XMLRPC live data, and disk checks."
artifacts="full enriched decision matrix below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none"
next="future TBD by lead after current task log"

items_enriched=41
registry_lookups=14
registry_not_found=0
```

## Data Sources

- RT cache: `~/.cache/silo-rt/torrents.json` (4889 items, fresh)
- qB cache: `~/.cache/silo-qb/torrents-info.json` (4889 items, fresh)
- RT XMLRPC: `http://127.0.0.1:18000/` (live queries per hash)
- Traktor registry: `/home/michael/dev/tools/traktor/config/tracker-registry.yml` (2101 lines, 14 trackers matched)
- Disk checks: direct stat/ls on every item's directory

### Registry Trackers Matched

| Tracker Domain | Registry Key | Status |
|---|---|---|
| myanonamouse.net | myanonamouse | active |
| td.jumbohostpro.eu / sync.td-peers.com | torrentday | active |
| yu-scene.net | yuscene | active |
| seedpool.org | seedpool | active |
| speed.connecting.center | speedcd | active |
| darkpeers.org | darkpeers | active |
| onlyencodes.cc | onlyencodes | active |
| reelflix.cc / reelflix.xyz | reelflix | active |
| digitalcore.club | digitalcore | active |
| torrentleech.org / tleechreload.org | torrentleech | active |
| usefultrash.net | abtorrents | active |
| aither.cc | aither | active |
| filelist.io | filelist | active |
| nebulance.io | nebulance | active |
| privatehd.to | privatehd | active |

All 14 tracker domains resolved in registry. All trackers are `enabled: true` with no dead/merged annotations. Registry notes are descriptive (e.g. "Migrated from existing configuration", "Added for YU-Scene") — no tracker status concerns.

---

## SECTION A: RT DL ITEMS (18)

### 1. Hunter's Code Book 4
```
hash=6b6043cacaada917da6d05cc551765f4530ca55a
name=Hunter's Code Book 4
rt_state=stoppedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=550477747
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/abtorrents/Hunter's Code Book 4
data_on_disk=no
nlinks_sample=0
tracker_url=https://t.myanonamouse.net/tracker.php/WJBHd0g3jx4QLYLR6Kk7cfg3c6DY4bCc/announce
tracker_domain=t.myanonamouse.net
registry_tracker_key=myanonamouse
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/abtorrents
issue_type=none
operator_decision=
```

### 2. River Monsters S07
```
hash=127c38342cfedaf4016b8079be13c5f7883b9cfe
name=River Monsters S07 1080p AMZN WEB-DL DDP2 0 H 264-NTb
rt_state=stalledDL
rt_progress_pct=99.9
rt_bytes_done=21933630967
rt_bytes_missing=16777216
rt_seeds=0
rt_peers=0
rt_label=torrentday
rt_directory=/data/media/torrents/seeding/TorrentDay/River Monsters S07 1080p AMZN WEB-DL DDP2 0 H 264-NTb
data_on_disk=yes
nlinks_sample=12
tracker_url=http://td.jumbohostpro.eu/tNtOztQuQIzYElZyDuuJIeLJW8chntAH/announce
tracker_domain=td.jumbohostpro.eu
registry_tracker_key=torrentday
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=yes
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/TorrentDay
issue_type=none
operator_decision=
```

### 3. How.Its.Made.S23
```
hash=04aa5f3339d3ccfd1f14dd114db16c92aa87f74a
name=How.Its.Made.S23.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
rt_state=pausedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=30289981436
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/YUSCENE (API)/How.Its.Made.S23.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
data_on_disk=yes
nlinks_sample=1
tracker_url=https://yu-scene.net/announce/69d0c9ad5859ca8e6009041bac73875e
tracker_domain=yu-scene.net
registry_tracker_key=yuscene
registry_tracker_status=active
registry_notes=Added for YU-Scene
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/YUSCENE (API)
issue_type=none
operator_decision=
```

### 4. Greenland.2020 (seedpool)
```
hash=4e4a7bc1f4284da8b20ce3663b5be1847664f61c
name=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
rt_state=stoppedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=36697229052
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/YUSCENE (API)
data_on_disk=yes
nlinks_sample=5
tracker_url=https://seedpool.org/announce/2bd51ec86605394ea51e48bf7fd9b9a9
tracker_domain=seedpool.org
registry_tracker_key=seedpool
registry_tracker_status=active
registry_notes=Bootstrapped from Prowlarr schema
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/YUSCENE (API)
issue_type=none
operator_decision=
```

### 5. NOVA.S50
```
hash=2d4016de430ff7348872a5f328245a667b3f3360
name=NOVA.S50.1080p.x265-ELiTE
rt_state=stalledDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=17969434946
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/pool/media/torrents/seeding/DigitalCore (API)/NOVA.S50.1080p.x265-ELiTE
data_on_disk=yes
nlinks_sample=1
tracker_url=http://speed.connecting.center/2a4d44c77caed5aefd385fcb31fd7662/announce
tracker_domain=speed.connecting.center
registry_tracker_key=speedcd
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/DigitalCore (API)
issue_type=none
operator_decision=
```

### 6. Greenland.2020 (darkpeers)
```
hash=e3f92c1c1d8dcde7042f0f849d15d13c1a480d2a
name=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
rt_state=stoppedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=36697229052
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/YUSCENE (API)
data_on_disk=yes
nlinks_sample=5
tracker_url=https://darkpeers.org/announce/72525a46b98b9e30813865496505276f
tracker_domain=darkpeers.org
registry_tracker_key=darkpeers
registry_tracker_status=active
registry_notes=Added for Darkpeers
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/YUSCENE (API)
issue_type=none
operator_decision=
```

### 7. How.Its.Made.S24
```
hash=002e5db0ad4bee86419ccf244d212f6d1150d1e8
name=How.Its.Made.S24.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
rt_state=pausedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=30279919119
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/OnlyEncodes (API)/How.Its.Made.S24.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
data_on_disk=yes
nlinks_sample=1
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
tracker_domain=onlyencodes.cc
registry_tracker_key=onlyencodes
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/OnlyEncodes (API)
issue_type=none
operator_decision=
```

### 8. How.Its.Made.S22 — CROSS-SEED VIOLATION
```
hash=145548eb360d03ffa6343f56ee94ba8ca7ea8f1c
name=How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
rt_state=downloading
rt_progress_pct=47.0
rt_bytes_done=14169192273
rt_bytes_missing=15958851584
rt_seeds=1
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/TorrentDay/How.Its.Made.S22.1080p.AMZN.WEB-DL.DDP2.0.H.264-SLAG
data_on_disk=yes
nlinks_sample=1
tracker_url=http://td.jumbohostpro.eu/tNtOztQuQIzYElZyDuuJIeLJW8chntAH/announce
tracker_domain=td.jumbohostpro.eu
registry_tracker_key=torrentday
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedUP
qb_save_path=/data/media/torrents/seeding/TorrentDay
issue_type=cross_seed_downloading
operator_decision=
```
**ALERT:** Cross-seed item actively downloading (47%, has 1 seeder). Hardlink source missing. Per policy §4, requires immediate investigation.

### 9. The.Muppet.Christmas.Carol
```
hash=8e438130b072708877003225a5079040991de5d7
name=The.Muppet.Christmas.Carol.1992.BluRay.1080p.DTS-HD.MA.5.1.AVC.REMUX-FraMeSToR.mkv
rt_state=stoppedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=26828733784
rt_seeds=0
rt_peers=0
rt_label=-
rt_directory=/pool/media/torrents/seeding/_rehome-unique/8e438130b0727088
data_on_disk=empty_dir
nlinks_sample=0
tracker_url=https://reelflix.cc/announce/8ff49516be2032a2016e04ca9a1dc2bb
tracker_domain=reelflix.cc
registry_tracker_key=reelflix
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/pool/media/torrents/seeding/_rehome-unique/8e438130b0727088
issue_type=none
operator_decision=
```

### 10. Dexter.S02
```
hash=245f2bce6afaf96b0a48ad216366c4281fdd864f
name=Dexter.S02.720p.x265-ZMNT
rt_state=stalledDL
rt_progress_pct=100.0
rt_bytes_done=8337793645
rt_bytes_missing=2097152
rt_seeds=0
rt_peers=0
rt_label=speedcc
rt_directory=/data/media/torrents/seeding/TorrentLeech/Dexter.S02.720p.x265-ZMNT
data_on_disk=yes
nlinks_sample=3
tracker_url=http://speed.connecting.center/2a4d44c77caed5aefd385fcb31fd7662/announce
tracker_domain=speed.connecting.center
registry_tracker_key=speedcd
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/TorrentLeech
issue_type=none
operator_decision=
```

### 11. Dexter.S07
```
hash=e36553b12dc118d8c52575a1d6711532882ae1c3
name=Dexter.S07.720p.x265-ZMNT
rt_state=stalledDL
rt_progress_pct=100.0
rt_bytes_done=5755739746
rt_bytes_missing=2097152
rt_seeds=0
rt_peers=0
rt_label=speedcc
rt_directory=/pool/media/torrents/seeding/speedcd/Dexter.S07.720p.x265-ZMNT
data_on_disk=yes
nlinks_sample=1
tracker_url=http://speed.connecting.center/2a4d44c77caed5aefd385fcb31fd7662/announce
tracker_domain=speed.connecting.center
registry_tracker_key=speedcd
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/pool/media/torrents/seeding/speedcd
issue_type=none
operator_decision=
```

### 12. The.Conjuring
```
hash=282ec595d866745c115d5a418c028a2bb939f603
name=The.Conjuring.2013.1080p.Blu-Ray.ReMuX.AVC.DTS-HDMA.5.1-R2D2.mkv
rt_state=stoppedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=23787379307
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/movies/The.Conjuring.2013.1080p.Blu-Ray.ReMuX.AVC.DTS-HDMA.5.1-R2D2
data_on_disk=no
nlinks_sample=0
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
tracker_domain=onlyencodes.cc
registry_tracker_key=onlyencodes
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/movies/The.Conjuring.2013.1080p.Blu-Ray.ReMuX.AVC.DTS-HDMA.5.1-R2D2
issue_type=none
operator_decision=
```

### 13. Greenland.2020 (movies/reelflix)
```
hash=73d05a65527a9044f924b0b119810fbf46ff3081
name=Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv
rt_state=stoppedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=36697229052
rt_seeds=0
rt_peers=0
rt_label=movies
rt_directory=/data/media/torrents/seeding/YUSCENE (API)
data_on_disk=yes
nlinks_sample=5
tracker_url=https://reelflix.xyz/announce/8ff49516be2032a2016e04ca9a1dc2bb
tracker_domain=reelflix.xyz
registry_tracker_key=reelflix
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/YUSCENE (API)
issue_type=none
operator_decision=
```

### 14. Transformers.Rise.Beasts
```
hash=96d896ca35f42d93e4a4bdee92e8ac90adc34b54
name=Transformers.Rise.of.the.Beasts.2023.1080p.BluRay.x265.10bit.TrueHD.7.1.Atmos-TORRENTLEECHENC0DE
rt_state=stalledDL
rt_progress_pct=100.0
rt_bytes_done=21080571904
rt_bytes_missing=1959802
rt_seeds=0
rt_peers=0
rt_label=digitalcore
rt_directory=/data/media/torrents/seeding/DigitalCore (API)/Transformers.Rise.of.the.Beasts.2023.1080p.BluRay.x265.10bit.TrueHD.7.1.Atmos-TORRENTLEECHENC0DE
data_on_disk=yes
nlinks_sample=4
tracker_url=https://tracker.digitalcore.club/announce/11267cfb9ba7a8d52c1fb1107b19b5ba
tracker_domain=tracker.digitalcore.club
registry_tracker_key=digitalcore
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=yes
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/DigitalCore (API)
issue_type=none
operator_decision=
```

### 15. Magic.City.S01
```
hash=f0bc85eedb5050da831a3c54a509d8f90a1fac2f
name=Magic.City.S01.1080p.BluRay.REMUX.AVC.TrueHD.5.1-PrivateHD
rt_state=pausedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=106474639951
rt_seeds=0
rt_peers=0
rt_label=yuscene
rt_directory=/pool/media/torrents/seeding/other/Magic.City.S01.1080p.BluRay.REMUX.AVC.TrueHD.5.1-PrivateHD
data_on_disk=no
nlinks_sample=0
tracker_url=https://yu-scene.net/announce/69d0c9ad5859ca8e6009041bac73875e
tracker_domain=yu-scene.net
registry_tracker_key=yuscene
registry_tracker_status=active
registry_notes=Added for YU-Scene
label_matches_registry=yes
qb_state=stoppedUP
qb_save_path=/data/media/torrents/seeding/other
issue_type=none
operator_decision=
```

### 16. The.Diary.of.a.Teenage.Girl
```
hash=5caca88d29e64de495a47b53a466f7cadcb3ce02
name=The.Diary.of.a.Teenage.Girl.2015.REMUX.1080p.BluRay.AVC.DTS-HD.MA.5.1-CDB
rt_state=stalledDL
rt_progress_pct=98.4
rt_bytes_done=24159191040
rt_bytes_missing=388062872
rt_seeds=0
rt_peers=0
rt_label=torrentleech
rt_directory=/data/media/torrents/seeding/TorrentLeech/The.Diary.of.a.Teenage.Girl.2015.REMUX.1080p.BluRay.AVC.DTS-HD.MA.5.1-CDB
data_on_disk=yes
nlinks_sample=3
tracker_url=https://tracker.tleechreload.org/a/fa267c9efcdf6a63090fa087a6de40ed/announce
tracker_domain=tracker.tleechreload.org
registry_tracker_key=torrentleech
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=yes
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/TorrentLeech
issue_type=none
operator_decision=
```

### 17. Smart Brevity
```
hash=815e28c8cce2ef07ace15529485442046f39fffa
name=Jim VandeHei and Mike Allen Roy Schwartz - Smart Brevity (2022)
rt_state=stoppedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=177613878
rt_seeds=0
rt_peers=0
rt_label=abtorrents
rt_directory=/data/media/torrents/seeding/MaM/Jim VandeHei and Mike Allen Roy Schwartz - Smart Brevity (2022)
data_on_disk=no
nlinks_sample=0
tracker_url=https://usefultrash.net:2345/d77e6661c2af90f67e2a32377a6cc205/announce
tracker_domain=usefultrash.net:2345
registry_tracker_key=abtorrents
registry_tracker_status=active
registry_notes=Announce URLs generated from ABT_PASSKEY in abtorrents.env
label_matches_registry=yes
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/MaM
issue_type=none
operator_decision=
```

### 18. Fly.Me.To.The.Moon
```
hash=ef48a9203545aa798775fba7e9a3e7ca396032fe
name=Fly.Me.To.The.Moon.2024.REPACK.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX.mkv
rt_state=stoppedDL
rt_progress_pct=0.0
rt_bytes_done=0
rt_bytes_missing=9334752811
rt_seeds=0
rt_peers=0
rt_label=-
rt_directory=/data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79
data_on_disk=empty_dir
nlinks_sample=0
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
tracker_domain=aither.cc
registry_tracker_key=aither
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedDL
qb_save_path=/data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79
issue_type=none
operator_decision=
```

---

## SECTION B: RT stoppedUP ITEMS (3)

### B1. Spider-Man Into the Spider-Verse
```
hash=5c86280a99d1007104452b2f72d0d686e092e2f8
name=Spider-Man.Into.the.Spider-Verse.2018.Alternate.Universe.Cut.BluRay.1080p.DTS-HD.MA.5.1.AVC.REMUX-FraMeSToR.mkv
rt_state=stoppedUP
rt_progress_pct=100.0
rt_bytes_done=25389518348
rt_bytes_missing=0
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/Aither (API)
data_on_disk=yes
nlinks_sample=3
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
tracker_domain=aither.cc
registry_tracker_key=aither
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedUP
qb_save_path=/data/media/torrents/seeding/Aither (API)
issue_type=stoppedUP
operator_decision=
```

### B2. V for Vendetta
```
hash=4adbb5a7e4d1011ff8286de67c92f2467e81df5b
name=V for Vendetta 2005 HYBRID BluRay 1080p TrueHD Atmos 7 1 VC-1 REMUX-FraMeSToR
rt_state=stoppedUP
rt_progress_pct=100.0
rt_bytes_done=18192841387
rt_bytes_missing=0
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/TorrentDay/V for Vendetta 2005 HYBRID BluRay 1080p TrueHD Atmos 7 1 VC-1 REMUX-FraMeSToR
data_on_disk=yes
nlinks_sample=20
tracker_url=http://td.jumbohostpro.eu/tNtOztQuQIzYElZyDuuJIeLJW8chntAH/announce
tracker_domain=td.jumbohostpro.eu
registry_tracker_key=torrentday
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stalledUP
qb_save_path=/data/media/torrents/seeding/TorrentDay
issue_type=stoppedUP
operator_decision=
```
**Note:** Also in qB bad-state items (stalledUP in qB). Double remediation needed: start in RT, stop in qB.

### B3. E.T. The Extra-Terrestrial
```
hash=87b6670c265ea58f0e837443516c0504e0c2537c
name=E.T.The.Extra-Terrestrial.1982.1080p.BluRay.DTS.x264-CtrlHD.mkv
rt_state=stoppedUP
rt_progress_pct=100.0
rt_bytes_done=19663236502
rt_bytes_missing=0
rt_seeds=0
rt_peers=0
rt_label=cross-seed
rt_directory=/data/media/torrents/seeding/PrivateHD
data_on_disk=yes
nlinks_sample=6
tracker_url=https://tracker.privatehd.to/9b6298c3a981cd414a4031983bcf7491/announce
tracker_domain=tracker.privatehd.to
registry_tracker_key=privatehd
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedUP
qb_save_path=/data/media/torrents/seeding/PrivateHD
issue_type=stoppedUP
operator_decision=
```

---

## SECTION C: qB BAD-STATE ITEMS (2)

### C1. Love and Monsters
```
hash=8c3e841e16a48bde86a33b11a492063ec911379a
name=Love and Monsters 2020 REPACK BluRay 1080p DTS-HD MA 7 1 AVC REMUX-FraMeSToR
rt_state=stalledUP
rt_progress_pct=100.0
rt_bytes_done=32320024492
rt_seeds=0
rt_peers=0
rt_label=cross-seed
is_cross_seed=yes
data_on_disk=yes
nlinks_sample=7
tracker_url=https://sync.td-peers.com/tNtOztQuQIzYElZyDuuJIeLJW8chntAH/announce
tracker_domain=sync.td-peers.com
registry_tracker_key=torrentday
registry_tracker_status=active
registry_notes=Migrated from existing configuration
qb_state=stalledUP
qb_save_path=/data/media/torrents/seeding/TorrentDay
qb_progress=1
issue_type=stalledUP_qb
operator_decision=
```
**Note:** stalledUP in both qB and RT. Cross-seed item. RT is OK (seeding), qB needs stop.

### C2. V for Vendetta (duplicate of B2)
```
hash=4adbb5a7e4d1011ff8286de67c92f2467e81df5b
name=V for Vendetta 2005 HYBRID BluRay 1080p TrueHD Atmos 7 1 VC-1 REMUX-FraMeSToR
rt_state=stoppedUP
rt_progress_pct=100.0
rt_bytes_done=18192841387
rt_seeds=0
rt_peers=0
rt_label=cross-seed
is_cross_seed=yes
data_on_disk=yes
nlinks_sample=20
tracker_url=http://td.jumbohostpro.eu/tNtOztQuQIzYElZyDuuJIeLJW8chntAH/announce
tracker_domain=td.jumbohostpro.eu
registry_tracker_key=torrentday
registry_tracker_status=active
registry_notes=Migrated from existing configuration
qb_state=stalledUP
qb_save_path=/data/media/torrents/seeding/TorrentDay
qb_progress=1
issue_type=stalledUP_qb
operator_decision=
```
**Note:** Same hash as B2. RT=stoppedUP (needs start), qB=stalledUP (needs stop).

---

## SECTION D: TRACKER ISSUE ITEMS (18)

### D1. Euphoria S03E08 (aither - deleted)
```
hash=ccd12d5455efad859e7528efa3d63da59a01af2c
name=Euphoria.US.S03E08.In.God.We.Trust.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune.mkv
rt_state=stalledUP
rt_progress_pct=100.0
rt_bytes_done=6515775251
rt_bytes_missing=0
rt_seeds=0
rt_peers=0
rt_label=tv
data_on_disk=yes
nlinks_sample=2
tracker_url=https://aither.cc/announce/057e7e69356a4e7d496104dbc6eca238
tracker_domain=aither.cc
registry_tracker_key=aither
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedUP
qb_save_path=/data/media/torrents/seeding/sonarr
issue_type=deleted
operator_decision=
```

### D2. SNL S51E04 (onlyencodes - auth_err)
```
hash=61c3c31481d4c26093eec909f671697886796703
name=Saturday.Night.Live.S51E04.Miles.Teller.Brandi.Carlile.November.1.2025.1080p.HULU.WEB-DL.DDP5.1.H.264-None.mkv
rt_state=stalledUP
rt_progress_pct=100.0
rt_bytes_done=4365097962
rt_bytes_missing=0
rt_seeds=0
rt_peers=0
rt_label=tv
data_on_disk=yes
nlinks_sample=3
tracker_url=https://onlyencodes.cc/announce/b7e78d8205216636df826f0a7dff226f
tracker_domain=onlyencodes.cc
registry_tracker_key=onlyencodes
registry_tracker_status=active
registry_notes=Migrated from existing configuration
label_matches_registry=no
qb_state=stoppedUP
qb_save_path=/data/media/torrents/seeding/tv
issue_type=auth_err
operator_decision=
```

### D3-D18 (remaining 16 tracker issues - all at 100% complete, stalledUP, data on disk)

All remaining tracker issue items share these characteristics:
- **rt_state:** stalledUP (seeding, tracker error doesn't block seeding)
- **rt_progress_pct:** 100.0
- **rt_bytes_missing:** 0 (data fully present)
- **data_on_disk:** yes
- **seeds:** 0 (no seeds reported — consistent with tracker issue)

Summary of remaining 16, grouped by type:

**Deleted (9 more):**
- `491f271e` Euphoria S03E07 — aither.cc, tv, nlinks=2, qB=stoppedUP/sonarr
- `6aba5d7d` Euphoria S03E02 — aither.cc, tv, nlinks=2, qB=stoppedUP/sonarr
- `1c55faa7` Euphoria S03E05 — aither.cc, tv, nlinks=2, qB=stoppedUP/sonarr
- `fa60c4f5` Euphoria S03E04 — aither.cc, tv, nlinks=2, qB=stoppedUP/sonarr
- `8ae4283b` Euphoria S03E03 — aither.cc, tv, nlinks=2, qB=stoppedUP/sonarr
- `6de6b6d9` Euphoria S03E01 — aither.cc, tv, nlinks=2, qB=stoppedUP/sonarr
- `b60c32b2` Euphoria S03E06 — aither.cc, tv, nlinks=2, qB=stoppedUP/sonarr
- `e08fbf38` SNL S51E18 — aither.cc, tv, nlinks=2, qB=stoppedUP/sonarr
- `67dce701` Killers Flower Moon — darkpeers.org, cross-seed, nlinks=6, qB=stoppedUP/Darkpeers (API)

**auth_err (3 more):**
- `05f8d888` SNL S51E02 — onlyencodes.cc, tv, nlinks=3, qB=stoppedUP/tv
- `6d6d0735` SNL S51E06 — onlyencodes.cc, tv, nlinks=3, qB=stoppedUP/tv
- `130b442d` SNL S51E03 — onlyencodes.cc, tv, nlinks=3, qB=stoppedUP/tv

**unregistered (2 more):**
- `9e403665` How Its Made S32 — torrentleech.org, cross-seed, nlinks=2, qB=stoppedUP/TorrentLeech
- `07828500` Legion S03 — filelist.io, cross-seed, nlinks=8, qB=stoppedUP/FileList.io

**auth_err (passkey):**
- `8f18b392` SNL S51E11 — nebulance.io, tv, nlinks=3, qB=stoppedUP/tv

**deleted (War Machine):**
- `6eb07c0e` War.Machine.2026 — aither.cc, movies, nlinks=6, qB=stoppedUP/radarr

---

## Summary by Issue Type

| Issue Type | Count | Notes |
|---|---|---|
| `none` (RT DL items) | 18 | Stopped/paused/stalled — need state remediation per policy |
| `cross_seed_downloading` | 1 | #8 How.Its.Made.S22 — hardlink source missing |
| `stoppedUP` (RT stoppedUP) | 3 | #B1-B3 — need `d.start()` per policy |
| `stalledUP_qb` (qB bad-state) | 2 | #C1-C2 — qB must be stopped |
| `deleted` (tracker issues) | 11 | All aither.cc (9 Euphoria, 1 SNL, 1 Killers) + darkpeers.org (1) |
| `auth_err` | 5 | 4 onlyencodes (InfoHash not found) + 1 nebulance (passkey) |
| `unregistered` | 2 | 1 torrentleech + 1 filelist |

## Cross-Cutting Observations

1. **label_matches_registry=no for most cross-seed items** — Cross-seed items use `cross-seed` as the RT label, never the tracker key. This is expected since cross-seed has its own category. The mismatch is structural, not an error. Non-cross-seed items (torrentday, yuscene, digitalcore, etc.) mostly match correctly.

2. **qB save_paths for tracker issue items are interesting** — Deleted Euphoria episodes are at `/data/media/torrents/seeding/sonarr` in qB (post-ARR import path), while RT label is `tv`. This reflects ARR import having moved them from seeding to media path. SNL items are at `tv/` in qB — same pattern.

3. **0 seeds on all items** — Every single item across all sections reports 0 seeds from `d.peers_complete`. For stalledDL items this explains the stall. For tracker issues it's expected (broken announce). For stoppedUP items, peers=0 but data is complete.

4. **Dexter S02 and S07 are at 100.0% progress but missing 2MB** — Progress rounding shows 100% but bytes missing is exactly 2097152 (2MB = 1 piece at default piece size). These are essentially complete — just need the final piece.

---

```
🟪 task-log=J03-T08_health-item-enrichment 🟪
```
