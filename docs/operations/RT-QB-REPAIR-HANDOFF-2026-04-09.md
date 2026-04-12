# RT/QB Repair Handoff

Last updated: 2026-04-09

## Summary

This note replaces the older "wait for hashall fix" guidance.

Hashall has now repaired the broad RT payload-sync failure mode and repeated
`payload sync --source rt --upgrade-missing` runs have improved RT from:

- `5285 complete / 17 incomplete / 16 zero-file roots`

to:

- `5290 complete / 12 incomplete / 12 zero-file roots`

Recovered without redownloading:

- `12.Monkeys` x2
- `Peppermint` x2
- `The.World.At.War` x1

Bottom line:

- the remaining work is no longer a general hashall catalog bug
- the remaining work is a focused RT/qB repair lane
- use hashall for positive lead discovery and validation
- use docker/qB/RT runtime truth to choose among ambiguous candidates

## What Hashall Fixed

1. RT multi-file inventory no longer builds bogus `root/root` paths.
2. RT payload sync now carries expected `file_count` and `total_bytes` through
   to candidate matching.
3. Safe payload reuse now works for:
   - exact count/bytes/root-name matches
   - hash-specific `_rehome-unique/<torrent_hash>/...` matches
   - trailing-space path drift

## Current RT Residual Set

These `12` hashes still resolve to incomplete RT payload rows because RT points
at dead or unresolved paths:

- `0b236c5155a4cb0b651c7da579e022bfc47d016b` `E.T.The.Extra-Terrestrial...`
- `0b360a2ea3cb6ead1a49554ea25f62450ee1687a` `The.Matrix.Reloaded...`
- `1c6285d80aa32b7df861773354feed7a1a84bebd` `E.T.The.Extra-Terrestrial...`
- `259e2f0a58fd199fa40bdf42d1a3f526815bc510` `High.Plains.Drifter...`
- `44ee49efda9e7866f5e10da22e111ce8045963a8` `DTF.St.Louis.S01E06...`
- `4c0502689ed1932f05e6617fb4f173edef5bb864` `Saturday.Night.Live.S51E15...`
- `4ec707a43e3b3c37b24f333f01022a6e86b12799` `1996 - John Gilstrap - Nathan's Run@`
- `60d62c5db82307bf594666ac8ba0881644c18560` `Saturday.Night.Live.S51E16...`
- `6ca9022e73b2cee44d731c7bdac34188a543882e` `Saturday.Night.Live.S51E16...April.4.2026...`
- `7dafdd61e6b9d58d9721c12d8a3da2cde40fc776` `Queen - Queen II...`
- `8414bf677afa8434cd47a4710cc1cca070245ca4` `Saturday.Night.Live.S51E14...`
- `c5a827e36ebb032189bef898102b32b7f6e234dd` `Here.2024...`

## Repair Buckets

### Bucket A: plausible existing local content, but not yet unique enough to auto-bind

- `0b236c...` `E.T...` old `/downloads/complete/cross-seed/...`
- `1c6285...` `E.T...` old `_qb-finish/...`
- `0b360a...` `The.Matrix.Reloaded...`
- `c5a827...` `Here.2024...`
- `7dafdd...` `Queen - Queen II...`

Interpretation:

- good local content likely exists already
- hashall found one or more plausible complete payload candidates
- docker-side qB/RT evidence is needed to choose the right one safely

### Bucket B: stale dead-path RT entries with no proven complete payload match yet

- `259e2f...` `High.Plains.Drifter...`
- `44ee49...` `DTF.St.Louis.S01E06...`
- `4c0502...` `Saturday.Night.Live.S51E15...`
- `60d62c...` `Saturday.Night.Live.S51E16...`
- `6ca902...` `Saturday.Night.Live.S51E16...April.4.2026...`
- `8414bf...` `Saturday.Night.Live.S51E14...`
- `4ec707...` `1996 - John Gilstrap - Nathan's Run@`

Interpretation:

- RT still advertises them
- the recorded path is dead
- hashall does not currently see a verified complete payload candidate with the
  same count/size signature
- these should be investigated via qB runtime state, RT session files, and any
  archived local content before considering reacquire

## Fresh Hashall Leads For Docker

### 1. River Monsters S07

Hashall file-level sidecar search found:

- non-zero `.nfo` present:
  - `torrents/seeding/TorrentLeech/River.Monsters.S07.1080p.AMZN.WEB-DL.DDP2.0.H.264-NTb/River.Monsters.S07.1080p.AMZN.WEB-DL.DDP2.0.H.264-NTb.nfo`
  - size `53`
- zero-byte `.nfo` variants also exist under TorrentDay and `_qb-repair-v2`

Hashall payload-level search found multiple distinct complete payload identities:

- `TorrentLeech` complete: `7` files, `21950407743` bytes
- `PrivateHD` complete: `6` files, `21950407690` bytes
- `FileList.io` complete: `6` files, `21950407690` bytes
- `Aither` complete: `11` files, `40548745392` bytes
- `YUSCENE` complete: `11` files, `40339883483` bytes
- nested wrapper variants also exist for `Aither` and `YUSCENE`

Implication:

- this is not a "no bytes anywhere" case
- use tracker/hash/runtime context to choose the correct family before merging

### 2. Transformers Rise of the Beasts

Hashall file-level sidecar search found:

