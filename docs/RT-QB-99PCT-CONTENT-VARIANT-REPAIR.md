# RT/qB 99 Percent Content-Variant Repair Runbook

**Status:** Active
**Created:** 2026-07-10
**Applies to:** RT/qB torrents stuck at 99.* percent where a sibling torrent has
apparently complete bytes but the failed torrent's piece map does not fully
match the currently shared payload file.

## Plain-language Goal

Make each 99.* item either:

1. become a verified 100 percent seed in both clients, or
2. prove the sibling is a real content variant by splitting the failed torrent
   away from the sibling inode, redownloading the target bytes, and comparing
   the resulting files.

Do not let an incomplete torrent write into an inode used by a healthy sibling.

## Failure Mode

This runbook is for the specific case where:

- qB or RT shows a torrent near 100 percent, usually `99.*`;
- RT may report `Download registered as completed, but hash check returned
  unfinished chunks`;
- the payload file or files are hardlinked to one or more 100 percent sibling
  torrents;
- at least one sibling has the same apparent release/file size, but the failed
  torrent's expected piece map may differ.

The important rule: matching names are not required, and matching names are not
proof. A valid payload is defined by the torrent metadata: path tree, file
sizes, and byte content. The source bytes must verify against the target
`.torrent` before they may be used.

The practical symptom is subtle: rTorrent does not necessarily show a loud
write error. It can mark the torrent stopped after a failed completion hash
check and refuse to redownload the bad piece while the path is still attached to
a file it previously treated as complete, especially when that file is also a
hardlinked 100 percent sibling. That is why these cases look like detective work
instead of an obvious client failure.

A second symptom is that manually triggering `d.start` can appear to do nothing:
the item remains stopped/paused because it still has no isolated writable target
for the bytes that differ from its own piece map. The repair is not "start
harder"; the repair is to split the failed torrent away from the shared inode
first, then start the split item.

Do not redownload every member of a suspected variant group. One representative
fresh download is enough to prove whether that group has a second byte variant.
After that representative verifies, test the other target torrents against the
new payload and only download another item if verification fails.

## Safety Rules

- Never start the 99.* torrent in its current shared-inode location.
- Never expect RT to repair the bad piece in place while the failed torrent is
  still pointed at a complete/shared sibling inode.
- Never repair by filename or release name alone.
- Never overwrite an existing target file unless the tool proves it is already
  the same inode and expected size.
- Never repoint RT or qB until the target tree verifies against the target
  `.torrent` offline.
- If the sibling/source fails target piece verification, do not stop at
  classification. That is the trigger to rename the invalid target file/tree out
  of the expected path, let the failed torrent download fresh target bytes into
  a unique path, and then compare old vs new bytes.
- Run `payload sync --hash` after a successful repair, and do not run a
  whole-catalog orphan prune as part of a hash-scoped sync.

## Required Evidence

For each hash, record:

- qB state, progress, amount left, save path, and tags;
- RT `d.directory`, `d.state`, `d.complete`, `d.left_bytes`, `d.message`;
- `.torrent` info name, single-file vs multi-file, file count, total size;
- current filesystem inode/dev/link count for payload files;
- DB payload rows for the failed hash and candidate sibling hashes;
- offline piece verification result for the candidate source bytes;
- offline piece verification result for the constructed target tree;
- post-recheck RT/qB state;
- post-sync DB payload status.

## Repair Plan A: Verified Sibling Bytes

1. Refresh the catalog and client state for only the target hash when possible.
2. Find candidate sibling bytes using the DB, RT/qB state, file size, and
   payload-hash evidence.
3. Verify the candidate source against the failed torrent's `.torrent` file.
4. Build the exact target payload tree expected by the failed torrent:
   single-file torrents use `save_path/info_name`; multi-file torrents use
   `save_path/info_name/<torrent file paths>`.
