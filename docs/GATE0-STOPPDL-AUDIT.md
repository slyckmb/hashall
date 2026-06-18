# Gate 0 — stoppedDL Audit Report

**Date:** 2026-06-18
**Agent:** opencode (deepseek-v4-flash-free)
**Worktree:** j20 (cr/hashall-20260530-000517-claude__j20)
**Head:** `92f6574`

---

## Pre-Audit State

| Metric | Value |
|--------|-------|
| qB stoppedUP | 4787 |
| qB stoppedDL | 115 |
| RT complete=1, down_rate=0 | 110/115 |
| RT complete=0 | 5/115 |

---

## Audit Summary

| Verdict | Count | % |
|---------|-------|---|
| HEALTHY | 82 | 71.3% |
| MISSING_DATA | 28 | 24.3% |
| RT_INCOMPLETE | 5 | 4.3% |
| **Total** | **115** | **100%** |

**RT downloading:** 0 — no items had `d.down.rate > 0` during audit.

---

## Per-Torrent Table

### HEALTHY (82) — RT complete, files present at qB path, qB stoppedDL

| Hash (16) | Name | qB State | qB Progress | RT Complete | RT Rate | RT Directory | Files | Recheck Outcome |
|---|---|---|---|---|---|---|---|---|
| 3af5a85cf2929786 | 28.Weeks.Later.2007 | stoppedDL | 100% | 1 | 0 | cross-seed/XSpeeds/ | YES | stoppedDL |
| 2f64f48d0b3e965e | 28.Weeks.Later.2007 | stoppedDL | 100% | 1 | 0 | cross-seed/XSpeeds/ | YES | stoppedDL |
| 08fc68ee4cc1937a | 28.Weeks.Later.2007 | stoppedDL | 100% | 1 | 0 | cross-seed/XSpeeds/ | YES | stoppedDL |
| 0c72a60861f98df9 | Alien.Resurrection.1997 | stoppedDL | 100% | 1 | 0 | cross-seed/FearNoPeer/ | YES | stoppedDL |
| 1376e795c9d9ca89 | Alien.Romulus.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | **stoppedUP** |
| d753b27bd23b2281 | Aliens.vs.Predator.Requiem | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 8779246eebcf9135 | Azrael Angel of Death | stoppedDL | 100% | 1 | 0 | cross-seed/Darkpeers (API)/ | YES | - |
| 2d34c67806bd1f95 | Azrael.Angel.of.Death.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/XSpeeds/ | YES | - |
| 49d3d9fd362768db | Azrael.Angel.of.Death.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 6e2271b54cf57ae7 | Barski - Land of Lisp.pdf | stoppedDL | 100% | 1 | 0 | cross-seed/MyAnonamouse/ | YES | - |
| 9e40638a670a51d6 | Black.Mirror.Bandersnatch | stoppedDL | 100% | 1 | 0 | cross-seed/XSpeeds/ | YES | - |
| 2d8af2f8120daa07 | Bullet.Train.2022 | stoppedDL | 100% | 1 | 0 | cross-seed/_movie/ | YES | - |
| 8bd649dad735d64c | Bullet.Train.2022 | stoppedDL | 100% | 1 | 0 | cross-seed/movies/ | YES | - |
| 05beedbc07bbfd30 | Burying.The Ex.2014 | stoppedDL | 100% | 1 | 0 | cross-seed/YUSCENE (API)/ | YES | - |
| 3937837845c3f806 | Chicago.Fire.S12 | stoppedDL | 100% | 1 | 0 | cross-seed/DigitalCore (API)/ | YES | - |
| 40a1d9dc713cfad4 | Chicago.Fire.S12 | stoppedDL | 100% | 1 | 0 | cross-seed/DigitalCore (API)/ | YES | - |
| 002151f24da1a959 | Cinderella.2021 | stoppedDL | 100% | 1 | 0 | cross-seed/DigitalCore (API)/ | YES | - |
| b75db0137986e3eb | Cinderella.2021 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 68f2165dcec621a3 | Cinderella.2021 | stoppedDL | 100% | 1 | 0 | cross-seed/Darkpeers (API)/ | YES | - |
| 35e253cd0654968c | Cinderella.2021 | stoppedDL | 100% | 1 | 0 | cross-seed/YUSCENE (API)/ | YES | - |
| 97343f6005da2ed8 | Cinderella.2021 | stoppedDL | 100% | 1 | 0 | cross-seed/DigitalCore (API)/ | YES | - |
| e144bce2d0d86d0d | Cleverman.S01 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| ef8d24059311056a | Cleverman.S02 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 58c56176ac98e77d | Cleverman.S02 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 55a3df42dcf14d25 | Elemental.2023 | stoppedDL | 100% | 1 | 0 | cross-seed/DigitalCore (API)/ | YES | - |
| 2efbeab815daf10f | Fly.Me.To.The.Moon | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| 1ab1bef12b5bd674 | Fly.Me.To.The.Moon | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| 228eca6edac19bb9 | Fly.Me.To.The.Moon | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| 314034000f91a460 | Fly.Me.To.The.Moon | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| 054eb86db10122ee | Furiosa A Mad Max Saga | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| 1af77f04b135676a | Greenland.2020 | stoppedDL | 100% | 1 | 0 | cross-seed/YUSCENE (API)/ | YES | - |
| e7f00a034a3b1cc3 | Greenland.2020 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 2761a4bb724fec1c | Heretic.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| 8f7bffad8fa830fd | How.Its.Made.S10 | stoppedDL | 100% | 1 | 0 | cross-seed/Darkpeers (API)/ | YES | - |
| b9b4129754e0ba3b | How.Its.Made.S10 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| b30fe86fad11b06f | How.Its.Made.S13 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| fda85be39db864e0 | How.Its.Made.S13 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 4133073939e40ecc | How.Its.Made.S13 | stoppedDL | 100% | 1 | 0 | cross-seed/FearNoPeer/ | YES | - |
| 22125ada5ed76ae2 | How.Its.Made.S13 | stoppedDL | 100% | 1 | 0 | cross-seed/FearNoPeer/ | YES | - |
| da30f89928e6e9e0 | How.Its.Made.S13 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 5e8f48b70005b6bd | How.Its.Made.S20 | stoppedDL | 100% | 1 | 0 | cross-seed/Darkpeers (API)/ | YES | - |
| d8c72e0ea8cdfbce | Longlegs.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| cb5ad3f613d9794b | Longlegs.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 922eed0bf5530890 | Longlegs.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/HD-Space/ | YES | - |
| fd6e0510a31eecb5 | M3GAN.2.0.2025 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 9b430bf2ab9508f5 | M3GAN.2.0.2025 | stoppedDL | 100% | 1 | 0 | cross-seed/YUSCENE (API)/ | YES | - |
| 2c10308ff15979da | M3GAN.2.0.2025 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 384a6d53f3774c7e | Megalopolis.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| c98f985835abdc0a | Mickey.17.2025 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 64ef4b90fda1d92a | NOVA.S50.1080p.x265-ELiTE | stoppedDL | 100% | 1 | 0 | cross-seed/DigitalCore (API)/ | YES | - |
| 2d4016de430ff734 | NOVA.S50.1080p.x265-ELiTE | stoppedDL | 100% | 1 | 0 | cross-seed/DigitalCore (API)/ | YES | - |
| 2fb25fdf2ef20ae5 | Novitiate.2017 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 01d362640fe4fa6d | Peppermint.2018 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| c1814769ad472f57 | Peppermint.2018 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 1e48e188ed92eaff | Stranger.Things.S02 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 18843b7d12172dad | Stranger.Things.S02 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 04799ca5a0fafa8d | Stranger.Things.S02 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 7a329a87f52300ae | Stranger.Things.S03 | stoppedDL | 100% | 1 | 0 | cross-seed/YUSCENE (API)/ | YES | - |
| ee73d3126855e726 | Stranger.Things.S03 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 36cd5df27c224eb1 | Stranger.Things.S03 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 7d8124c5c98cda50 | Stranger.Things.S03 | stoppedDL | 100% | 1 | 0 | cross-seed/DigitalCore (API)/ | YES | - |
| 37b945b3d7016c42 | Subservience.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 7df1f012dfd5ddfd | The.Accountant.2.2025 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| 32963bcf32d9dd03 | The.Electric.State.2025 | stoppedDL | 100% | 1 | 0 | cross-seed/movies/ | YES | - |
| a9d7cd8d3549a036 | The.Electric.State.2025 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 913f7936ee8a1b3e | The.Electric.State.2025 | stoppedDL | 100% | 1 | 0 | cross-seed/movies/ | YES | - |
| 6e9f9fb1da1ff77c | The.Substance.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |
| daa503b50fe76336 | The.Substance.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 2179ba97574ebdc9 | The.West.Wing.S02 | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| a314489c07630555 | The.West.Wing.S04 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| bd72dffdf417c6b9 | The.West.Wing.S06 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 9ca51d8cdd8d3285 | The.West.Wing.S06 | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| 1fc5a3607eeaad15 | The.West.Wing.S06 | stoppedDL | 100% | 1 | 0 | cross-seed/hawke-uno/ | YES | - |
| fa032ca56ad68cc1 | Twin.Peaks.S01 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 8b2237d1a64f3ad8 | Twin.Peaks.S03 | stoppedDL | 100% | 1 | 0 | cross-seed/YOiNKED (API)/ | YES | - |
| 9fb78cde0e0a1d8e | Twin.Peaks.S03 | stoppedDL | 100% | 1 | 0 | cross-seed/YOiNKED (API)/ | YES | - |
| 2c24f95d0d0109e5 | Twin.Peaks.S03 | stoppedDL | 100% | 1 | 0 | cross-seed/YOiNKED (API)/ | YES | - |
| b002826231d5a439 | Twisters.2024 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 04ca7e172d7f65c2 | V.for.Vendetta.2005 | stoppedDL | 100% | 1 | 0 | cross-seed/_movie/ | YES | - |
| a5a2b78798009b38 | Wilding.2023 | stoppedDL | 100% | 1 | 0 | cross-seed/ | YES | - |
| 8c8a25c76fabdde5 | Wilding.2023 | stoppedDL | 100% | 1 | 0 | cross-seed/_movie/ | YES | - |
| 030660dac09a07dc | Wilding.2023 | stoppedDL | 100% | 1 | 0 | cross-seed/seedpool (API)/ | YES | - |

