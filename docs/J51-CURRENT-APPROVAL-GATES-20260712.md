# J51 Current Approval Gates - 2026-07-12

This note captures the current j51 live gates after the guarded Plan C source-cleanup executor was added.

## Current qB StoppedDL State

Latest qB stoppedDL metadata refresh:

- Report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-refresh-stoppeddl-20260712-230531.json`
- Result: `active=164`, `missing_in_qb=0`, `pruned=0`

## Approval Gate 1: Convert Verified-Safe qB Items

The current safe batch contains 157 verified qB `stoppedDL` hashes.

Evidence:

- Drain report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-drain-20260712.json`
- Hash file: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-hashes-20260712.txt`
- Fresh dry-run: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-apply-dryrun-refresh-20260712-230548.json`
- Dry-run result: `planned=157`, `blocked=0`, `skipped_live_state=0`, `root_policy_rejected=0`, `same_filesystem_overridden=156`, `fr_needed=156`

Expected live effect: qB `stoppedDL` should drop from `164` to roughly `7`; the remaining 7 are excluded hard-tail items and must not be forced to `stoppedUP`.

Required approval text:

```text
approve j51 live fastresume retarget for 157 verified current stoppedDL hashes from /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-drain-20260712.json using --allow-verified-fastresume-cross-filesystem
```

Execution command after approval:

```bash
bin/qb-stoppeddl-apply.py \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --drain-report /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-drain-20260712.json \
  --hashes-file /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-hashes-20260712.txt \
  --allow-verified-fastresume-cross-filesystem \
  --apply \
  --report-json /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-apply-live.json \
  --rollback-ledger /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-rollback-ledger.jsonl
```

Immediate post-apply checks:

```bash
bin/qb-stoppeddl-bucket.py \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --states stoppedDL \
  --no-export-torrents \
  --prune-absent \
  --report-json /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-post-refresh.json
```

```bash
bin/qb-stoppeddl-apply.py \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --drain-report /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-drain-20260712.json \
  --hashes-file /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-hashes-20260712.txt \
  --allow-verified-fastresume-cross-filesystem \
  --report-json /tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-post-apply-dryrun.json \
  --no-wait-recheck
```

Expected post-apply result: the refresh should show roughly `7` active `stoppedDL` hashes, and the follow-up dry-run should skip the 157 hashes by live state or otherwise plan `0` new actions.

## Approval Gate 2: Reclaim Dexter S02 Old Source Root

The guarded Plan C cleanup executor previews Dexter S02 source cleanup as ready, but live deletion still requires explicit operator approval.

Evidence:

- Source cleanup dry-run: `/tmp/hashall-j51-dexter-s02-source-cleanup-dryrun-refresh-20260712.json`
- Guarded execute preview: `/tmp/hashall-j51-dexter-s02-source-cleanup-execute-preview-20260712-230548.json`
- Delete root after approval: `/data/media/torrents/seeding/SpeedCD/Dexter.S02.720p.x265-ZMNT`
- Filesystem check: `13` files, `8339890797` bytes, `min_nlink=1`, `max_nlink=1`, `non_nlink1=0`
- Safety state: no exact qB/RT client hits, no library hits, no dry-run blockers

Required approval text:

```text
approve Plan C source cleanup delete 245f2bce6afa /data/media/torrents/seeding/SpeedCD/Dexter.S02.720p.x265-ZMNT
```

Execution command after approval:

```bash
.venv/bin/python -m hashall.cli client-drift incomplete-rehome-source-cleanup-execute \
  --dry-run-report /tmp/hashall-j51-dexter-s02-source-cleanup-dryrun-refresh-20260712.json \
  --apply \
  --approval 'approve Plan C source cleanup delete 245f2bce6afa /data/media/torrents/seeding/SpeedCD/Dexter.S02.720p.x265-ZMNT' \
  --output /tmp/hashall-j51-dexter-s02-source-cleanup-execute-live-20260712.json
```

## Excluded Hard-Tail Items

These 7 hashes are intentionally excluded from the verified-safe qB conversion batch.

| Hash | Name | Current evidence | Next action |
| --- | --- | --- | --- |
| `09bceba1b43c` | Nintendo Gamecube Complete Collection - HardStyle | DB payload incomplete; 675.98 GiB; not verified safe | Do not retarget. Run a dedicated long verifier only if the I/O is worthwhile. |
| `09c5e08c31eb` | Supernatural S01-S15 web eac3 hevc-d3g | DB payload incomplete; 268.87 GiB; not verified safe | Do not retarget. Run a dedicated long verifier only if the I/O is worthwhile. |
| `127c38342cfe` | River Monsters S07 1080p AMZN WEB-DL DDP2 0 H 264-NTb | Verified partial, class D, ratio `0.9992356763546204` | Leave as partial/no-seed or continue variant/replacement handling. |
| `245f2bce6afa` | Dexter.S02.720p.x265-ZMNT | Verified partial, class D, ratio `0.9997485396330664` | Do not convert to `stoppedUP`; source cleanup is separate from partial repair. |
| `399f4c0bbb79` | Yu-Gi-Oh! Zexal Season 4 | Incomplete/no candidate, class E | Needs targeted source discovery or replacement plan. |
| `96d896ca35f4` | Transformers.Rise.of.the.Beasts.2023.1080p.BluRay.x265.10bit.TrueHD.7.1.Atmos-TORRENTLEECHENC0DE | Targeted DB-root verify proved partial, class D, ratio `0.9999070414299701` | Do not convert to `stoppedUP`; continue variant/replacement handling. |
| `e36553b12dc1` | Dexter.S07.720p.x265-ZMNT | Targeted DB-root verify proved partial, class D, ratio `0.9996357743303342` | Do not convert to `stoppedUP`; source cleanup remains blocked by a live TorrentLeech client reference. |

## Important Tracking Note

Commit `b1d9eb5` added the guarded source-cleanup executor and has the expected j51-t22 trailers, but `chatrap ack commit HEAD` reports `s05_direct_cr_commit=FAIL` because this long-running session is committing on the CR branch instead of a job worktree.