5. Hardlink the target tree to the verified source bytes.
6. Verify the target tree offline against the failed torrent's `.torrent`.
7. Repoint RT and qB to the target save path and force recheck.
8. Start RT only if the post-recheck result is complete.
9. Confirm qB is `stoppedUP` with `progress=1.0` and `amount_left=0`.
10. Run a hash-scoped DB sync and confirm the DB payload is complete.

## Repair Plan B: Split, Rename, and Redownload

Use this when Plan A proves the sibling/source bytes do not match the failed
torrent. This is the E.T. lesson: the old shared stash inode did not satisfy
the failed seedpool/Darkpeers/DigitalCore target torrents, so the seedpool
target was split away, its invalid path was renamed/cleared, and seedpool
downloaded a fresh file. That fresh file proved a second variant exists in the
wild. Only after that new seedpool file verified did the other compatible
target torrents get per-tracker views hardlinked to the new verified variant.

1. Stop the failed torrent in both clients.
2. Record every expected target path, inode, size, and hardlink count.
3. Rename the invalid file or payload tree at the failed torrent's expected path
   to a quarantine name that includes the target hash, for example
   `.invalid-for-HASH`.
4. Confirm the healthy sibling's own path still exists and still points to its
   original inode. Renaming one hardlink path must not remove the sibling's
   directory entry.
5. Start or recheck/resume only one representative failed torrent for the group,
   so it writes fresh bytes into the now-empty expected target path. Stop for
   operator tracker/freeleech choice before starting unless tooling has recorded
   proof that the selected source is freeleech.
6. When the failed torrent reaches 100 percent, stop it and verify it offline
   against its `.torrent`.
7. Compare the new verified target file/tree against the renamed invalid source:
   same bytes means prior client metadata/path state was wrong; different bytes
   means they are real content variants and must remain separate payloads.
8. Run hash-scoped DB sync for the failed hash and any affected sibling hash.
9. Record the final outcome in the validation report and OP/JOB tracking.

Do not delete the renamed invalid file/tree until the comparison is recorded
and the healthy sibling has been rechecked or otherwise proven unaffected.

## E.T. Reference Pattern

The E.T. repair is the reference case for this failure mode:

| Variant | Hashes | Location | Payload hash | Inode evidence | Meaning |
| --- | --- | --- | --- | --- | --- |
| old/original | `b1722c003cd9`, `87b6670c265e`, `f8c7e9b445ee` plus related stash paths | `/stash` and `/data` tracker views | `2a23eeb97cc253a1` | `dev=49 ino=67281 nlink=9` | Healthy sibling group, but not valid for the seedpool/Darkpeers/DigitalCore target piece maps. |
| new seedpool variant | `0b236c5155a4`, `1c6285d80aa3`, `4b4a1747e01b` | `/pool/media/torrents/seeding/cross-seed/{seedpool,Darkpeers,DigitalCore} (API)/...` | `3d5fd5f8d7fb6996` | `dev=45 ino=50291 nlink=3` | Freshly downloaded/split variant that verifies for those target torrents. |

Correct lesson: Plan B proves whether a second variant exists. Plan A may then
reuse the newly verified variant for other target torrents whose piece maps
accept it. Do not describe the initial E.T. repair as "old sibling bytes
verified"; they did not.

## Tooling

Use `bin/torrent-sibling-hardlink-repair.py` for Plan A and
`bin/rt-qb-variant-split-redownload.py` for Plan B.

Single-file source:

```bash
.venv/bin/python bin/torrent-sibling-hardlink-repair.py --dry-run \
  --source-file "/path/to/verified/source/file" \
  --hash HASH \
  --target "HASH=/path/to/target/save_path"
```

Multi-file source:

```bash
.venv/bin/python bin/torrent-sibling-hardlink-repair.py --dry-run \
  --source-dir "/path/to/verified/source/save_path/or/info_name" \
  --hash HASH \
  --target "HASH=/path/to/target/save_path"
```

