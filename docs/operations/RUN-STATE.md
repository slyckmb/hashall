# Operational Run State

Last updated: 2026-03-10

## Pool Migration Status

- Donor acquisition and offline attach are the shared backbone for both `REUSE` and `MOVE`.
- The current rsync-based donor transfer is still the data mover; qB is metadata-only.
- `REUSE` continues in small batches; each apply must finish with `stoppedup`/`stalledup`, no new downloads, and clean cleanup messages.
- `qb-zfs-relocate` has already proven the guarded live `pool-data -> pool-media` mover for pilot batches.
- `rehome` now has an explicit root-to-root planner for this domain:
  - `hashall rehome relocate-plan --source-device pool-data --source-root /pool/data/media/torrents/seeding --target-device pool-media --target-root /pool/media/torrents/seeding`
  - shared-root sibling collisions are now surfaced and get synthesized unique destination views.
- `rehome apply` now uses the hardened `qb-zfs-relocate` backend for donor verification, offline fastresume patching, restart checks, and deferred cleanup.

## Current `MOVE` Risk

- `MOVE` has been refactored to use the same offline fastresume attach constructor after donor acquisition.
- The new path still needs a live pilot before it can be trusted at scale.
- Operational guard: do not run `MOVE` apply at scale until a pilot shows no `MV`/`moving`, no download-like flip, and proper cleanup provenance.
- Do not treat `rehome auto` returning `0 MOVE groups` as the final answer for explicit root-to-root relocation anymore; use `rehome relocate-plan` for that case.
- The current safe model is unified:
  - use `rehome relocate-plan` or `rehome auto` for planning
  - use `rehome apply` for execution
  - keep `qb-zfs-relocate` available for direct wrapper-driven dataset migration or troubleshooting

## Refresh / Identity State

- The latest `hashall refresh --verbose` did not hang; it finished `PARTIAL`.
- The scan stages succeeded, but payload sync failed its quality gate:
  - `queued=24`
  - `completed=15`
  - `failed=0`
  - ratio `0.625 < 0.900`
- The incomplete roots were zero-file old `/pool/data/...` entries from the stale-root qB cohort.
- Stable `fs_uuid` entries are enforced; `device_id` stays as runtime metadata.
- The catalog now updates known movers immediately rather than waiting for a later refresh.
- Do not treat the prior `PARTIAL` refresh as the current truth forever; the stale-root qB cohort has since been remediated and refresh should be rerun after the remaining repair lane is reduced.

## qB Guarding

- `qb-start-seeding-gradual.sh` now halts only on newly flipped downloading-like torrents; preexisting download-like states no longer trigger safety gates.
- StoppedDL drain/apply wraps and path watchers continue to use the shared cache agent for observability.
- `hashall rehome qb-missing-audit` now classifies stale-root `missingFiles` cohorts against qB, fastresume, and rehome history.
- Historical live audit result on 2026-03-08:
  - `49` `missingFiles` items mapped cleanly from old `/pool/data/...` roots to existing `/pool/media/...` payloads
  - tool classification: `root_drift_fastresume_stale`
  - interpretation: legacy stale-root drift, not current `qb-zfs-relocate` pilot mutations
- That stale-root `missingFiles` lane has now been remediated live.
- Current qB health snapshot:
  - `stalledUP=5138`
  - `uploading=5`
  - `stoppedDL=7`
- The active qB problem lane is now repair-oriented:
  - `7` `stoppedDL` torrents remain and need donor/sibling repair rather than path-drift relocation
- `qb-start-seeding-gradual` halt at `2026-03-08 14:34` is explained historically:
  - `35` halted hashes were a direct subset of the old audited `49`
  - the daemon tripped on preexisting `missingFiles` rows in protected scope, not on a newly started torrent

## Known Gaps

1. Shared-root payload groups can now be planned and executed in theory, but the new execution path still needs a live end-to-end pilot.
2. `rehome auto` still favors donor-backed MOVE discovery and does not replace `rehome relocate-plan` for explicit root-to-root cases.
3. Cleanup/canonical-root accounting should continue to dedupe by payload root, not by torrent hash.
4. The active live gap is no longer stale-root remediation; it is the remaining `7`-item `stoppedDL` repair lane.
5. `hashall payload siblings` still has a separate read-only catalog bug:
   - `src/hashall/cli.py` `payload_siblings()` opens the DB without `read_only=True`
   - this triggers a WAL-mode write attempt on the live read-only DB path even though `src/hashall/model.py` already supports safe read-only connections

## Logs to Watch

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Immediate Checklist

1. Use the hardened repair path for the remaining `7` `stoppedDL` items, starting from:
   - `out/qb-repair-payload-group/20260310-102047-0fff0ce260a5/repair-plan.json`
2. Fix and regression-test the `hashall payload siblings` read-only DB/WAL bug in `src/hashall/cli.py`.
3. Re-run `hashall refresh --verbose` after the `stoppedDL` lane is reduced.
4. Continue with explicit `rehome relocate-plan` / `rehome apply` pilots for root-to-root `MOVE` after the repair lane is under control.
