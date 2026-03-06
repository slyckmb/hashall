# Run State (Canonical)

Last updated: 2026-03-05
Status: canonical living state

## Purpose

Single living document for current operational status, handoff context, and next-agent execution guidance.

## Current Mission

1. Keep qB stoppedDL repair loop safe and convergent.
2. Keep hashall catalog refresh + dedup pipeline robust across `stash`, `data`, and `spare`.
3. Eliminate refresh/runtime failures caused by device alias drift and negative device IDs.

## Non-Negotiables

- One mutating qB workflow at a time.
- No unintended sustained downloading state flips.
- Prefer deterministic, idempotent loops.
- Any full refresh run must include all three main archives:
  `/stash/media` (covers `/data/media` collection), `/pool/data`, `/mnt/hotspare6tb`.

## Active Toolchain

- qB stoppedDL pipeline:
  - `bin/qb-stoppeddl-bucket.py`
  - `bin/qb-stoppeddl-drain.py`
  - `bin/qb-stoppeddl-apply.py`
  - `bin/qb-stoppeddl-apply-watch.sh`
  - `bin/qb-stoppeddl-roundloop.sh`
  - `bin/qbit-start-seeding-gradual.sh`
- Full DB refresh pipeline:
  - `bin/codex-says-run-this-next.sh` (canonical)
  - `bin/full-hashall-db-refresh.sh` (equivalent explicit wrapper)
  - `bin/db-refresh-step1-scan-stash.sh`
  - `bin/db-refresh-step2-scan-pool-hotspare.sh`
  - `bin/db-refresh-step3-sha256-backfill.sh`
  - `bin/db-refresh-step4_5-link-dedup.sh`
  - `bin/db-refresh-step4-payload-sync.sh`
  - `bin/qb-hash-root-report.sh`

## Recent Hardening (2026-03-01)

- Refresh scripts now derive repo root from script location instead of hardcoded paths.
- Step 3 and step 3.5 now resolve device aliases safely:
  - supports `spare` and legacy `hotspare6tb`
  - fallback by mountpoint `/mnt/hotspare6tb`
  - logs resolved devices and fails cleanly if none resolve
- Step 3.5 default device set now uses `stash,data,spare`.
- Step 3 / 3.5 aggregate per-device failures and exit non-zero on partial failure.
- `hashall stats --hash-coverage` path for negative `device_id` tables is fixed in branch code
  by quoting dynamic SQLite identifiers (e.g. `files_-905882091`).

## Current Long-Running Operation

- Full pipeline launched via `bin/codex-says-run-this-next.sh`.
- Step 3 and step 3.5 for `stash` and `data` completed and applied.
- Step 3.5 for `spare` currently running large `hashall link execute` action set.
- Monitoring signals:
  - plan status from `link_plans`
  - `link_actions` status counts
  - process liveness (`jdupes` in I/O state on large files)
  - `~/.logs/hashall/hashall.log` for error signatures

## Primary Logs and Reports

- DB refresh logs: `~/.logs/hashall/reports/db-refresh/`
- Hashall runtime log: `~/.logs/hashall/hashall.log`
- qB triage logs: `~/.logs/hashall/reports/qbit-triage/`
- stoppedDL reports: `/tmp/qb-stoppeddl-bucket-live/reports/`

## Next-Agent Checklist

1. Verify full refresh completion (all steps through payload sync + hash-root report).
2. If any step failed:
   - isolate failing device/step from logs,
   - patch root cause,
   - rerun only failed step(s),
   - confirm no regression in successful steps.
3. Re-run validations on this branch code path:
   - `PYTHONPATH=$PWD/src python3 -m hashall stats --hash-coverage`
   - syntax/compile checks for touched scripts.
4. Only after clean run + validation, finalize commits and leave clean working tree.

## Compatibility Notes

Legacy docs remain stubs pointing here:

- `docs/ops-log.md`
- `docs/handoff.md`
- `docs/next-agent.md`
- `docs/NEXT-AGENT-PROMPT.md`
- `docs/qbit-repair-handoff.md`
- `docs/qbit-repair-ops-log.md`

## Incident Update (2026-03-05)

### Scope

- Active incident: qB `missingFiles` after `/pool/data/media` -> `/pool/media` migration attempts.
- Objective this session: truth assessment, preserve DB state, apply safest remediation lane in controlled batches.

### Baseline and Artifacts

- DB backups/snapshots:
  - `out/reports/recovery-truth/db-backups/catalog-pre-refresh-20260305-194555.db`
  - `out/reports/recovery-truth/catalog-snapshot-20260305-193532.db`
- Truth reports:
  - `out/reports/recovery-truth/truth-assessment-20260305-183948.csv`
  - `out/reports/recovery-truth/truth-assessment-20260305-183948.md`
  - `out/reports/recovery-truth/refresh-upgrade-roots-20260305-195619.csv`
  - `out/reports/recovery-truth/refresh-upgrade-roots-20260305-195619-summary.json`

### Refresh Readout

- Refresh log set reviewed:
  - `/home/michael/.logs/hashall/rehome/refresh/20260305-195619.log`
  - `/home/michael/.logs/hashall/rehome/refresh/20260305-195619.json`
- Run completed `OK`, but payload upgrade stage was mostly incomplete:
  - `queued=190 started=190 completed=5 failed=0`
  - parsed summary: `zero_files=185` (most roots unresolved/missing on disk)

### qB Missing Repair Progress

- Pre-remediation baseline:
  - `missing_total=49`
  - `actionable_total=34`
  - `ambiguous_root_name_candidates=11`
  - `qb_false_missing_content_exists=4`
