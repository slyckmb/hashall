# J51 Current Approval Gates - 2026-07-12

This note captures the current j51 live gates after the guarded Plan C source-cleanup executor was added.

## Current qB StoppedDL State

Latest qB stoppedDL metadata refresh:

- Report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-refresh-stoppeddl-20260712-230531.json`
- Result: `active=164`, `missing_in_qb=0`, `pruned=0`

## Applied Gate 1: Convert Verified-Safe qB Items

The current safe batch contained 157 verified qB `stoppedDL` hashes. Operator approval was received and the live fastresume retarget completed successfully on 2026-07-13.

Evidence:

- Drain report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-drain-20260712.json`
- Hash file: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-hashes-20260712.txt`
- Fresh dry-run: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-apply-dryrun-refresh-20260712-230548.json`
- Dry-run result: `planned=157`, `blocked=0`, `skipped_live_state=0`, `root_policy_rejected=0`, `same_filesystem_overridden=156`, `fr_needed=156`
- Live apply report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-apply-live.json`
- Rollback ledger: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-rollback-ledger.jsonl`
- Post-refresh report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-post-refresh.json`
- Live qB state report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-current-combined-verified157-live-state-after-apply.json`

Live result:

- Apply summary: `planned=157`, `applied=157`, `ok=157`, `failed=0`, `blocked=0`, `fr_patched=156`, `rollback_ledger_written=156`
- qB stoppedDL bucket refresh: `active=7`, `pruned=157`, `missing_in_qb=0`
- Direct qB state check: `requested=157`, `found=157`, `state_counts={"stoppedUP": 157}`, `stoppedup_complete=157`
- The remaining 7 are excluded hard-tail items and must not be forced to `stoppedUP`.

Executed command:

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
- Current guarded execute preview: `/tmp/hashall-j51-dexter-s02-source-cleanup-execute-preview-20260713-005557.json`
- Latest guarded execute preview: `/tmp/hashall-j51-dexter-s02-source-cleanup-execute-preview-20260713-current.json`
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

## Approval Gate 3: qB Retarget All 3 Verified Hard-Tail Items

The three RT-complete/qB-stoppedDL hard-tail rows now all have independent class-A byte proof and a combined dry-run. This is the preferred live gate over applying the three individual gates separately.

Included hashes:

- `399f4c0bbb791` — Yu-Gi-Oh! Zexal Season 4
- `09c5e08c31eb` — Supernatural S01-S15 web eac3 hevc-d3g
- `09bceba1b43c` — Nintendo Gamecube Complete Collection - HardStyle

Evidence:

- Combined drain report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-verified3-combined-drain-20260713.json`
- Hashes file: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-verified3-hashes-20260713.txt`
- Combined apply dry-run: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-verified3-apply-dryrun-20260713.json`
- Dry-run state: `planned=3`, `fr_needed=3`, `same_filesystem_overridden=3`, `blocked=0`, `root_policy_rejected=0`

Required approval text:

```text
approve j51 live fastresume retarget verified hard-tail 3 hashes from /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-verified3-combined-drain-20260713.json using --allow-verified-fastresume-cross-filesystem
```

Execution command after approval:

```bash
bin/qb-stoppeddl-apply.py \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --drain-report /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-verified3-combined-drain-20260713.json \
  --hashes-file /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-verified3-hashes-20260713.txt \
  --allow-verified-fastresume-cross-filesystem \
  --apply \
  --wait-recheck \
  --report-json /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-verified3-apply-live-20260713.json \
  --rollback-ledger /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-verified3-rollback-ledger-20260713.jsonl
```

## Approval Gate 4: qB Retarget Yu-Gi-Oh Verified Hard-Tail Item

Yu-Gi-Oh was previously listed as class E/no-candidate because the earlier verifier timed out before reading enough data. A targeted full verifier on 2026-07-13 proved the pool payload is complete and byte-correct.

Evidence:

- Full piece verifier: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-yugioh-full-verify-20260713.json`
- Apply-compatible drain report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-yugioh-drain-verified-crossfs-20260713.json`
- Apply dry-run: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-yugioh-apply-dryrun-20260713.json`
- Verification result: class A, exact tree, verified `true`, ratio `1.0`, `2799/2799` pieces OK
- Recommended path: `/pool/media/torrents/seeding/Yu-Gi-Oh! Zexal Season 4`
- Dry-run state: `planned=1`, `fr_needed=1`, `same_filesystem_overridden=1`, `blocked=0`, `root_policy_rejected=0`

Required approval text:

```text
approve j51 live fastresume retarget Yu-Gi-Oh 399f4c0bbb791 using verified class-A drain report /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-yugioh-drain-verified-crossfs-20260713.json with --allow-verified-fastresume-cross-filesystem
```

Execution command after approval:

```bash
bin/qb-stoppeddl-apply.py \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --drain-report /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-yugioh-drain-verified-crossfs-20260713.json \
  --hashes-file /tmp/qb-stoppeddl-bucket-live/reports/j51-yugioh-verified-hash.txt \
  --allow-verified-fastresume-cross-filesystem \
  --apply \
  --wait-recheck \
  --report-json /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-yugioh-apply-live-20260713.json \
  --rollback-ledger /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-yugioh-rollback-ledger-20260713.jsonl
```

## Approval Gate 5: qB Retarget Supernatural Verified Hard-Tail Item

Supernatural was previously excluded because no independent full verifier artifact existed. A targeted full verifier on 2026-07-13 proved the pool payload is complete and byte-correct.

Evidence:

