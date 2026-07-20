# RT/qB Surgical Repair Runbook

**Status:** Active
**Date:** 2026-07-05

Use this runbook for small live RT/qB state repairs. It does not replace the
full 4-Gate protocol. It defines the safe path for urgent explicit-hash repairs
that are too small for a full batch run but still mutate live clients.

## Choose the Gate

| Situation | Required path |
|-----------|---------------|
| Broad/batch qB or RT repair | Full 4-Gate protocol |
| Explicit 1-5 hash RT/qB repair | Surgical mini-gate |
| qB actively uploading/downloading and should be passive | Stop-only containment, then log |
| Read-only audit, bucket, drain, report | No live gate; write findings |

Stop-only containment means only pausing/stopping the explicit qB hash. Do not
combine it with path changes, rechecks, resumes, RT starts, RT repoints, or
filesystem mutation.

## Surgical Mini-Gate

1. Capture baseline:
   - qB state breakdown
   - qB active upload/download hashes
   - qB stoppedDL count and checking backlog
   - RT stoppedDL/PD list
   - RT current directory/complete/state for target hashes

2. Declare exact scope:
   - target hashes
   - allowed commands
   - forbidden commands
   - expected target paths

3. Verify payload:
   - compare torrent metadata to candidate payload tree
   - require every file by relative path and size
   - block if any required file is missing, including `.nfo` or sidecar files

4. Dry-run:
   - old RT/qB state
   - proposed state
   - single-file vs multi-file target semantics
   - exact client calls that would run

5. Apply:
   - mutate only the approved hashes
   - for RT, trigger hash-check and start only after `complete=1`
   - for qB, keep mirror state passive

6. Post-check:
   - immediate state snapshot
   - 60-second follow-up
   - no qB active states
   - no unexplained qB stoppedDL increase
   - no new RT stoppedDL/PD outside approved exceptions

## RT Repair Command Shape

Use the surgical wrapper:

```bash
python3 bin/rt-surgical-repair.py \
  --hash <hash> \
  --target <candidate-dir> \
  --dry-run \
  --report-json /tmp/rt-repair-<hash>-dry-run.json
```

Apply only after the dry-run report passes review:

```bash
python3 bin/rt-surgical-repair.py \
  --hash <hash> \
  --target <candidate-dir> \
  --apply \
  --allow-start-if-complete \
  --report-json /tmp/rt-repair-<hash>-apply.json
```

Do not call `d.directory.set`, `d.start`, or
`rt_apply_directory_repoint(..., restart=True)` directly for manual repair.

## Blocked Example

If torrent metadata requires:

```text
Movie.mkv
Movie.mkv.nfo
```

and only `Movie.mkv` exists, the repair is blocked. A matching media file is not
enough proof that the torrent is complete.

## State Guard

Before and after repair, use the state guard:

```bash
python3 bin/rt-qb-state-guard.py baseline --output /tmp/rt-qb-baseline.json
python3 bin/rt-qb-state-guard.py check --baseline /tmp/rt-qb-baseline.json --report-json /tmp/rt-qb-check.json
```

Use `watch` during longer live batches.

## Task Log Summary

Every surgical repair task-log should include:

- gate type: `surgical-mini-gate`
- hashes touched
- baseline artifact
- dry-run artifact
- apply artifact
- post-check artifact
- 60-second follow-up verdict
- blocked hashes and why