Live repair requires replacing `--dry-run` with `--apply` and should include
`--allow-start-if-complete` only after the dry-run source verification is clean.

Plan B split/redownload dry-run:

```bash
.venv/bin/python bin/rt-qb-variant-split-redownload.py --dry-run \
  --hash HASH \
  --report-json .agent/reports/<run>/HASH-split-dryrun.json
```

Plan B limited live pilot:

```bash
.venv/bin/python bin/prowlarr-freeleech-proof.py \
  --query "Release title" \
  --output .agent/reports/<run>/HASH-freeleech-proof.json

.venv/bin/python bin/rt-qb-variant-split-redownload.py --apply \
  --allow-start-download \
  --freeleech-proof .agent/reports/<run>/HASH-freeleech-proof.json \
  --hash HASH \
  --report-json .agent/reports/<run>/HASH-split-pilot-live.json
```

If the item has already been split and contained/stopped, resume only the
already-isolated target path instead of quarantining again:

```bash
.venv/bin/python bin/rt-qb-variant-split-redownload.py --apply \
  --start-existing-split \
  --allow-start-download \
  --freeleech-proof .agent/reports/<run>/HASH-freeleech-proof.json \
  --hash HASH \
  --report-json .agent/reports/<run>/HASH-start-existing-split-live.json
```

The Plan B tool is intentionally hash-scoped and dry-run first. Live mode stops
the RT item, renames only that torrent's expected payload path to an
`.invalid-for-HASH` quarantine name, and runs `d.check_hash`. It starts RT only
when `--allow-start-download` is explicit and either
`--operator-download-approval` or a JSON `--freeleech-proof` report with
`freeleech_proven=true` is also present. The expected successful pilot symptom
is a new target inode with `nlink=1` and RT `d.state=1` with either a nonzero
download rate or normal stalled-download behavior while waiting for seeds.
`--start-existing-split` uses the same start gate but first blocks if the target
path is missing, still shares an inode, is already complete, or contains another
RT session directory below it.

`bin/prowlarr-freeleech-proof.py` is read-only. It searches Prowlarr and treats
freeleech as proven only when Prowlarr returns an explicit zero download-volume
field (`downloadVolumeFactor=0`, `downloadVolume=0`, or `downloadFactor=0`) or a
freeleech flag in `indexerFlags`, `flags`, or `releaseFlags`. Seed count,
tracker name, or title text alone is not proof.

If a multi-file payload root contains another RT session directory below it, do
not quarantine the whole root. That would break the sibling view. Use a more
targeted file-level split or a unique per-hash target tree.

## Outcome Classes

- `direct-repaired`: existing source and target both verify, clients recheck to
  100 percent, DB sync shows complete payload.
- `redownload-repaired`: Plan B redownload produces a new verified payload for
  the failed torrent; compatible sibling target torrents may then be hardlinked
  to that new variant.
- `needs-split-redownload`: candidate source exists but fails target torrent
  piece verification; next step is Plan B, not terminal classification.
- `variant-proven`: after Plan B, the newly downloaded verified target bytes
  differ from the renamed invalid sibling bytes.
- `duplicate-proven`: after Plan B, the newly downloaded verified target bytes
  match the renamed invalid bytes; investigate client/fastresume/path metadata
  before deleting anything.
- `no-verified-source`: no sibling source can be proven against the target
  torrent.
- `blocked-existing-target`: target path already contains non-matching files
  and needs an explicit split/rename decision before live repair.
- `waiting-for-seeds`: tracker announces successfully but no verified sibling
  source exists; leave as incomplete and monitor rather than pretending it is
  fixed.

## Current Driver

The active objective is to run this process over the remaining qB 99.* stoppedDL
set and reduce the actionable content-variant set to zero. Items that cannot be
repaired from verified sibling bytes move to Plan B so the system proves whether
the files are true variants instead of leaving the failed target attached to an
invalid sibling inode.
