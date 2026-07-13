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
- Decide stash-vs-pool home for the whole same-inode payload group, not for one
  torrent at a time. The canonical path shape is per torrent, but the storage
  home is group-wide. If any same-inode member has a hardlink in a media library
  path such as `movies/`, `shows/`, `books/`, `music/`, or `audiobooks/`, the
  entire group stays on stash. Only groups with no media-library consumers are
  eligible for pool placement.
- Repeat the group-home check after Plan B creates a new verified variant. A
  split/redownload creates a new byte variant and therefore a new group
  candidate; do not assume the representative's current directory is the final
  canonical home.
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
- same-inode member paths for the repaired/new variant group;
- placement audit result: `stash_required` if any same-inode member is in a
  media library path, otherwise `pool_eligible`;
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

## Failed-Piece Analysis Gate

Before starting a Plan B download, map the failed pieces to the torrent's
expected files. This distinguishes a true media-byte mismatch from a missing
sidecar-only problem.

Current target path:

```bash
make client-drift-verify-pieces HASH=<hash> SHOW=1 MAP=1
```

Exact split/quarantine tree:

```bash
make client-drift-verify-pieces HASH=<hash> QUARANTINE_ROOT="/path/to/.invalid-for-<hash>" SHOW=1 MAP=1
```

Machine-readable report:

```bash
make client-drift-verify-pieces HASH=<hash> PAYLOAD_ROOT="/path/to/payload-root" JSON=1
```

Compare failed-piece byte ranges against another exact payload root:

```bash
make client-drift-verify-pieces HASH=<hash> \
  QUARANTINE_ROOT="/path/to/bad-or-suspect-payload" \
  COMPARE_ROOT="/path/to/known-good-or-candidate-payload" \
  JSON=1
```

Interpretation:

- `sidecar_only_missing`: repair or fetch the sidecar first; do not assume a
  media variant.
- `sidecar_media_boundary_piece`: the failed piece spans a sidecar and media
  bytes; treat it as ambiguous until `COMPARE_ROOT` proves which byte range
  differs.
- `media_piece_mismatch`: the media file bytes do not match the torrent piece
  map; Plan B split/redownload is appropriate if no verified sibling source
  exists.
- `media_piece_missing_or_truncated`: the media file is missing or too short at
  the mapped byte range; Plan B or a verified donor source is needed.
- `layout_missing`: the expected tree is absent or the wrong root was supplied;
  fix the path/root before concluding content differs.
- `comparison_classification=sidecar_only_diff`: the sidecar range differs but
  the mapped media range matches the compare root; try sidecar repair first.
- `comparison_classification=media_only_diff`: the mapped media range differs;
  this is a real media-byte variant or corruption, not a sidecar-only issue.
- `comparison_classification=sidecar_and_media_diff`: both ranges differ; a
  fresh tracker-approved payload is needed before reusing either set of bytes.
- `comparison_classification=no_span_diff`: the compared roots have identical
  bytes in the failed ranges; the compare root is not a useful known-good proof
  for this target torrent.

After a split, the live target may contain zero-byte placeholder files. In that
case, use `--quarantine-root` or `QUARANTINE_ROOT=...` to inspect the old bytes
that were moved aside, not the new empty target directory.

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
8. Run a placement audit on the newly verified variant group. Enumerate all
   same-inode paths and check media-library prefixes. If any member is in a
   media library path, classify the whole group as `stash_required`; otherwise
   classify it as `pool_eligible`.
9. Run hash-scoped DB sync for the failed hash and any affected sibling hash.
10. Record the final outcome in the validation report and OP/JOB tracking.

Do not delete the renamed invalid file/tree until the comparison is recorded
and the healthy sibling has been rechecked or otherwise proven unaffected.

## Repair Plan C: Expected-Incomplete Rehome

Use this when the suspect payload is not complete for the failed torrent, but it
is still the best known local byte set and should be parked in the correct
canonical pool/stash location while waiting for seeds. This is the Dexter
S02/S07 SpeedCD case: the source bytes fail exactly one piece, piece `0`,
classified as `sidecar_media_boundary_piece`, with no missing files. That is an
acceptable incomplete wait state, not a verified 100 percent repair.

Plan C success is deliberately different from Plan A:

- RT should point at the canonical target tree and be active/waiting or
  stalled-DL after recheck/start.
- qB should point at the matching passive save path and remain `stoppedDL`.
- The offline piece result must still match the expected incomplete gate:
  known failed piece(s), expected classification, and no surprise missing files.
- No cleanup deletion happens until after copy/repoint/recheck verification and
  explicit operator cleanup approval.

Steps:

1. Verify the source payload against the failed torrent with failed-piece
   mapping enabled. For Dexter SpeedCD, the expected proof is one failed piece:
   `piece_index=0`, `classification=sidecar_media_boundary_piece`,
   `pieces_missing=0`.
2. Build a source-inode manifest. It must list every same-inode catalog path,
   protect live/media-library paths, and identify only repair/staging residue as
   cleanup candidates.
