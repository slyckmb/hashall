# J51 99 Percent Content-Variant Validation - 2026-07-10

## Summary

The active qB `stoppedDL` 99.* set is 6 rows. All 6 were validated with the
new `docs/RT-QB-99PCT-CONTENT-VARIANT-REPAIR.md` process and
`bin/torrent-sibling-hardlink-repair.py` dry-runs.

Result: 0 verified sibling-hardlink repair candidates remain, and all 6 current
rows now require the split/rename/redownload phase to prove whether the
candidate sibling bytes are true variants.

This does not mean the qB dashboard count is zero. It means Plan A found no
source bytes that can be hardlinked directly. The next valid repair step is Plan
B from the runbook: rename the invalid target file/tree out of the failed
torrent's expected path, let that failed torrent download fresh bytes, then
compare old vs new to prove duplicate vs variant.

## Current Live Set

| Hash prefix | Name | qB left | RT state | Verification result | Next class |
| --- | --- | ---: | --- | --- | --- |
| `245f2bce6afa` | `Dexter.S02.720p.x265-ZMNT` | 2097152 | active incomplete, peers 0 | current tree fails target torrent: 3976/3977 pieces OK, 1 failed | `needs-split-redownload` |
| `e36553b12dc1` | `Dexter.S07.720p.x265-ZMNT` | 2097152 | active incomplete, peers 0 | TorrentLeech sibling fails speedcd target torrent: 2745/2746 pieces OK, 1 failed | `needs-split-redownload` |
| `c5a827e36ebb` | `Here.2024.1080p.AMZN...` | 1048576 | stopped after failed completion hash check, peers 0 | seedpool/movies inode fails target torrent: 6383/6384 pieces OK, 1 failed | `needs-split-redownload` |
| `127c38342cfe` | `River Monsters S07...` | 16777216 | active incomplete, peers 0 | target tree has 1308/1309 pieces OK; one piece missing because torrent sidecar content is absent/truncated | `needs-split-redownload` |
| `5feb771c9b7f` | `Spider-Man.Into.the.Spider-Verse...` | 524288 | stopped after failed completion hash check, peers 0 | Aither sibling inode fails target torrent: 48426/48427 pieces OK, 1 failed | `needs-split-redownload` |
| `96d896ca35f4` | `Transformers.Rise.of.the.Beasts...` | 1959802 | active incomplete, peers 0 | target tree has 5026/5027 pieces OK; one piece missing because target sidecar content is absent/truncated | `needs-split-redownload` |

## Evidence Artifacts

Dry-run reports:

- `/tmp/hashall-j51-245f2b-dryrun.json`
- `/tmp/hashall-j51-e36553-dryrun.json`
- `/tmp/hashall-j51-c5a827-dryrun.json`
- `/tmp/hashall-j51-127c38-dryrun.json`
- `/tmp/hashall-j51-5feb77-dryrun.json`
- `/tmp/hashall-j51-96d896-dryrun.json`

DB source:

- `/home/michael/dev/work/hashall/.state/catalog.db`
- device refresh evidence: pool scanned `2026-07-10 11:47:01`; stash scanned
  `2026-07-10 09:27:54`

RT peer/message snapshot:

| Hash prefix | RT state | RT complete | RT left | peers complete | peers connected | trackers | Message |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `245f2bce6afa` | 1 | 0 | 2097152 | 0 | 0 | 1 | |
| `e36553b12dc1` | 1 | 0 | 2097152 | 0 | 0 | 1 | |
| `c5a827e36ebb` | 0 | 0 | 1048576 | 0 | 0 | 1 | failed completion hash check |
| `127c38342cfe` | 1 | 0 | 16777216 | 0 | 0 | 2 | |
| `5feb771c9b7f` | 0 | 0 | 524288 | 0 | 0 | 2 | failed completion hash check |
| `96d896ca35f4` | 1 | 0 | 1959802 | 0 | 0 | 2 | |

qB tracker API showed working tracker status for the rows with tracker data, but
private trackers did not expose useful scrape seed counts through qB
(`num_seeds=-1`). RT showed 0 connected/known complete peers at the time of the
scan.

## Conclusion

Plan A of the documented repair process is valid and now tested against the
remaining suspected 99.* content-variant set. It correctly refused direct
hardlink repair from incompatible sibling bytes.

Actionable direct sibling-hardlink repair backlog: 0.

Remaining split/rename/redownload backlog: 6.
