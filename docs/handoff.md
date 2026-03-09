# Handoff Notes

## Key Facts

- `qb-zfs-relocate` remains the hardened live migration backend for guarded qB dataset relocation:
  - entrypoint: `bin/qb-zfs-relocate.py`
  - core module: `src/hashall/qb_zfs_relocate.py`
  - phases: `plan`, `copy`, `verify`, `validate`, `patch`, `resume`, `cleanup`, `rollback`
  - current script semver: `v0.1.8`
  - wrapper-driven runs write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
  - `migrate` supports staged safe cleanup via `--auto-cleanup=safe`
- `hashall` package semver is now `0.4.164`.
- New `rehome` planning capability landed in commit `e572bf8`:
  - new CLI: `hashall rehome relocate-plan`
  - core planner: `src/rehome/normalize.py`
  - this can now generate `rehome apply` batch plans for explicit root-to-root relocations such as `/pool/data/media/torrents/seeding -> /pool/media/torrents/seeding`
  - shared-root sibling groups are now surfaced as one payload move plus synthesized unique destination views when sibling torrents would collide on the same target save path
  - this is the first planner step toward handling `2-to-1 -> 2-to-2` payload/view relocation inside `rehome`
- `rehome apply` now uses the hardened relocation backend for MOVE/REUSE attachment:
  - donor acquisition remains qB-metadata-only and copy-first
  - offline verify, validate, patch, restart checks, and deferred cleanup reuse the guarded `qb-zfs-relocate` contract
  - tests covering the merged path now pass locally:
    - `pytest tests/test_rehome_atomic_relocation.py tests/test_rehome_catalog_sync.py tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py -q`
    - result: `47 passed`
- New stale-root audit exists for missing qB items:
  - CLI: `hashall rehome qb-missing-audit`
  - audited live cohort: `49` `missingFiles` items
  - current tool classification: `root_drift_fastresume_stale`
  - evidence: old `/pool/data/...` qB + fastresume paths, mapped payload present at `/pool/media/...`
  - note: catalog linkage for this cohort is incomplete, so the audit command does not currently prove `latest_rehome_reuse_success` for all 49 rows even though earlier manual investigation pointed at older rehome events
- Guarded relocation coverage is current:
  - `tests/test_qb_zfs_relocate.py` previously passed locally for the guarded dataset relocation slice
  - `hashall rehome relocate-plan --help` works
  - `hashall rehome qb-missing-audit --help` works
- Live qB relocation already succeeded for `pool-data -> pool-media` via `qb-zfs-relocate`:
  - successful migrate runs are logged under `~/.logs/qb-zfs-relocate/`
  - cleanup completed successfully for prior successful pilot batches
- Treat the older 49-item `missingFiles` cohort as a legacy remediation lane, not proof of a current `qb-zfs-relocate` fastresume scribbler.

## Immediate Next Work

1. Refresh is not hung; the latest `hashall refresh --verbose` finished `PARTIAL`.
   - root cause: payload-sync quality gate failed because `24` old `/pool/data/...` upgrade roots were queued and only `15` completed
   - the incomplete roots were zero-file stale-root entries from the current `missingFiles` cohort
2. Dry-run the new explicit planner:
   - `hashall rehome relocate-plan --source-device pool-data --source-root /pool/data/media/torrents/seeding --target-device pool-media --target-root /pool/media/torrents/seeding -o out/rehome-plan-pool-data-to-media.json`
   - then `hashall rehome apply out/rehome-plan-pool-data-to-media.json --dryrun`
3. Active live remediation pilot:
   - manifest: `out/qb-zfs-relocate/remediate-stranger-things-s02-20260309/manifest.json`
   - hashes: `18843b7d...`, `1e48e188...`, `0f5f679b...`
   - dry-run result: all `3` hashes reused existing destination payload and verified `exact_tree`
   - current blocker: `validate` still trusts stale qB `progress=0.0` on `missingFiles` rows and adds `torrent_not_complete`
   - uncommitted fix in worktree: `src/hashall/qb_zfs_relocate.py` + `tests/test_qb_zfs_relocate.py`
4. Preserve the staged cleanup contract: qB online, live save-path match, prior verify report present, rename-to-staging, observe, then delete.
5. Keep future direct `qb-zfs-relocate` runs on timestamped manifests or pass explicit per-run `--manifest` paths.

## Key Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Operational Reminders

- `hashall refresh --verbose` keeps catalog scans updated; run it after any donor copy.
- `hashall rehome auto --from <src> --to <dst> --limit <n> [--apply]` remains the canonical mover.
- `hashall rehome relocate-plan` is now the explicit planner for root-to-root relocation cases that `auto` does not surface cleanly.
- `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` is the canonical proof path for the current legacy stale-root `missingFiles` cohort.
- Do not let qB run `setLocation` as part of normal migration; we rely on offline fastresume repointing.
- Keep the guard log tailing commands handy for monitoring long runs.
