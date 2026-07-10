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

Focused validation passed:

```text
tests/test_rt_qb_variant_split_redownload.py 3 passed
tests/test_rtorrent_safe_start.py 8 passed
tests/test_torrent_sibling_hardlink_repair.py 2 passed
```

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

## Next

Let `c5a827e36ebb` finish, then compare the quarantined file/tree against the new
verified file/tree. If they differ, record `variant-proven`; if they match,
investigate client/session metadata. Then repeat the same Plan B loop for the
remaining 99.* rows, prioritizing stopped hashes before already-active hashes.
