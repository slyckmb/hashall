# HANDOFF-2026-02-22-FULL-CONTEXT-REPAIR

## Session/Branch Context
- Worktree: `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260219-193341`
- Branch: `chatrap/codex-hashall-20260219-193341`
- Date: 2026-02-22
- Scope: qB noHL rehome safety/repair workflow after unexpected redownload behavior.

## Objective (as requested)
Repair the stopped/broken qB torrents by finding real on-disk data, reattaching safely, and proving no redownload regressions before resuming larger noHL rehome runs.

## Stage Status Snapshot

### Stage 0 (Containment) - COMPLETE
- Verified `add_stopped_enabled=true` (qB v5 key; `start_paused_enabled` not present on this build).
- Gate satisfied at time of execution: no active `down/moving/missing` violations.
- Artifact: `out/reports/rehome-normalize/stage0-containment-final-20260221-230019.log`

### Stage 1 (Tripwire) - COMPLETE
- Ran enforced paused-DL watchdog soak (20 samples).
- No leaks during soak (`unexpected_down=0`).
- Artifact: `out/reports/rehome-normalize/nohl-stage1-tripwire-soak-20260221-235528.log`

### Stage 2 (Baseline Snapshot) - COMPLETE
- Added script: `bin/rehome-100_nohl-basics-qb-repair-baseline.sh`
- Produced canonical repair queue artifact.
- Baseline summary at run time:
  - `queue_total=123`
  - `states={'stoppedDL':123}`
  - `save_missing=0`
  - `content_missing=26`
- Artifacts:
  - `out/reports/rehome-normalize/nohl-qb-repair-baseline-20260222-000329.json`
  - `out/reports/rehome-normalize/nohl-qb-repair-baseline-20260222-000329.tsv`
  - `out/reports/rehome-normalize/nohl-qb-repair-queue-hashes-20260222-000329.txt`

### Stage 3 (Candidate Mapping) - COMPLETE (but logic is flawed)
- Added script: `bin/rehome-101_nohl-basics-qb-candidate-mapping.sh`
- Produced mapping artifact.
- Mapping summary:
  - `mapped=123`
  - `confident=12`
  - `ambiguous=111`
  - `manual_only=0`
- Artifacts:
  - `out/reports/rehome-normalize/nohl-qb-candidate-mapping-20260222-000814.json`
  - `out/reports/rehome-normalize/nohl-qb-candidate-mapping-20260222-000814.tsv`
  - `out/reports/rehome-normalize/nohl-qb-candidate-confident-hashes-20260222-000814.txt`

### Stage 4 (Pilot Transaction) - STARTED, FAILED / ABORTED
- Added script: `bin/rehome-102_nohl-basics-qb-repair-pilot.sh`
- Dryrun was fine, but live pilot picked a bad candidate and stalled waiting for impossible terminal state.
- Key failure evidence:
  - Log: `out/reports/rehome-normalize/nohl-basics-qb-repair-pilot-20260222-002843.log`
  - First pilot hash: `d95fb5bf...`
  - Target chosen: `/data/media/torrents/seeding/public` (current stoppedDL save path)
  - Recheck ran, but state stayed `stoppedDL`, `progress=0`, `amount_left=size` for >10 minutes.

## Root Cause (current best understanding)
1. Stage 3 scoring bug:
   - `save_path_exact` was scored highest (`100`) even for `stoppedDL` queues.
   - That means the mapper often selected the same non-recovery path as “best candidate”.
2. Stage 4 selection bug:
   - Pilot trusted `confidence=confident` from Stage 3, then selected by size only.
   - It did not reject entries where target equals current `save_path`.
3. Missing recoverability preflight:
   - No requirement that selected pilot item has provable existing data root for full recheck completion.

## What Was Added in Code (this session)
- `bin/rehome-89_nohl-basics-qb-automation-audit.sh`
- `bin/rehome-100_nohl-basics-qb-repair-baseline.sh`
- `bin/rehome-101_nohl-basics-qb-candidate-mapping.sh`
- `bin/rehome-102_nohl-basics-qb-repair-pilot.sh`
- Enhanced `bin/rehome-99_qb-checking-watch.sh` with enforce/allowlist/events features.
- `bin/codex-says-run-this-next.sh` updated to include stage 89 + watchdog recommendation flow.

## Commits Added (recent)
- `783ef2c` feat(rehome): add qB automation audit and paused-DL watchdog
- `6c0abfc` feat(rehome): add stage2 repair baseline snapshot queue
- `24e0ba7` feat(rehome): add stage3 candidate mapping for repair queue
- `2eda5a2` feat(rehome): add stage4 pilot transaction runner

## Current Runtime State (at handoff capture)
- qB API endpoint `http://localhost:9003` was unreachable during handoff capture (`qbit_up=0`).
- Confirm before any next repair step:
  - qB container/process health
  - API login and torrent list access

## Required Fixes Before Resuming Pilot
1. Fix Stage 3 mapping so recovery candidates are real data locations, not current stoppedDL save paths.
   - Penalize or reject `save_path_exact` when state is `stoppedDL` and progress < 1.
   - Prefer candidate roots with existing content evidence (`content_exists`, DB-root exists, peer complete roots).
2. Add Stage 4 preflight guardrails:
   - Reject pilot item if `target_save_path == current save_path`.
   - Reject pilot item with no recoverability evidence.
   - Fail fast with explicit reason and move item to manual queue.
3. Rebuild Stage 3 artifacts after fix, then rerun Stage 4 dryrun/apply.

## Suggested Resume Commands (after qB is reachable)
```bash
# 0) qB reachability check
QBIT_URL=http://localhost:9003 QBIT_USER=admin QBIT_PASS=adminpass \
  bash -lc 'curl -fsS -c /tmp/qb.cookie --data-urlencode "username=$QBIT_USER" --data-urlencode "password=$QBIT_PASS" "$QBIT_URL/api/v2/auth/login" && echo OK'

# 1) Refresh baseline
bin/rehome-100_nohl-basics-qb-repair-baseline.sh --output-prefix nohl --fast --debug

# 2) Rebuild mapping (after Stage 3 code fix)
bin/rehome-101_nohl-basics-qb-candidate-mapping.sh --output-prefix nohl --fast --debug

# 3) Pilot dryrun
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode dryrun --output-prefix nohl --limit 3 --fast --debug

# 4) Pilot apply
bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --output-prefix nohl --limit 3 --poll-s 2 --heartbeat-s 10 --timeout-s 1200 --fast --debug
```

## Critical Safety Notes
- Keep `HASHALL_REHOME_QB_RESUME_AFTER_RELOCATE=0` and `HASHALL_REHOME_QB_RESUME_ON_FAILURE=0`.
- Keep tripwire running during repair/apply windows.
- Do not bulk-repair until Stage 4 proves 3/3 success on valid candidates.

## Workspace Notes
- This handoff intentionally includes unresolved logic debt in Stage 3/4 (documented above).
- Dirty/unrelated files were present in workspace before/alongside this work and are committed per user request.