3. Build an incomplete-rehome dry-run plan. The plan must show:
   source root(s), target root, target readiness, rsync argv, qB save path, RT
   target directory, expected post-recheck states, and cleanup manifest summary.
4. Build the pilot dry-run manifest from the plan. This is the final
   pre-approval artifact: it restates current source/target stats, the copy
   command, the RT/qB operation order, and the cleanup gate. It is not live
   approval.
5. Confirm qB save path is the parent save path for multi-file torrents. Do not
   set qB save path equal to the payload root if that would make qB expect a
   nested `<info_name>/<info_name>/...` tree.
6. For the live pilot, copy the source bytes to the target with `rsync -aHAX`.
   Zero-byte placeholder targets may be replaced; nonzero existing target files
   block the plan.
7. Repoint RT to the target payload directory, force recheck, and start only so
   RT can wait for seeds. Do not require completion for Plan C.
8. Repoint or patch qB to the parent save path, force recheck, and leave qB
   stopped/passive.
9. Re-run offline piece verification against the target tree and confirm it
   still matches the expected incomplete gate.
10. Build the post-pilot validation report from the live execute report, target
    verify JSON, and qB/RT state snapshots. The report must be
    `validated_ready_for_cleanup_approval` before cleanup is discussed.
11. Run targeted DB sync/refresh for affected hashes.
12. Only after the clients and offline verifier match the plan, ask for explicit
    cleanup approval. Cleanup must remove stale repair/staging direntries, not
    protected live sibling paths. Collapse `/data` and `/stash` aliases, but do
    not collapse distinct stale hardlink locations such as `_qb-finish` and
    `RecycleBin`; both must be removed if both are stale.
13. Add a separate source-payload cleanup stage for space reclamation. This is
    not the same approval as repair/staging cleanup. Source cleanup may delete
    the original stash/data source tree only after a fresh client-reference scan
    proves no qB or RT torrent still has that exact release root as its
    `content_path`, `root_path`, or RT `save_path`, no media-library path anchors
    the inode group, and the validated pool target remains intact. If another
    tracker sibling still uses the old source root, block source cleanup for that
    root until that sibling is rehomed, retired, or explicitly excluded by the
    operator.

Plan C is not a downloader. If the item has no seeds, it is allowed to remain
in the expected incomplete waiting state after rehome. The goal is to make the
client paths truthful and recoverable while preserving rollback evidence until
cleanup is explicitly approved.

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

Use `hashall client-drift source-inode-manifest` and
`hashall client-drift incomplete-rehome-plan` for Plan C dry-runs.

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

Plan C source-inode manifest:

```bash
.venv/bin/python -m hashall.cli client-drift source-inode-manifest \
  --source-root "/data/media/torrents/seeding/SpeedCD/Dexter.S02.720p.x265-ZMNT" \
  --target-root "/pool/media/torrents/seeding/cross-seed/speedcd/Dexter.S02.720p.x265-ZMNT" \
  --catalog ~/.hashall/catalog.db \
  --output /tmp/HASH-source-inode-manifest.json
```

Plan C incomplete-rehome dry-run:

```bash
.venv/bin/python -m hashall.cli client-drift incomplete-rehome-plan HASH \
  --source-root "/data/media/torrents/seeding/SpeedCD/Dexter.S02.720p.x265-ZMNT" \
  --target-root "/pool/media/torrents/seeding/cross-seed/speedcd/Dexter.S02.720p.x265-ZMNT" \
  --verify-json /tmp/HASH-verify-pieces.json \
  --qb-save-path "/pool/media/torrents/seeding/cross-seed/speedcd" \
  --rt-target-directory "/pool/media/torrents/seeding/cross-seed/speedcd/Dexter.S02.720p.x265-ZMNT" \
  --catalog ~/.hashall/catalog.db \
  --output /tmp/HASH-incomplete-rehome-plan.json
```

Plan C pilot operation dry-run:

```bash
.venv/bin/python -m hashall.cli client-drift incomplete-rehome-pilot-dry-run \
  --plan /tmp/HASH-incomplete-rehome-plan.json \
  --output /tmp/HASH-incomplete-rehome-pilot-dryrun.json
```

Equivalent Make target:

```bash
make client-drift-incomplete-rehome-pilot \
  PLAN=/tmp/HASH-incomplete-rehome-plan.json \
  OUTPUT=/tmp/HASH-incomplete-rehome-pilot-dryrun.json
```

Plan C guarded live pilot:

```bash
make client-drift-incomplete-rehome-execute \
  PILOT=/tmp/HASH-incomplete-rehome-pilot-dryrun.json \
  APPLY=1 \
  APPROVAL="approve Plan C HASH no cleanup" \
  OUTPUT=/tmp/HASH-incomplete-rehome-execute-live.json
```

The approval string must include `Plan C`, the target hash, and `no cleanup`.
This command performs copy/repoint/recheck only. It does not delete stale source
paths; cleanup remains a separate approval after verification.

