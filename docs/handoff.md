# Handoff Notes

## Key Facts

- `qb-zfs-relocate` is now implemented for guarded qB dataset relocation:
  - entrypoint: `bin/qb-zfs-relocate.py`
  - core module: `src/hashall/qb_zfs_relocate.py`
  - phases: `plan`, `copy`, `verify`, `validate`, `patch`, `resume`, `cleanup`, `rollback`
  - shared fastresume/bencode path now uses `src/hashall/bencode.py`
- Source-layout CLI bootstrap is now present:
  - `python3 -m hashall` works from repo root via local `hashall/` + `rehome/` bootstrap packages.
- Guarded relocation coverage is in place:
  - targeted regression set now includes `tests/test_qb_zfs_relocate.py`
  - last local verification for the relocation/tooling slice: `34 passed`
  - note: this was code/test validation only; no live qB relocation batch was executed here.
- Operate through `hashall` (script-level commands) rather than the removed `rehome` entrypoint.
- Pool migration now relies on a shared donor-acquisition + offline fastresume attach constructor for both `REUSE` and `MOVE`.
- `REUSE` applies already succeed via offline fastresume with no `MV`/`moving`, while cleanup notices still need refinement.
- `MOVE` uses the same offline attach path but remains unproven live; the next gate is one live `MOVE` pilot.
- `pool-data -> pool-media` dry-runs report `0 MOVE groups available`, yet numerous `/pool/data` payloads still exist; watch the inventory carefully.
- qB gradual-seeding daemon and path watchers are tuned to avoid halting on preexisting download-like states.
- Active gate: stash → pool-media `REUSE` pilot `rehome_runs.id=338` is running; do not scale `~noHL` until it finishes cleanly.

## Immediate Next Work

1. Run a real `qb-zfs-relocate plan` dry-run against the intended qB selection and confirm manifest path semantics on live metadata.
2. Confirm the chosen verifier source (`BT_backup/*.torrent` vs export fallback) is complete in the live environment before any copy/patch attempt.
3. Validate qB stop/start control wiring (`--qb-container` or command hooks) on the real host before patch mode.
4. After that, continue the existing stash/pool-media `REUSE` and `MOVE` operator follow-up work as previously planned.

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