- Apply-compatible drain report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-supernatural-drain-verified-crossfs-20260713.json`
- Apply dry-run: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-supernatural-apply-dryrun-20260713.json`
- Verification result: class A, exact tree, verified `true`, ratio `1.0`
- Recommended path: `/pool/media/torrents/seeding/Supernatural S01-S15 web eac3 hevc-d3g`
- Dry-run state: `planned=1`, `fr_needed=1`, `same_filesystem_overridden=1`, `blocked=0`, `root_policy_rejected=0`

Required approval text:

```text
approve j51 live fastresume retarget Supernatural 09c5e08c31eb using verified class-A drain report /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-supernatural-drain-verified-crossfs-20260713.json with --allow-verified-fastresume-cross-filesystem
```

Execution command after approval:

```bash
bin/qb-stoppeddl-apply.py \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --drain-report /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-supernatural-drain-verified-crossfs-20260713.json \
  --hashes-file /tmp/qb-stoppeddl-bucket-live/reports/j51-supernatural-verify-hash.txt \
  --allow-verified-fastresume-cross-filesystem \
  --apply \
  --wait-recheck \
  --report-json /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-supernatural-apply-live-20260713.json \
  --rollback-ledger /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-supernatural-rollback-ledger-20260713.jsonl
```

## Approval Gate 6: qB Retarget Nintendo Verified Hard-Tail Item

Nintendo was previously excluded because the earlier verifier timed out at 19.6% after 900 seconds. A targeted full verifier on 2026-07-13 proved the pool payload is complete and byte-correct.

Evidence:

- Apply-compatible drain report: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-nintendo-drain-verified-crossfs-20260713.json`
- Apply dry-run: `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-nintendo-apply-dryrun-20260713.json`
- Verification result: class A, exact tree, verified `true`, ratio `1.0`
- Recommended path: `/pool/media/torrents/seeding/Nintendo Gamecube Complete Collection - HardStyle`
- Dry-run state: `planned=1`, `fr_needed=1`, `same_filesystem_overridden=1`, `blocked=0`, `root_policy_rejected=0`

Required approval text:

```text
approve j51 live fastresume retarget Nintendo 09bceba1b43c using verified class-A drain report /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-nintendo-drain-verified-crossfs-20260713.json with --allow-verified-fastresume-cross-filesystem
```

Execution command after approval:

```bash
bin/qb-stoppeddl-apply.py \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --drain-report /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-nintendo-drain-verified-crossfs-20260713.json \
  --hashes-file /tmp/qb-stoppeddl-bucket-live/reports/j51-nintendo-verify-hash.txt \
  --allow-verified-fastresume-cross-filesystem \
  --apply \
  --wait-recheck \
  --report-json /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-nintendo-apply-live-20260713.json \
  --rollback-ledger /tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-nintendo-rollback-ledger-20260713.jsonl
```

## Excluded Hard-Tail Items

These 7 hashes are intentionally excluded from the verified-safe qB conversion batch.

| Hash | Name | Current evidence | Next action |
| --- | --- | --- | --- |
| `09bceba1b43c` | Nintendo Gamecube Complete Collection - HardStyle | Full verifier now proves class A exact tree, verified `true`, ratio `1.0`; dry-run requires one fastresume retarget | Ready for explicit live approval under Approval Gate 6, or the combined Approval Gate 3. |
| `09c5e08c31eb` | Supernatural S01-S15 web eac3 hevc-d3g | Full verifier now proves class A exact tree, verified `true`, ratio `1.0`; dry-run requires one fastresume retarget | Ready for explicit live approval under Approval Gate 5, or the combined Approval Gate 3. |
| `127c38342cfe` | River Monsters S07 1080p AMZN WEB-DL DDP2 0 H 264-NTb | RT cache currently `stalledDL`; verified partial, class D, ratio `0.9992356763546204`; report `/tmp/qb-stoppeddl-bucket-live/reports/verify-127c38342cfedaf4016b8079be13c5f7883b9cfe-20260712-223627.json` | Leave as partial/no-seed or continue variant/replacement handling; do not convert to `stoppedUP`. |
| `245f2bce6afa` | Dexter.S02.720p.x265-ZMNT | RT cache currently `stalledDL`; verified partial, class D, ratio `0.9997485396330664`; report `/tmp/qb-stoppeddl-bucket-live/reports/verify-245f2bce6afaf96b0a48ad216366c4281fdd864f-20260712-220009.json` | Do not convert to `stoppedUP`; source cleanup is separate from partial repair. |
| `399f4c0bbb79` | Yu-Gi-Oh! Zexal Season 4 | Full verifier now proves class A exact tree, verified `true`, ratio `1.0`; dry-run requires one fastresume retarget | Ready for explicit live approval under Approval Gate 4, or the combined Approval Gate 3. |
| `96d896ca35f4` | Transformers.Rise.of.the.Beasts.2023.1080p.BluRay.x265.10bit.TrueHD.7.1.Atmos-TORRENTLEECHENC0DE | RT cache currently `stalledDL`; targeted DB-root verify proved partial, class D, ratio `0.9999070414299701`; report `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-transformers-dbroot-verify-20260712.json` | Do not convert to `stoppedUP`; continue variant/replacement handling. |
| `e36553b12dc1` | Dexter.S07.720p.x265-ZMNT | RT cache currently `stalledDL`; targeted DB-root verify proved partial, class D, ratio `0.9996357743303342`; report `/tmp/qb-stoppeddl-bucket-live/reports/j51-hardtail-dexter-s07-dbroot-verify-20260712.json` | Do not convert to `stoppedUP`; source cleanup remains blocked by a live TorrentLeech client reference. |

## Important Tracking Note

Commit `b1d9eb5` added the guarded source-cleanup executor and has the expected j51-t22 trailers, but `chatrap ack commit HEAD` reports `s05_direct_cr_commit=FAIL` because this long-running session is committing on the CR branch instead of a job worktree.
