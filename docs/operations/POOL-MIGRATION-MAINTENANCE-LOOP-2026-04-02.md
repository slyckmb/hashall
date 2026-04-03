# Pool Migration Maintenance Loop

Last updated: 2026-04-02

## Purpose

Provide a low-touch operator loop for the post-migration cleanup and restart lane:

1. recover the payload-sync tail if qB / RT are degraded
2. prune a very small reviewed set of stale `/pool/data` residue
3. reconcile the catalog after cleanup
4. resume `/stash -> pool-media` rehome only when the current batch is entirely `REUSE`

This is intended for the current state of the repo where:

- bulk `pool/data -> pool/media` migration is effectively complete
- only a small carve-out set remains on `/pool/data`
- qB still has to remain online because `payload sync` and `rehome apply` are still qB-backed

## Script

- `bin/run-pool-migration-maintenance-loop.sh`

## Current safety contract

The loop is intentionally narrow and fail-closed.

It will only auto-delete these exact stale roots:

- `/pool/data/cross-seed-link/SpeedCD/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED`
- `/pool/data/cross-seed-link/TorrentDay/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED`

And only if:

- no qB `torrent_instances` rows still save there
- no RT session rows still point there

It will only auto-apply a stash rehome round when the dry-run plan is entirely:

- `plan REUSE`

It will pause instead of continuing if:

- any candidate round includes non-`REUSE` decisions
- any apply or verify step reports failure
- any verify step reports `status=dest_missing`
- qB / RT recovery does not succeed
- the reviewed stale roots are still referenced by qB or RT

## Behavior

Each run does the following:

1. `bin/run-hashall-upgrade-scans.sh --payload-sync-only`
2. reviewed stale `/pool/data` residue cleanup
3. `scan /pool/data --hash-mode upgrade --drift-policy quick`
4. another `--payload-sync-only`
5. repeated `rehome auto --from stash --to pool-media --limit N`
6. auto-apply only when the batch is all `REUSE`

## Logs

Per-run logs are written to:

- `~/.logs/hashall/pool-migration-loop/`

The run-specific dry-run and apply logs are also kept there.

## Current observed state

As of this document update:

- the stale `How It's Made` roots under `SpeedCD` and `TorrentDay` are gone from `/pool/data`
- qB and RT are both healthy
- free space remains comfortable:
  - `/pool/data`: about `3.7T`
  - `/pool/media`: about `3.7T`
  - `/stash/media`: about `12T`
- the live loop has already progressed past:
  - payload-sync recovery
  - stale residue cleanup
  - `/pool/data` reconcile scan
  - at least one successful stash reuse wave

Because the loop may still be running when this file is read, the current source of truth for in-flight status is the newest log in:

- `~/.logs/hashall/pool-migration-loop/`

## Current manual follow-up after the first unattended run

The first unattended run exposed a specific residual class the loop must not auto-repeat:

- `06a8867d184c6972956307c7eea48ce16669e17c`
  - `Bullet.Train.2022.BluRay.1080p.TrueHD.Atmos.7.1.AVC.HYBRID.REMUX-FraMeSToR`
  - current save path: `/data/media/torrents/seeding/_qb-unique-repair/06a8867d184c6972956307c7eea48ce16669e17c`
  - verify status in unattended run: `dest_missing`
- `2bf62b9780fa8c394a8a4d9a57ebb5b924309645`
  - `The.Muppet.Christmas.Carol.1992.BluRay.1080p.DTS-HD.MA.5.1.AVC.REMUX-FraMeSToR`
  - current save path: `/data/media/torrents/seeding/cross-seed/PrivateHD`
  - verify status in unattended run: `dest_missing`
- `7c404604a9a478b5d35f109c72935023bd454ef2`
  - `Lego.Masters.US.S04.1080p.WEB-DL.AAC2.0.H.264-BAE`
  - current save path: `/data/media/torrents/seeding/_qb-unique-repair/7c404604a9a478b5d35f109c72935023bd454ef2`
  - verify status in unattended run: `dest_missing`

These three are why later rounds kept resurfacing the same families.

The next real progress step is **not** another unattended loop run. It is:

1. isolate these three torrents
2. decide the correct canonical target path for each shape variant
3. repair / migrate them individually
4. only then resume unattended stash reuse rounds

## Operator guidance

Use this loop for the current narrow cleanup / reuse phase only.

Do not broaden it yet to:

- carve-out families still rooted on `/pool/data`
- mixed `MOVE` / `REUSE` stash batches
- RT repair work
- arbitrary duplicate deletion outside the reviewed residue list
