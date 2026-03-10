# Handoff Notes

## Key Facts

- `qb-zfs-relocate` remains the hardened live migration backend for guarded qB dataset relocation:
  - entrypoint: `bin/qb-zfs-relocate.py`
  - core module: `src/hashall/qb_zfs_relocate.py`
  - phases: `plan`, `copy`, `verify`, `validate`, `patch`, `resume`, `cleanup`, `rollback`
  - current script semver: `v0.1.9`
  - wrapper-driven runs write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
  - `migrate` supports staged safe cleanup via `--auto-cleanup=safe`
- `hashall` package semver is now `0.4.168`.
- `qb-repair-payload-group.sh` was hardened in commit `5d83419`:
  - wrapper: `bin/qb-repair-payload-group.sh`
  - core module: `src/hashall/qb_repair_payload_group.py`
  - script semver: `v0.2.0`
  - validates that `--good` and `--broken` share the same `payload_hash` before any apply step
  - uses dynamic catalog device/file-table resolution, full relative-path file matching, shared fastresume backup/journal logic, and per-run artifacts under `out/qb-repair-payload-group/<stamp>-<hash>/`
  - targeted validation now passes locally:
    - `pytest tests/test_fastresume.py tests/test_qb_repair_payload_group.py -q`
    - result: `8 passed`
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
  - the original audited live cohort was `49` `missingFiles` items classified as `root_drift_fastresume_stale`
  - that stale-root `missingFiles` lane has now been remediated live in waves using `qb-zfs-relocate`
  - current qB non-healthy set is no longer `missingFiles`; the live stoppedDL repair lane is now clear
  - current qB state snapshot:
    - `stalledUP=5145`
    - `uploading=5`
  - there are no remaining `stoppedDL`, `stoppedUP`, or `missingFiles` rows in the active lane
- Guarded relocation coverage is current:
  - `tests/test_qb_zfs_relocate.py` previously passed locally for the guarded dataset relocation slice
  - `hashall rehome relocate-plan --help` works
  - `hashall rehome qb-missing-audit --help` works
- Live qB relocation already succeeded for `pool-data -> pool-media` via `qb-zfs-relocate`:
  - successful migrate runs are logged under `~/.logs/qb-zfs-relocate/`
  - cleanup completed successfully for prior successful pilot batches
- Treat the older 49-item `missingFiles` cohort as a legacy remediation lane, not proof of a current `qb-zfs-relocate` fastresume scribbler.

## Immediate Next Work

1. Hardened live repair succeeded and the sidecar-fetch lane is now clear.
   - commit `fe6b0fb` fixed qB API readiness checks after container restart
   - `0fff0ce260a58b789f857f6ad085a5d03622b952` repaired from sibling donor and now seeds normally again
   - live artifact: `out/qb-repair-payload-group/20260310-164254-0fff0ce260a5/repair-plan.json`
2. The remaining sidecar blockers were resolved operationally.
   - qB resume attempts initially failed with `Permission denied` creating missing `.nfo` / `.srt` files
   - root cause: the six payload directories were `root:root 755` while qB runs as uid `1026` gid `101`
   - minimal live fix: change ownership of just those six directories to `1026:101`, then resume the six torrents
   - result: qB fetched the missing sidecars and all six returned to `stalledUP 100%`
3. `hashall payload siblings` read-only bug is fixed in commit `74ea2b5`.
4. Re-run `hashall refresh --verbose` now that the stoppedDL lane is clear.
   - the last `PARTIAL` refresh was explained by the old stale-root `/pool/data/...` cohort, which has since been remediated
5. Dry-run the new explicit planner:
   - `hashall rehome relocate-plan --source-device pool-data --source-root /pool/data/media/torrents/seeding --target-device pool-media --target-root /pool/media/torrents/seeding -o out/rehome-plan-pool-data-to-media.json`
   - then `hashall rehome apply out/rehome-plan-pool-data-to-media.json --dryrun`
6. Preserve the staged cleanup contract: qB online, live save-path match, prior verify report present, rename-to-staging, observe, then delete.
7. Keep future direct `qb-zfs-relocate` runs on timestamped manifests or pass explicit per-run `--manifest` paths.

## Key Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## Operational Reminders

- `hashall refresh --verbose` keeps catalog scans updated; run it after any donor copy.
- `hashall rehome auto --from <src> --to <dst> --limit <n> [--apply]` remains the canonical mover.
- `hashall rehome relocate-plan` is now the explicit planner for root-to-root relocation cases that `auto` does not surface cleanly.
- `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` is the canonical proof path for the legacy stale-root cohort; that lane is no longer the active blocker now that the `missingFiles` set has been cleared.
- Do not let qB run `setLocation` as part of normal migration; we rely on offline fastresume repointing.
- Keep the guard log tailing commands handy for monitoring long runs.
