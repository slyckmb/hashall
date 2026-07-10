# RT/qB 99 Percent Content-Variant Repair Runbook

**Status:** Active
**Created:** 2026-07-10
**Applies to:** RT/qB torrents stuck at 99.* percent where a sibling torrent has
apparently complete bytes but the failed torrent's piece map does not fully
match the currently shared payload file.

## Plain-language Goal

Make each 99.* item either:

1. become a verified 100 percent seed in both clients, or
2. be explicitly classified as not repairable from known sibling bytes.

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

## Safety Rules

- Never start the 99.* torrent in its current shared-inode location.
- Never repair by filename or release name alone.
- Never overwrite an existing target file unless the tool proves it is already
  the same inode and expected size.
- Never repoint RT or qB until the target tree verifies against the target
  `.torrent` offline.
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

## Repair Plan

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

## Tooling

Use `bin/torrent-sibling-hardlink-repair.py` for this failure mode.

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

## Outcome Classes

- `repaired`: source and target both verify, clients recheck to 100 percent, DB
  sync shows complete payload.
- `source-not-compatible`: candidate source exists but fails target torrent
  piece verification.
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
repaired from verified sibling bytes must be classified with evidence rather
than left ambiguous.
