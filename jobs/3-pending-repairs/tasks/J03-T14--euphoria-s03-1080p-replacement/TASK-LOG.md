# J03-T14 — Euphoria S03: 2160p → 1080p Replacement — Task Log

## Summary

Removed the incorrectly-added 2160p season pack and replaced it with a proper
1080p season pack per the 1080p-only quality rule.

---

## Step 1: Erase the 2160p torrent and its partial data ✅

- **RT erase**: `A39C355D` (`Euphoria.US.S03.2160p.AMZN.WEB-DL.DDP5.1.Atmos.H.265-Kitsune`) — erased via `d.erase`
- **qB removal**: Not present in qB (T13 had only stopped it in RT)
- **Data removal**: `rm -rf /data/media/torrents/seeding/sonarr/Euphoria.US.S03.2160p.AMZN.WEB-DL.DDP5.1.Atmos.H.265-Kitsune`
  - Contained 8x zero-byte files + 1x ~9GB partial (ep7 = ~1.6%)
- **Verified**: 0 2160p items remain in RT, 0 2160p directories on disk

## Step 2: Search Prowlarr for 1080p Euphoria S03 season pack ✅

**Prowlarr API key**: Found at `/mnt/config/secrets/prowlarr/prowlarr-api-key.env`

**Best candidate found**:
- **Title**: `Euphoria.US.S03.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune`
- **Size**: 35.6 GB
- **Indexer**: seedpool (API) — also available on TorrentLeech (200 seeders, freeleech)
- **Quality check**: 1080p only, no 2160p/4K/UHD/HDR — compliant with quality rule

## Step 3: Add the 1080p season pack ✅

- **method**: Downloaded .torrent via Prowlarr API → `load.raw_start` into RT
- **hash**: `406FF76C`
- **Label**: `tv`
- **Directory**: `/data/media/torrents/seeding/sonarr/Euphoria.US.S03.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-Kitsune`
- **Status**: Active, downloading at ~2 MB/s
- **qB sync**: Deferred to RT completion hook (`rt_qb_mirror_enqueue.sh`)

## Step 4: Verify ✅

- 2160p torrent fully erased from RT and disk: yes
- 1080p season pack added and downloading: yes
- No 2160p items remain in RT: confirmed (0)

---

## Required Artifacts

| Artifact | Value |
|---|---|
| step1_2160p_erased | yes |
| step1_partial_data_removed | yes |
| step2_1080p_pack_found | yes |
| step2_pack_size_gb | 35.6 |
| step3_pack_added | yes |
| step3_rt_state | 1 (downloading) |
| step4_euphoria_tracker_issue_remaining | 0 |

---

**Completed**: 2026-06-13
**Agent**: Claude
