# J51 99 Percent Variant Split Validation - 2026-07-10

## Goal

Validate the documented repair process for RT/qB 99.* items that remain
stopped/paused after start attempts because their payload path is still attached
to a complete hardlinked sibling inode.

## Loop 1 - Code Walk

Finding: `bin/torrent-sibling-hardlink-repair.py` correctly covers Plan A. It
verifies candidate sibling bytes against the failed torrent and blocks when the
piece map does not match.

Gap: there was no first-class Plan B executor for the required
split/rename/redownload flow. The manual procedure existed in docs, but no
hash-scoped tool produced dry-run/live reports for the paused-after-start symptom.

Fix: added `bin/rt-qb-variant-split-redownload.py`.

## Loop 2 - Simulation

Added `tests/test_rt_qb_variant_split_redownload.py`.

Validated:

- dry-run reports the failed payload path, quarantine path, and shared inode
  detection;
- live mode renames only the failed torrent's path, leaving the sibling hardlink
  path intact;
- RT mutation order is `d.stop`, rename to quarantine, `d.check_hash`, `d.start`;
- hash prefixes resolve against RT session `.torrent` files.

Focused validation passed initially:

```text
tests/test_rt_qb_variant_split_redownload.py 3 passed
tests/test_rtorrent_safe_start.py 8 passed
tests/test_torrent_sibling_hardlink_repair.py 2 passed
```

After the download-choice and nested-session hardening, focused validation
passed again with 52 tests.

## Loop 3 - Dry Run Against Current 99.* Set

Reports live under:

` .agent/reports/j51-variant-split-validation-20260710/`

| Hash | RT state | Left bytes | Shared inode | Dry result |
| --- | ---: | ---: | --- | --- |
| `127c38342cfe` | `1` | `16777216` | yes | planned |
| `245f2bce6afa` | `1` | `2097152` | yes | planned |
| `5feb771c9b7f` | `0` | `524288` | yes | planned |
| `96d896ca35f4` | `1` | `1959802` | yes | planned |
| `c5a827e36ebb` | `0` | `1048576` | yes | planned |
| `e36553b12dc1` | `1` | `2097152` | yes | planned |

The two hashes matching the "start does nothing / remains paused" symptom were
`5feb771c9b7f` and `c5a827e36ebb`.

## Loop 4 - Limited Pilot

Pilot hash: `c5a827e36ebb032189bef898102b32b7f6e234dd`

Reason: stopped RT state, failed-completion hash message, single-file payload,
smallest stopped candidate besides Spider-Man, and dry-run showed one shared
target inode.

Pre-pilot:

- RT `state=0`, `complete=0`, `left_bytes=1048576`
- message: `Download registered as completed, but hash check returned unfinished chunks.`
- target inode: `dev=49 ino=4066 nlink=5`

Live pilot actions:

1. `d.stop`
2. rename failed target path to `.invalid-for-c5a827e36ebb-20260710-114255`
3. `d.check_hash`
4. `d.start`

Post-pilot validation:

- RT transitioned to `state=1`
- RT download rate became nonzero
- old quarantined file remained on `dev=49 ino=4066 nlink=5`
- healthy sibling path remained on `dev=49 ino=4066 nlink=5`
- new target file appeared on isolated `dev=49 ino=100406 nlink=1`
- guard check passed with the pilot hash as the only allowed changed hash

Conclusion: the documented diagnosis is correct. The failure was not "RT cannot
start"; RT could not make progress while the failed torrent stayed attached to
the complete/shared sibling inode. After split/quarantine, `d.start` moved it to
active download against an isolated target.

## Follow-up Correction

Two extra gates were added after the pilot:

- download choice gate: starting a split item now requires explicit operator
  approval or freeleech proof, because tracker/source choice can affect ratio;
- group representative rule: only one item in a suspected variant group should
  download fresh bytes first. Other items should be checked against that new
  representative payload before any additional download is allowed.

The tool was also hardened to block whole-root multi-file quarantine when another
RT session directory is nested under that root. Live evidence showed that this
can break a healthy sibling view even though the file inodes remain recoverable.

`bin/prowlarr-freeleech-proof.py` was added as a read-only proof helper. It uses
the same Prowlarr API surface as the tracker-warning flow but preserves explicit
freeleech evidence from raw release fields before allowing that JSON report to be
used as `--freeleech-proof`.

## Batch Split and Containment

After the c5 pilot, the remaining five split-eligible rows were split and then
contained/stopped pending tracker/freeleech choice:

| Hash | Final RT state | Left bytes | Shared inode after split |
| --- | ---: | ---: | --- |
| `127c38342cfe` | `0` | `21950408183` | no |
| `245f2bce6afa` | `0` | `8339890797` | no |
| `5feb771c9b7f` | `0` | `23450701324` | no |
| `96d896ca35f4` | `0` | `21082531706` | no |
| `c5a827e36ebb` | `0` | `810549248` | no |
| `e36553b12dc1` | `0` | `5757836898` | no |

Final dry inventory result: `split_eligible_shared_count=0`.

Guard result after containment: pass, 0 issues.