### RT_INCOMPLETE (5) — RT complete=0

| Hash (16) | Name | qB Path | RT Directory |
|---|---|---|---|
| 245f2bce6afaf96b | Dexter.S02.720p.x265-ZMNT | /data/media/.../TorrentLeech | ? |
| e36553b12dc118d8 | Dexter.S07.720p.x265-ZMNT | /pool/.../cross-seed/speedcd | ? |
| 127c38342cfedaf4 | River Monsters S07 | /data/media/.../TorrentDay | ? |
| 5caca88d29e64de4 | The.Diary.of.a.Teenage.Girl | /data/media/.../TorrentLeech | ? |
| 96d896ca35f42d93 | Transformers.Rise.of.the.Beasts | /data/media/.../DigitalCore (API) | ? |

### MISSING_DATA (28) — RT complete=1, files not found at qB path

All MISSING_DATA items are on TorrentDay, TorrentLeech, DocsPedia, yuscene, hawkeuno,
speedcd, or onlyencodes — their data was moved by the pilot rename but the filesystem
path no longer matches the cached qB save_path. These need `set_location` to update
qB's metadata, which is deferred to a later repair pass.

---

## Recheck Results (batch 1/5)

5 HEALTHY items received recheck + pause in qB:

| Hash | Recheck | After Pause | Verdict |
|------|---------|-------------|---------|
| 3af5a85cf2929786 | ok | stoppedDL | stayed in stoppedDL despite recheck |
| 2f64f48d0b3e965e | ok | stoppedDL | stayed in stoppedDL despite recheck |
| 08fc68ee4cc1937a | ok | stoppedDL | stayed in stoppedDL despite recheck |
| 0c72a60861f98df9 | ok | stoppedDL | stayed in stoppedDL despite recheck |
| 1376e795c9d9ca89 | ok | **stoppedUP** | successfully recovered |

**4/5 stayed in stoppedDL** after recheck. This suggests qB is classifying these as
incomplete downloads even though the data is fully present and RT confirms complete=1.
A `set_location` to update qB's save_path metadata may be needed before recheck,
so qB knows where to look for the data.

---

## Post-Audit State

| State | Count | Change |
|-------|-------|--------|
| stoppedUP | 4788 | +1 (1376e795 recovered) |
| stoppedDL | 114 | -1 (1376e795 recovered) |
| MISSING_DATA (deferred) | 28 | - |
| RT_INCOMPLETE (deferred) | 5 | - |

No RT mutations were performed. RT checking count was 0 at start, 0 during run,
and 0 at end (confirmed via sample spot-checks).

---

## Recommendations

1. **HEALTHY (82):** Batch recheck + re-pause in groups of 3-5, asynchronously.
   qB recheck does not cause RT harm. 4/5 stayed in stoppedDL — needs investigation.
   May require `set_location` before recheck to point qB to the correct path.

2. **MISSING_DATA (28):** These need `set_location` to update qB's save_path.
   Data exists at canonical path per RT. qB is looking at old path.

3. **RT_INCOMPLETE (5):** RT has not received the data or the torrent is incomplete.
   Investigate separately — may be pre-existing from failed downloads.
