# RT PD Holdouts RCCA - 2026-07-09

## Summary

The current rTorrent holdout set is 7 rows, not 6. Five are near-complete
99% rows that were previously treated as possible "waiting for seeds" items.
They are not active stalled downloads. Live rTorrent says each one is stopped:
`d.state=0`, `d.complete=0`, `d.hashing=0`, `d.is_active=0`, and rate is
zero.

Those five rows all carry the rTorrent message:

`Download registered as completed, but hash check returned unfinished chunks.`

That means rTorrent believed the torrent had completed, then a hash check proved
one or more pieces do not match that torrent's piece map.

The remaining two rows are 0% TorrentDay items and are a different class:
their current RT directories are missing required payload files. They belong in
the existing missing-payload repair lane, not the "split then wait for seeds"
lane.

## Current live set

| Hash prefix | Name | RT state evidence | Class |
| --- | --- | --- | --- |
| `0b236c5155a4` | `E.T.The.Extra-Terrestrial.1982...` | `state=0 complete=0 hashing=0 active=0 left=16777216` plus failed-completion message | split-first 99% holdout |
| `1c6285d80aa3` | `E.T.The.Extra-Terrestrial.1982...` | `state=0 complete=0 hashing=0 active=0 left=16777216` plus failed-completion message | split-first 99% holdout |
| `4b4a1747e01b` | `E.T.The.Extra-Terrestrial.1982...` | `state=0 complete=0 hashing=0 active=0 left=16777216` plus failed-completion message | split-first 99% holdout |
| `c5a827e36ebb` | `Here.2024.1080p.AMZN...` | `state=0 complete=0 hashing=0 active=0 left=1048576` plus failed-completion message | split-first 99% holdout |
| `5feb771c9b7f` | `Spider-Man.Into.the.Spider-Verse...` | `state=0 complete=0 hashing=0 active=0 left=524288` plus failed-completion message | split-first 99% holdout |
| `f938949604fd` | `Killers of the Flower Moon 2023...` | `state=0 complete=0 hashing=0 active=0 left=27185179550`, no failed-completion message | missing-payload blocker |
| `8685d0e65d6f` | `The Matrix Reloaded 2003...` | `state=0 complete=0 hashing=0 active=0 left=18052469099`, no failed-completion message | missing-payload blocker |

## Hardlink evidence

The five 99% rows are not isolated files. Their payload files share inodes with
100% sibling torrents:

| Hash prefix | Inode evidence | 100% sibling evidence |
| --- | --- | --- |
| `0b236c5155a4`, `1c6285d80aa3`, `4b4a1747e01b` | same file inode `dev=49 ino=67281 nlink=9` | RT cache shows siblings `87b6670c265e`, `f8c7e9b445ee`, `b1722c003cd9` at `stalledUP 100` |
| `c5a827e36ebb` | file inode `dev=49 ino=4066 nlink=5` | RT cache shows siblings `fe76ddefe9b5`, `e2a7eab3a5be` at `stalledUP 100` |
| `5feb771c9b7f` | file inode `dev=49 ino=65878 nlink=4` | RT cache shows sibling `5c86280a99d1` at `stalledUP 100` |

This matters because starting a 99% partial torrent in place can cause rTorrent
to write missing pieces into a file that is also the live file for a 100% sibling.
That is unsafe.

## Root cause

There are two root causes working together:

1. Unsafe cross-seed hardlink matching allowed torrents with the same apparent
   filename/size to share a physical inode even though their piece maps are not
   fully interchangeable.
2. The live rTorrent config has complete-only hooks for finished/hash-done mirror
   handling, but no hook that safely restarts or classifies an item when a
   post-completion hash check returns `complete=0`. After the failed hash check,
   the torrents remain stopped instead of becoming active stalled downloads.

The observed "will not transition to SD" behavior is therefore expected from the
current state: the items are stopped after failed hash checks, and there is no
safe automatic start path for this condition.

## Correct course of action

Do not issue `d.start` on the five 99% rows in their current payload locations.

Safe repair requires:

1. For each 99% hash, build a unique per-item payload tree that is not hardlinked
   to the 100% sibling's active file.
2. Repoint the partial torrent to that unique tree.
3. Hash-check the 100% sibling afterward to prove it stayed healthy.
4. Then start the split partial item so it can wait for seeds or finish without
   mutating the good sibling's inode.
5. Keep `f938949604fd` and `8685d0e65d6f` in the missing-payload repair lane.

## Follow-up tooling gap

Add a guard/hook path for rTorrent `hash_done` where `complete=0`:

- classify the item as failed-completion-hash;
- detect whether any files are hardlinked to complete siblings;
- if hardlinked, block start and emit a split-needed report;
- if not hardlinked and tracker health is good, optionally start the item as a
  normal stalled download/wait-for-seeds case.
