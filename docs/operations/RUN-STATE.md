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

- `hashall refresh --verbose` is healthy again and validates `stash`, `pool-media`, `pool-data`, and `spare` roots.
- Stable `fs_uuid` entries are enforced; `device_id` stays as runtime metadata.
- The catalog now updates known movers immediately rather than waiting for a later refresh.

## qB Guarding

- `qb-start-seeding-gradual.sh` now halts only on newly flipped downloading-like torrents; preexisting download-like states no longer trigger safety gates.
- StoppedDL drain/apply wraps and path watchers continue to use the shared cache agent for observability.
- `hashall rehome qb-missing-audit` now classifies stale-root `missingFiles` cohorts against qB, fastresume, and rehome history.
- Live audit result on 2026-03-08:
  - `49` `missingFiles` items map cleanly from old `/pool/data/...` roots to existing `/pool/media/...` payloads
  - classification: `root_drift_after_rehome_reuse`
  - this points at legacy REUSE path drift, not current `qb-zfs-relocate` pilot mutations

## Known Gaps

1. Shared-root payload groups can now be planned and executed in theory, but the new execution path still needs a live end-to-end pilot.
2. `rehome auto` still favors donor-backed MOVE discovery and does not replace `rehome relocate-plan` for explicit root-to-root cases.
3. Cleanup/canonical-root accounting should continue to dedupe by payload root, not by torrent hash.
4. The 49-item legacy stale-root cohort still needs controlled live remediation.

## Logs to Watch

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Immediate Checklist

1. Resolve and rerun the hung `hashall refresh --verbose` task if needed before using catalog state for live decisions.
2. Pilot one explicit `MOVE` apply for `/pool/data -> /pool/media`, with a shared-root sibling case included.
3. Export the `49` stale-root `missingFiles` hashes with `hashall rehome qb-missing-audit` and remediate them in small batches.
4. Keep direct `qb-zfs-relocate` wrapper runs only for ad hoc troubleshooting or manifest-specific replay.
