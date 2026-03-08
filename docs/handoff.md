# Handoff Notes

## Key Facts

- `qb-zfs-relocate` is now implemented for guarded qB dataset relocation:
  - entrypoint: `bin/qb-zfs-relocate.py`
  - core module: `src/hashall/qb_zfs_relocate.py`
  - phases: `plan`, `copy`, `verify`, `validate`, `patch`, `resume`, `cleanup`, `rollback`
  - shared fastresume/bencode path now uses `src/hashall/bencode.py`
  - script semver is now `v0.1.2`
  - wrapper-driven runs now write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json` and keep `current-manifest.txt` + `latest-manifest.json` pointers
  - `migrate` can now opt into staged safe cleanup via `--auto-cleanup=safe`
- Source-layout CLI bootstrap is now present:
  - `python3 -m hashall` works from repo root via local `hashall/` + `rehome/` bootstrap packages.
  - package semver is now `0.4.157`
- Guarded relocation coverage is in place:
  - targeted regression set now includes `tests/test_qb_zfs_relocate.py`
  - last local verification for the relocation/tooling slice: `28 passed` in `tests/test_qb_zfs_relocate.py`
- Live qB relocation has now succeeded for the `pool-data -> pool-media` workflow:
  - successful migrate runs are logged at `~/.logs/qb-zfs-relocate/20260308-120340-migrate-pid1497678.*` and `~/.logs/qb-zfs-relocate/20260308-123054-migrate-pid1658492.*`
  - both completed with `resume_ok=2` and `exit_code=0`
  - cleanup dry-runs against both successful batches returned `blocked=0`, `dryrun=2`, `source_missing=0`
- Operate through `hashall` (script-level commands) rather than the removed `rehome` entrypoint.
- Pool migration now relies on a shared donor-acquisition + offline fastresume attach constructor for both `REUSE` and `MOVE`.
- `REUSE` applies already succeed via offline fastresume with no `MV`/`moving`, while cleanup notices still need refinement.
- `MOVE` uses the same offline attach path but remains unproven live; the next gate is one live `MOVE` pilot.
- `pool-data -> pool-media` dry-runs report `0 MOVE groups available`, yet numerous `/pool/data` payloads still exist; watch the inventory carefully.
- qB gradual-seeding daemon and path watchers are tuned to avoid halting on preexisting download-like states.
- Active gate: stash → pool-media `REUSE` pilot `rehome_runs.id=338` is running; do not scale `~noHL` until it finishes cleanly.

## Immediate Next Work

1. Keep future relocation runs on the timestamped-manifest wrappers or pass explicit per-run `--manifest` paths when invoking the tool directly.
2. If space pressure requires source cleanup, use `cleanup --dryrun` first, then `--apply --confirm-cleanup`, or opt into `migrate --auto-cleanup=safe` only after observing a clean pilot.
3. Preserve the staged cleanup contract: qB online, live save-path match, prior verify report present, rename-to-staging, observe, then delete.
4. Continue the existing stash/pool-media `REUSE` and `MOVE` operator follow-up work as previously planned.

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
