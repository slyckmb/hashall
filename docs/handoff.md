# Handoff Notes

## Key Facts

- Operate through `hashall` (script-level commands) rather than the removed `rehome` entrypoint.
- Pool migration now relies on a shared donor-acquisition + offline fastresume attach constructor for both `REUSE` and `MOVE`.
- `REUSE` applies already succeed via offline fastresume with no `MV`/`moving`, while cleanup notices still need refinement.
- `MOVE` uses the same offline attach path but remains unproven live; the next gate is one live `MOVE` pilot.
- `pool-data -> pool-media` dry-runs report `0 MOVE groups available`, yet numerous `/pool/data` payloads still exist; watch the inventory carefully.
- qB gradual-seeding daemon and path watchers are tuned to avoid halting on preexisting download-like states.
- Active gate: stash → pool-media `REUSE` pilot `rehome_runs.id=338` is running; do not scale `~noHL` until it finishes cleanly.

## Immediate Next Work

1. Fix cleanup-source path/provenance so operator messaging references the actual migrated source root.
2. Confirm the stash → pool-media pilot completes cleanly.
3. If clean, scale stash/pool-media `REUSE` cautiously, verifying each batch and watching for any unexpected `MV`/download states.
4. Pilot `MOVE` only once the planner surfaces a real donor-acquisition case and the pilot passes cleanly.
5. After that, resume planning for the `~noHL` migration lane.

## Key Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Operational Reminders

- `hashall refresh --verbose` keeps catalog scans updated; run it after any donor copy.
- `hashall rehome auto --from <src> --to <dst> --limit <n> [--apply]` remains the canonical mover.
- Do not let qB run `setLocation` as part of normal migration; we rely on offline fastresume repointing.
- Keep the guard log tailing commands handy for monitoring long runs.
