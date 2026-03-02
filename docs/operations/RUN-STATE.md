# Run State (Canonical)

Last updated: 2026-03-01
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
  - `bin/rehome-106_nohl-basics-qb-hash-root-report.sh`

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
