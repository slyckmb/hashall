# Hashall Ops Log (Living)

Last updated: 2026-02-26

## Execution Model

- User runs all mutating CLI locally to monitor live behavior.
- Agent does not run mutating CLI commands without explicit approval.
- Run one mutating pipeline command at a time to avoid qB/db contention.

## Current Snapshot

- qbit-repair script line: `bin/qbit-repair-batch.sh` v1.6.1.
- T1/T2 campaign moved into db-refresh/rehome pipeline.
- Latest T2 run (`--limit 30 --apply`) returned `0 candidates` with `26 blacklisted`.
- DB UUID migration completed (`dev-XX` -> `zfs-*`) before rescans.
- DB refresh scan steps completed for stash/pool/hotspare.
- New repair safety + ranking features implemented:
  - Phase 100 emits `tracker_key`, `tracker_name`, `normalized_tags`, `current_payload_root`.
  - Phase 101 supports tracker-aware scoring (`--tracker-aware`) and tracker alias normalization via `tracker-registry.yml`.
  - Phase 101 now persists ranked candidates with payload roots and score breakdown.
  - Phase 102 supports ranked candidate attempts (`--candidate-top-n`) and optional fallback (`--candidate-fallback`).
  - Phase 102 has a hard apply gate for Phase 103 ownership conflicts (override: `--allow-ownership-conflicts`).
  - New Phase 103 script: `bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh`.
- Link dedup apply plans completed:
  - Plan 30 (`data`): 54 completed, 56 skipped, 0 failed, ~123.6 GB saved
  - Plan 31 (`stash`): 984 completed, 154 skipped, 0 failed, ~2.28 TB saved
  - Plan 32 (`spare`): 409 completed, 2 skipped, 0 failed, ~216.1 GB saved
  - Aggregate saved: ~2.62 TB

## Known Issues / TODO

- `qbit-repair-batch`: investigate hash tracking around `checkUP -> pausedDL/stoppedDL` transitions.
  - Example: `a047ce7c` observed at ~83% in qB while script still treated it as persistent `stoppedDL`.
- `link_plans` summary row for plan 30 may show stale counters; `link_actions` is the source of truth.
- SQLite lock contention still appears under concurrent heavy operations; keep single-writer discipline.
- Device identity hardening TODO: prefer stable filesystem identity over transient numeric `device_id` for long-lived references.

## Next Ordered Steps

1. `bin/db-refresh-step4-payload-sync.sh`
2. `bin/rehome-89_nohl-basics-qb-automation-audit.sh`
3. `bin/rehome-89_nohl-basics-qb-automation-audit.sh --mode apply` (only if audit flags risks)
4. `bin/rehome-100_nohl-basics-qb-repair-baseline.sh`
5. `bin/rehome-101_nohl-basics-qb-candidate-mapping.sh --tracker-aware --candidate-top-n 10`
6. `bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh` (must be clean before Phase 102 apply)
7. `bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode dryrun --limit 10 --candidate-top-n 3 --candidate-fallback`
8. `bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 10 --candidate-top-n 3 --candidate-fallback`
9. `bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh` (post-apply verification)
10. `bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode apply --limit 100 --candidate-top-n 3 --candidate-fallback` (repeat until drained)

## Log Locations

- qbit triage logs: `~/.logs/hashall/reports/qbit-triage/`
- db-refresh logs: `~/.logs/hashall/reports/db-refresh/`
- hashall runtime log: `~/.logs/hashall/hashall.log`
- jdupes per-plan logs: `~/.logs/hashall/jdupes/`
