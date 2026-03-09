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
- Important boundary: this is a planning integration step, not yet a full execution merge. `rehome apply` still needs the hardened `qb-zfs-relocate` MOVE backend merged in before we should treat it as the canonical live mover for this path.

## Current `MOVE` Risk

- `MOVE` has been refactored to use the same offline fastresume attach constructor after donor acquisition.
- The new path still needs a live pilot before it can be trusted at scale.
- Operational guard: do not run `MOVE` apply at scale until a pilot shows no `MV`/`moving`, no download-like flip, and proper cleanup provenance.
- Do not treat `rehome auto` returning `0 MOVE groups` as the final answer for explicit root-to-root relocation anymore; use `rehome relocate-plan` for that case.
- The interim safe model remains: use `qb-zfs-relocate` for hardened live MOVE and use `rehome relocate-plan` to surface the payload-group/view topology cleanly.

## Refresh / Identity State

- `hashall refresh --verbose` is healthy again and validates `stash`, `pool-media`, `pool-data`, and `spare` roots.
- Stable `fs_uuid` entries are enforced; `device_id` stays as runtime metadata.
- The catalog now updates known movers immediately rather than waiting for a later refresh.

## qB Guarding

- `qb-start-seeding-gradual.sh` now halts only on newly flipped downloading-like torrents; preexisting download-like states no longer trigger safety gates.
- StoppedDL drain/apply wraps and path watchers continue to use the shared cache agent for observability.

## Known Gaps

1. The hardened `qb-zfs-relocate` MOVE transport is not yet merged into `rehome apply`.
2. Shared-root payload groups can now be planned, but the execution path still needs a live end-to-end pilot once the transport merge lands.
3. `rehome auto` still favors donor-backed MOVE discovery and does not replace `rehome relocate-plan` for explicit root-to-root cases.
4. Cleanup/canonical-root accounting should continue to dedupe by payload root, not by torrent hash.

## Logs to Watch

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Immediate Checklist

1. Dry-run `hashall rehome relocate-plan` for `/pool/data -> /pool/media` and inspect the generated `view_targets`.
2. Merge the rsync/verify/fastresume MOVE backend from `qb-zfs-relocate` into `rehome` execution.
3. Pilot one explicit `MOVE` apply only after that transport merge, with a shared-root sibling case included.
4. Keep direct live dataset moves on `qb-zfs-relocate` until the unified `rehome` execution path is proven.
