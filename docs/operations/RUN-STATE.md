# Operational Run State

Last updated: 2026-03-07

## Pool Migration Status

- Donor acquisition and offline attach are the shared backbone for both `REUSE` and `MOVE`.
- The current rsync-based donor transfer is still the data mover; qB is metadata-only.
- `REUSE` continues in small batches; each apply must finish with `stoppedup`/`stalledup`, no new downloads, and clean cleanup messages.
- `pool-data -> pool-media` dry-runs show `0 MOVE groups available` when filtering by the strict safety criteria, but the catalog still contains many `/pool/data` payloads and the watcher reports >1.3 T of old-root usage.
- Active gate: stash → pool-media `REUSE` pilot `rehome_runs.id=338` is running, and we do not scale `~noHL` until it finishes cleanly.

## Current `MOVE` Risk

- `MOVE` has been refactored to use the same offline fastresume attach constructor after donor acquisition.
- The new path still needs a live pilot before it can be trusted at scale.
- Operational guard: do not run `MOVE` apply at scale until a pilot shows no `MV`/`moving`, no download-like flip, and proper cleanup provenance.
- If the planner returns `0 MOVE groups`, move to the next source domain instead of forcing a synthetic move.
- The interim safe model for any copy is `copy-then-REUSE` (external transfer first, then shared attach).

## Refresh / Identity State

- `hashall refresh --verbose` is healthy again and validates `stash`, `pool-media`, `pool-data`, and `spare` roots.
- Stable `fs_uuid` entries are enforced; `device_id` stays as runtime metadata.
- The catalog now updates known movers immediately rather than waiting for a later refresh.

## qB Guarding

- `qb-start-seeding-gradual.sh` now halts only on newly flipped downloading-like torrents; preexisting download-like states no longer trigger safety gates.
- StoppedDL drain/apply wraps and path watchers continue to use the shared cache agent for observability.

## Known Gaps

1. Cleanup-source path/provenance still sometimes references legacy `/pool/data/seeds/...` roots instead of the actual migrated source.
2. `MOVE` has been refactored off qB relocation semantics but still awaits a pilot validation.
3. Catalog updates for migration actions should be immediate, not wait for another refresh pass.
4. The active stash → pool-media pilot (`rehome_runs.id=338`) is long-running; inspect the sequential rechecks once it finishes.

## Logs to Watch

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Immediate Checklist

1. Fix cleanup-source path/provenance so operator messaging cites the actual migrated root.
2. Confirm the stash → pool-media pilot completes cleanly.
3. If clean, continue stash/pool-media `REUSE` batches incrementally.
4. Only pilot `MOVE` once the planner surfaces a donor-acquisition candidate and the pilot passes without `MV`/download issues.
5. After that, resume planning for `~noHL`.