- non-zero `.nfo` candidates:
  - `torrents/seeding/movies/Transformers.Rise.of.The.Beasts.../Transformers...EnC0de.nfo`
    size `4677`
  - `torrents/seeding/TorrentDay/Transformers Rise of the Beasts.../Transformers...mkv.nfo`
    size `1241`
- `.txt` files exist but are zero-byte in the DigitalCore / rtorrent /
  `_qb-repair-v2` locations

Hashall payload-level search found several complete payload identities:

- x265 / Atmos EnC0de complete: `6` files, `21089898211` bytes
- DigitalCore complete: `3` files, `21082527408` bytes
- TorrentDay complete: `2` files, `12191158871` bytes
- HiDt single-file variants complete: `1` file, `12191157630` bytes

Implication:

- there are usable local payload families and sidecars
- choose the correct one by tracker/hash/runtime evidence, not by name only

### 3. Diary of a Teenage Girl

Hashall file-level search found:

- complete movie payload present under TorrentLeech and the library path
- `.nfo` exists but is zero-byte
- `Sample.mkv` exists but is zero-byte:
  - `torrents/seeding/TorrentLeech/The.Diary.of.a.Teenage.Girl.../Sample.mkv`

Hashall payload-level search found:

- complete payload:
  - `payload_hash=2fb707648f1e032844aae35b866a4b50a306bb28a93481de17e7f27482a30acc`
  - `7` files
  - `24172941329` bytes

Implication:

- main content exists locally
- the blocker is sidecar/sample quality, not primary movie bytes

### 4. Dexter S07

Hashall file-level search shows active episode files under:

- `torrents/seeding/cross-seed/TorrentLeech/Dexter.S07.720p.x265-ZMNT/...`
- `torrents/seeding/cross-seed-link/SpeedCD/Dexter.S07.720p.x265-ZMNT/...`

Hashall payload-level search shows:

- incomplete path:
  - `/stash/media/torrents/seeding/cross-seed/TorrentLeech/Dexter.S07.720p.x265-ZMNT/Dexter.S07.720p.x265-ZMNT`
- complete payload identities:
  - `/stash/media/torrents/seeding/cross-seed/TorrentLeech/Dexter.S07.720p.x265-ZMNT`
  - `/stash/media/torrents/seeding/cross-seed/SpeedCD/Dexter.S07.720p.x265-ZMNT`
  - `/stash/media/torrents/seeding/cross-seed-link/SpeedCD/Dexter.S07.720p.x265-ZMNT`
  - all share payload hash `53f311a1e39c6fd17248825fafa57f5f94eeea616f8e863e32b5481cf9d12a5e`
  - `13` files
  - `5757836898` bytes

Implication:

- hashall already sees a stable alternate payload identity
- do not keep chasing same-name dead wrapper paths
- use the complete payload family above as the donor authority

### 5. 12 Monkeys

Resolved by hashall during the latest repair wave:

- `65c69d...` -> reused complete payload `#13042`
- `af86f4...` -> reused complete payload `#12343`

Hashall file-level search did **not** find a non-zero `.nfo` for:

- `12.Monkeys.1995.REMASTERED.1080p.BluRay.x265.10bit.DTS-HD-MA.5.1-UnKn0wn*.nfo`

Implication:

- primary content is already recovered
- `.nfo` remains unresolved in current catalog

### 6. Avatar Fire and Ash

Hashall now shows strong local authority:

- main movie file present in multiple seeding locations
- `TorrentDay` `.mkv` and `.nfo` variants exist but are zero-byte
- multiple active seeded copies exist under:
  - `radarr`
  - `TorrentLeech`
  - `OnlyEncodes (API)`
  - `seedpool (API)`
  - `YUSCENE (API)`
  - `PrivateHD`
  - `Darkpeers (API)`

Implication:

- no need to treat Avatar as "no authority"
- the main payload bytes clearly exist
- if still blocked, the remaining issue is path/session/sidecar-specific

## How Docker Agent Should Use Hashall

For each candidate hash under repair:

1. Ask hashall for current complete payload candidates.
2. Prefer exact `file_count` + `total_bytes` matches.
3. Prefer `_rehome-unique/<torrent_hash>/...` paths when present.
4. Use canonical host paths only.
5. Do **not** use a hashall "no candidate" result as proof that no bytes exist.

## Recommended Next Execution Order

1. Repair ambiguous-but-promising RT residuals first:
   - `E.T` x2
   - `The.Matrix.Reloaded`
   - `Here.2024`
   - `Queen - Queen II`
2. Run sidecar merge/repair for:
   - `River Monsters S07`
   - `Transformers`
   - `Diary of a Teenage Girl`
3. Use the complete `Dexter.S07` payload family as the alternate identity donor.
4. Re-check `Avatar Fire and Ash` with the newly confirmed authority and downgrade
   it from "blocked for no authority" to "repairable with local bytes".
5. Only then revisit the stale `/downloads/complete/...` RT rows with qB/runtime
   evidence to determine whether they can be rebound or need reacquire.

## Validation Loop

After each docker-side repair wave, rerun:

```bash
PYTHONPATH=src python -m hashall.cli payload sync --source rt --upgrade-missing
```

Success signal:

- `incomplete payloads` drops
- `missing in catalog` drops
- no new zero-file upgrade roots appear outside the current residual set
