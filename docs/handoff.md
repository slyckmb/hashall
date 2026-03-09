# Handoff Notes

## Key Facts

- `qb-zfs-relocate` remains the hardened live migration backend for guarded qB dataset relocation:
  - entrypoint: `bin/qb-zfs-relocate.py`
  - core module: `src/hashall/qb_zfs_relocate.py`
  - phases: `plan`, `copy`, `verify`, `validate`, `patch`, `resume`, `cleanup`, `rollback`
  - current script semver: `v0.1.6`
  - wrapper-driven runs write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
  - `migrate` supports staged safe cleanup via `--auto-cleanup=safe`
- `hashall` package semver is now `0.4.162`.
- New `rehome` planning capability landed in commit `e572bf8`:
  - new CLI: `hashall rehome relocate-plan`
  - core planner: `src/rehome/normalize.py`
  - this can now generate `rehome apply` batch plans for explicit root-to-root relocations such as `/pool/data/media/torrents/seeding -> /pool/media/torrents/seeding`
  - shared-root sibling groups are now surfaced as one payload move plus synthesized unique destination views when sibling torrents would collide on the same target save path
  - this is the first planner step toward handling `2-to-1 -> 2-to-2` payload/view relocation inside `rehome`
- Important boundary:
  - `rehome relocate-plan` now solves explicit planning for these root-to-root moves
  - the hardened `qb-zfs-relocate` MOVE transport has not yet been merged into `rehome apply`
  - do not overstate this as a fully unified live execution path yet
- Guarded relocation coverage is current:
  - `tests/test_qb_zfs_relocate.py` previously passed locally for the guarded dataset relocation slice
  - latest local validation for the new `rehome` planner slice:
    - `pytest tests/test_rehome_normalize.py tests/test_rehome_atomic_relocation.py tests/test_rehome_catalog_sync.py -q`
    - result: `45 passed`
  - `hashall rehome relocate-plan --help` works
- Live qB relocation already succeeded for `pool-data -> pool-media` via `qb-zfs-relocate`:
  - successful migrate runs are logged under `~/.logs/qb-zfs-relocate/`
  - cleanup completed successfully for prior successful pilot batches
- Operate through `hashall` for planning and `qb-zfs-relocate` for the hardened live mover until the transport merge is complete.

## Immediate Next Work

1. Dry-run the new explicit planner:
   - `hashall rehome relocate-plan --source-device pool-data --source-root /pool/data/media/torrents/seeding --target-device pool-media --target-root /pool/media/torrents/seeding -o out/rehome-plan-pool-data-to-media.json`
   - then `hashall rehome apply out/rehome-plan-pool-data-to-media.json --dryrun`
2. Merge the hardened MOVE transport from `qb-zfs-relocate` into `rehome` execution so `relocate-plan` plans can be applied with the same rsync/verify/fastresume safety contract.
3. Preserve the staged cleanup contract: qB online, live save-path match, prior verify report present, rename-to-staging, observe, then delete.
4. Keep future direct `qb-zfs-relocate` runs on timestamped manifests or pass explicit per-run `--manifest` paths.

## Key Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Operational Reminders

- `hashall refresh --verbose` keeps catalog scans updated; run it after any donor copy.
- `hashall rehome auto --from <src> --to <dst> --limit <n> [--apply]` remains the canonical mover.
- `hashall rehome relocate-plan` is now the explicit planner for root-to-root relocation cases that `auto` does not surface cleanly.
- Do not let qB run `setLocation` as part of normal migration; we rely on offline fastresume repointing.
- Keep the guard log tailing commands handy for monitoring long runs.
