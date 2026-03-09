# Operational Run State

Last updated: 2026-03-08

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

## qB Guarding

- `qb-start-seeding-gradual.sh` now halts only on newly flipped downloading-like torrents; preexisting download-like states no longer trigger safety gates.
- StoppedDL drain/apply wraps and path watchers continue to use the shared cache agent for observability.
- `hashall rehome qb-missing-audit` now classifies stale-root `missingFiles` cohorts against qB, fastresume, and rehome history.
- Live audit result on 2026-03-08:
  - `49` `missingFiles` items map cleanly from old `/pool/data/...` roots to existing `/pool/media/...` payloads
  - current tool classification: `root_drift_fastresume_stale`
  - this points at legacy stale-root drift, not current `qb-zfs-relocate` pilot mutations
- `qb-start-seeding-gradual` halt at `2026-03-08 14:34` is explained:
  - `35` halted hashes are a direct subset of the audited `49`
  - the daemon tripped on preexisting `missingFiles` rows in protected scope, not on a newly started torrent

## Known Gaps

1. Shared-root payload groups can now be planned and executed in theory, but the new execution path still needs a live end-to-end pilot.
2. `rehome auto` still favors donor-backed MOVE discovery and does not replace `rehome relocate-plan` for explicit root-to-root cases.
3. Cleanup/canonical-root accounting should continue to dedupe by payload root, not by torrent hash.
4. The 49-item legacy stale-root cohort still needs controlled live remediation.
5. Current uncommitted worktree fix:
   - `qb-zfs-relocate validate` should trust successful offline verify over stale qB `progress=0.0` for `reused_existing_dest` rows
   - this is required to finish the live `Stranger.Things.S02` remediation pilot

## Logs to Watch

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Immediate Checklist

1. Finish and validate the uncommitted `torrent_not_complete` override for `reused_existing_dest` rows in `qb-zfs-relocate`.
2. Re-run the `Stranger.Things.S02` 3-hash remediation dry-run/apply pilot from `out/qb-zfs-relocate/remediate-stranger-things-s02-20260309/manifest.json`.
3. Export the `49` stale-root `missingFiles` hashes with `hashall rehome qb-missing-audit` and remediate them in small batches.
4. Pilot one explicit `MOVE` apply for `/pool/data -> /pool/media`, with a shared-root sibling case included.