- Applied safe lane (`root_name_unique_candidate`) in two batches:
  - Batch A: `limit=10`, `ok=10`, `errors=0`
  - Batch B: `limit=25`, `ok=25`, `errors=0`
  - Batch C: `limit=25`, selected `22`, `ok=22`, `errors=0`
- Current post-batch state:
  - `missing_total=23`
  - `actionable_total=8`
  - `ambiguous_root_name_candidates=11`
  - `qb_false_missing_content_exists=4`
- Latest audit artifacts:
  - `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-audit-20260305-204458.json`
  - `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-remediate-plan-20260305-204458.json`

### Seeding Daemon Safety Hardening

- `bin/qbit-start-seeding-gradual.sh` hardened to fail-closed (`v1.3.4`):
  - halt if any downloading-like state exists in protected scope,
  - halt on `missingFiles`/`error` state set,
  - stop affected hashes immediately.
- Verified behavior:
  - run at `2026-03-05 20:17` halted correctly,
  - `downloading_new=0`, confirming pre-existing DL-like states were detected, not newly created by that run.

### Immediate Next Actions

1. Apply remaining safe actionable lane (8 items):
   - `bin/rehome-57_qb-missing-remediate.sh --plan /home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-remediate-plan-20260305-204458.json --mode apply --only-reason root_name_unique_candidate --limit 8 --max-apply-actions 8`
2. Re-audit:
   - `bin/rehome-56_qb-missing-audit.sh`
3. Keep seeding daemon halted until:
   - actionable lane is cleared,
   - ambiguous/false-missing lanes are explicitly triaged.
4. Triage remaining ambiguous lane via strict mapping path (`rehome-108` + `rehome-102`) before any broad auto-start operations.

### Compact-Critical Continuity Notes

- Worktree and branch context are mandatory:
  - repo: `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`
  - branch: `chatrap/codex-hashall-20260305-181919`
- Current verified state after additional apply batches and targeted recheck:
  - latest audit: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-audit-20260305-204944.json`
  - `missing_total=11`
  - `actionable_total=0`
  - remaining class:
    - `ambiguous_root_name_candidates=11`
- Safe lane is exhausted:
  - latest apply: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-remediate-20260305-204728.json`
  - `selected=8 ok=8 errors=0`
- False-missing lane resolved by explicit qB recheck:
  - rechecked hashes: `1c7dcdd96f7c4a642ef8f94df9e2c0d119dd4ee5`, `23c02140437c1e5f7d510a7e76b7dfd97bc8d5a3`, `2e3809871661d946e1dd04afafa86c9b732dbb42`, `2f4a52783dffaa01470aec79d91c2f7bad653052`
  - recheck API status: `200`
- Seeding daemon is intentionally in HALT state and must stay halted during ambiguity triage:
  - halt indicator: `/home/michael/.logs/hashall/reports/qbit-triage/daemon-halt-reset`
  - do not reset until ambiguous/false-missing lanes are resolved or explicitly accepted.
- `qbit-start-seeding-gradual.sh` hardening was first applied in a different worktree (`main`) and has not yet been ported in this chatrap worktree; re-apply/verify in this branch before daemon re-enable.
- Refresh caveat to preserve:
  - `/home/michael/.logs/hashall/rehome/refresh/20260305-195619.log` completed but upgrade stage mostly incomplete (`queued=190 completed=5`), so refresh success does not imply payload-root recovery.

### Immediate Next Commands (Post-Compact)

1. Reconfirm current missing state:
   - `bin/rehome-56_qb-missing-audit.sh`
2. False-missing lane (recheck-first):
   - run targeted remediation for non-relocation-safe items (no broad moves).
3. Ambiguous lane:
   - build strict mapping with `bin/rehome-108_nohl-basics-qb-build-strict-map.sh`
   - execute controlled pilot with `bin/rehome-102_nohl-basics-qb-repair-pilot.sh` (small limit).
4. Only after both lanes are resolved:
   - re-evaluate daemon halt and consider controlled reset.

## Incident Update (2026-03-05 21:06 EST)

### What Changed

- Applied manual ambiguity lane (`manual_ambiguous_2cand`) for 4 hashes:
  - run: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-remediate-20260305-210322.json`
  - result: `selected=4 ok=4 errors=0`
- Immediate re-audit still showed:
  - `missing_total=11`
  - `actionable_total=0`
  - class: `ambiguous_root_name_candidates=11`
  - audit: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-audit-20260305-210322.json`

### Key Root-Cause Clarification

- Daemon halt at `20:17` was not caused by the newly started batch item:
  - `downloading_new=0`
  - `downloading_preexisting=9`
  - source log: `/home/michael/.logs/hashall/reports/qbit-triage/start-seeding-gradual-20260305-201729.log`
- Safety gate behavior was correct: it detected pre-existing downloading-like torrents in protected scope and stopped them.

### Decisive Recovery Step

- Submitted explicit qB recheck for all 11 remaining ambiguous hashes, then re-ran audit:
  - latest audit: `/home/michael/.logs/hashall/reports/rehome-normalize/nohl-qb-missing-audit-20260305-210637.json`
  - current state: `missing_total=0`, `actionable_total=0`

### Current Operational State

- Missing-files incident is currently cleared in qB audit terms (`0 missing`).
- qB still has active downloading-like torrents unrelated to `missingFiles` count:
  - latest watch snapshot (`21:06:52`): `checking=16 missing=0 down=6 stoppedDL=15`
- Keep daemon halt/reset discipline in place until downloading-like inventory is explicitly reviewed and allowlisted or paused by policy.