Dexter S02 correction: the first whole-root split moved a path that contained a
nested healthy RT sibling view (`e56e8c574db0`). The nested view was restored as
hardlinks from quarantine, RT rechecked it to `complete=1 left=0`, and the tool
now blocks that nested-session shape before mutation.

## Next

`5feb771c9b7f` was selected as the first representative because Prowlarr returned
explicit TorrentLeech freeleech proof and a live seed count. The already-split
target was started with `--start-existing-split`; the tool confirmed the payload
path existed, no longer shared an inode, had no nested RT session directory, and
was not complete before issuing `d.start`. Post-start guard passed with 0 issues,
and RT entered active download with decreasing `left_bytes`.

Completion validation:

- RT downloaded the new target to `complete=1 left=0`.
- RT was stopped and force-rechecked; final state was `state=0 complete=1 hashing=0 left=0`.
- qB was then force-rechecked against the same path and moved from
  `stoppedDL progress=0.999979... left=524288` to
  `stoppedUP progress=1.0 left=0`.
- The quarantined old file and new verified file have the same size
  (`25389518348`) but different bytes; `cmp` reported the first difference at
  byte 57. Old inode: `dev=49 ino=65878 nlink=4`; new inode:
  `dev=49 ino=100413 nlink=1`.
- Hash-scoped RT payload sync processed the one torrent, recorded one complete
  payload, skipped orphan prune, and exited cleanly after fixing the
  `--upgrade-missing` empty-queue summary bug.
- The procedure and tool now require a payload-group home audit before reusing
  or rehoming the newly verified variant. Canonical path shape is per torrent,
  but stash-vs-pool home is decided for the full same-inode group: any
  media-library hardlink keeps the whole group on stash.
- Targeted placement audit for the repaired Spider-Man variant scanned
  `/data/media/torrents/seeding/movies`, `/data/media/movies`, and
  `/stash/media/movies`. It found one same-inode member, no media-library member,
  and classified the current new variant group as `pool_eligible`. Rerun this
  audit after any additional compatible target torrent is hardlinked into the
  group.
- The only same-title Spider-Man sibling found in qB/RT was
  `5c86280a99d1` on Aither. Read-only verification tested the new
  `5feb771c9b7f` representative file against the Aither `.torrent`; it failed
  piece verification (`1513/1514` pieces OK, 1 failed), so Aither is not
  compatible with the new variant and must not be hardlinked/repointed to it.
  Proposed-member placement audit including the Aither path found media-library
  anchors under `/data/media/movies` and `/stash/media/movies`, so if any future
  compatible member from that inode group were proposed, the combined group would
  be `stash_required`.

Keep the other split rows stopped unless the operator chooses a tracker/source or
Prowlarr records freeleech proof with viable seeds. After the representative
verifies, compare quarantined vs new bytes and test other target torrents against
that representative payload before allowing any further downloads.

## Remaining Source Scan

After the Spider-Man representative repair, a read-only Prowlarr scan was run for
the five remaining split/contained rows. The first pass exposed a proof bug:
`prowlarr-freeleech-proof.py` could set `freeleech_proven=true` because unrelated
broad-query results were freeleech. The tool is now v0.2.0 and supports
`--expected-title`, `--expected-size`, and `--size-tolerance-bytes`; when those
filters are present, only matching releases can prove freeleech for live Plan B
start.

Strict source results:

| Hash | Title | Strict freeleech proof | Best strict freeleech hit | Seeders | Recommended action |
| --- | --- | --- | --- | ---: | --- |
| `127c38342cfe` | River Monsters S07 NTb | yes | TorrentLeech | 40 | Best next pilot. |
| `245f2bce6afa` | Dexter S02 ZMNT | yes | TorrentLeech | 10 | Viable next pilot. |
| `e36553b12dc1` | Dexter S07 ZMNT | yes | TorrentLeech | 11 | Viable next pilot. |
| `96d896ca35f4` | Transformers TLENC0DE | yes | DigitalCore | 0 | Do not pilot now; proof exists but no current seeders. |
| `c5a827e36ebb` | Here 2024 FLUX | no | none | 0 | Needs operator approval or a stricter freeleech source before start. |

Strict proof reports are under
`.agent/reports/j51-variant-source-scan-20260710/*-prowlarr-strict.json`.

## River Monsters Live Start

Operator approved the next representative pilot. `127c38342cfe` River Monsters
was started with `--start-existing-split`, `--allow-start-download`, and the
strict TorrentLeech freeleech proof report.

Evidence:

- Dry-run passed: payload exists, no shared inode, no nested RT session dirs,
  torrent incomplete.
- Live apply report:
  `.agent/reports/j51-variant-source-scan-20260710/127c38342cfe-start-existing-live.json`.
- RT moved from `state=0 complete=0 left=21950408183` to
  `state=1 complete=0 left=21950408183`.
- Watch result after roughly three minutes: still active, no message, no hashing,
  no connected peers, no byte progress.
- Tracker evidence from `t.multicall`: TorrentDay trackers are enabled/usable;
  the focused tracker reported scrape complete/incomplete `1/1` and latest peers
  `1`, but RT had `peers_connected=0`.

Current interpretation: the split/start path worked and the item is active, but
it has not connected to a peer yet. Leave it active for now and recheck progress
before starting another representative.