Plan C qB/RT state snapshots:

```bash
make client-drift-incomplete-rehome-snapshot \
  HASH=HASH \
  SIDE=qb \
  OUTPUT=/tmp/HASH-qb-snapshot.json

make client-drift-incomplete-rehome-snapshot \
  HASH=HASH \
  SIDE=rt \
  OUTPUT=/tmp/HASH-rt-snapshot.json
```

Plan C post-pilot validation:

```bash
make client-drift-incomplete-rehome-post-validate \
  EXECUTE_REPORT=/tmp/HASH-incomplete-rehome-execute-live.json \
  TARGET_VERIFY_JSON=/tmp/HASH-target-verify-pieces.json \
  QB_JSON=/tmp/HASH-qb-snapshot.json \
  RT_JSON=/tmp/HASH-rt-snapshot.json \
  OUTPUT=/tmp/HASH-post-pilot-validation.json
```

If `QB_JSON` or `RT_JSON` is omitted, the validator warns and still checks the
execute report plus target piece gate. Cleanup approval should wait for both
client snapshots.

Plan C source-payload cleanup dry-run:

```bash
# 1. List exact client references before deleting any original source tree.
# A source root is blocked if any qB content_path/root_path or RT save_path
# exactly equals that release root.

# 2. Delete only after the dry-run proves:
# - post-pilot validation is validated_ready_for_cleanup_approval
# - repair/staging cleanup has been planned or completed
# - no qB/RT exact client reference remains on the old source root
# - no media-library path anchors the inode group
# - the pool target still verifies against the expected Plan C piece gate
```

For Dexter S02/S07, the intended sequence after Plan C validation is:

- First cleanup: remove only stale repair/staging paths from `.rehome-cleanup-stage`,
  `_qb-repair-v2`, `_qb-finish`, and `RecycleBin`.
- Second cleanup: reclaim old source payloads when they are no longer exact
  qB/RT roots. Dexter S02 SpeedCD source is eligible only if the fresh exact
  client-reference scan remains empty. Dexter S07 must keep any source root still
  used by the TorrentLeech sibling `288305f401ff...` until that sibling is moved
  or intentionally retired.

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

Plan B placement audit:

```bash
.venv/bin/python bin/rt-qb-variant-split-redownload.py --dry-run \
  --placement-audit \
  --placement-scan-root /data/media/torrents/seeding \
  --placement-scan-root /data/media/movies \
  --placement-scan-root /data/media/shows \
  --placement-member-path /path/to/compatible/sibling-a \
  --placement-member-path /path/to/compatible/sibling-b \
  --hash HASH \
  --report-json .agent/reports/<run>/HASH-placement-audit.json
```

The placement audit is read-only. It scans same-inode paths for the current
payload plus any `--placement-member-path` entries that are proposed compatible
members of the repaired variant group. It emits `placement_audit.group_home`:

- `stash_required`: at least one same-inode member is in a media-library path,
  so the whole newly verified variant group must stay on stash.
- `pool_eligible`: no media-library member was found in the scanned roots, so
  pool placement may be considered after the normal canonical path, free-space,
  and client-routing checks.
- `unknown_requires_manual_review`: the scan hit `--placement-max-files` before
  completing, the payload was not present in the scan roots, or a proposed
  member path was missing. Narrow the scan roots to the suspected group and
  media-library roots, fix the missing path, or raise the limit; do not treat
  this as pool-eligible.

Placement matrix for one repaired representative plus two 99.* candidates:

| Representative group | Candidate A | Candidate B | Expected action |
| --- | --- | --- | --- |
| no media anchor | neither candidate is compatible | neither candidate is compatible | Audit representative only. If no media anchor is found, it may be `pool_eligible`; do not include incompatible candidates. |
| no media anchor | compatible, no media anchor | compatible, no media anchor | Audit with both `--placement-member-path` values. If the payload and both candidates are found and no media member appears, result is `pool_eligible`. |
| no media anchor | compatible, media anchor | compatible, no media anchor | Audit with both member paths. Any media anchor on either candidate makes the proposed combined group `stash_required`. |
| no media anchor | compatible, media anchor | compatible, media anchor | Audit with both member paths. Result is `stash_required`. |
| media anchor | compatible or not | compatible or not | Representative audit is already `stash_required`; compatible candidates inherit stash home if added. Incompatible candidates stay out of the group. |
| any | compatible candidate path missing | any | Result is `unknown_requires_manual_review`; do not hardlink or rehome until the path is resolved. |
| any | scan roots do not include the representative or candidate paths | any | Result is `unknown_requires_manual_review`; widen/fix scan roots. |
| any | scan hits file limit before completion and no media anchor was found | any | Result is `unknown_requires_manual_review`; do not treat as pool-eligible. |
| any | scan hits file limit after finding a media anchor | any | Result remains `stash_required`; positive media-library evidence wins over incomplete scan uncertainty. |

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
