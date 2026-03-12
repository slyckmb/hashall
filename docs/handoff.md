# Handoff Notes

## Key Facts

- `qb-zfs-relocate` remains the hardened live migration backend for guarded qB dataset relocation:
  - entrypoint: `bin/qb-zfs-relocate.py`
  - core module: `src/hashall/qb_zfs_relocate.py`
  - phases: `plan`, `copy`, `verify`, `validate`, `patch`, `resume`, `cleanup`, `rollback`
  - current script semver: `v0.1.11`
  - wrapper-driven runs write timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
  - `migrate` supports staged safe cleanup via `--auto-cleanup=safe`
- `hashall` package semver is now `0.4.171`.
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
  - cross-device `REUSE` reruns now support catalog-only catch-up after successful live repoint:
    - executor logs `rehome_reconcile_only`
    - offline verify still runs
    - validate/patch are skipped when qB is already on the target save paths
    - catalog sync then updates the target `payloads` row and `torrent_instances`
  - non-reconcile `MOVE` runs now explicitly stop qB before patch-mode validate:
    - this removes the false `torrent_not_stopped` blocker that appeared after successful copy + offline verify
    - the live `Megalopolis.2024.REPACK...` pilot proved the corrected path
  - small live `rehome` pilots are now green on both major paths:
    - `REUSE`: `The.West.Wing.S07...` cross-device reuse group completed and catalog-synced on rerun via `rehome_reconcile_only`
    - `MOVE`: `Megalopolis.2024.REPACK...` moved from `/pool/data/...` to `/pool/media/...`, verified `exact_tree`, patched, resumed, and left source cleanup deferred
- mixed-state reruns are now handled safely:
  - commit `85b91af` added partial reconcile support for batches where some rows are already repointed and verified while others were skipped
  - post-patch save-path verification now ignores rows that were not actually patched
  - this unblocked the live `Longlegs` mixed-batch rerun
- commit `21ea673` added streamed rsync progress for `rehome` MOVE copy windows:
  - long `MOVE` transfers now emit `copy_progress percent=... elapsed=... eta=...`
  - a long pause after `step=move_payload` is no longer expected on new runs
- New stale-root audit exists for missing qB items:
  - CLI: `hashall rehome qb-missing-audit`
  - the original audited live cohort was `49` `missingFiles` items classified as `root_drift_fastresume_stale`
  - that stale-root `missingFiles` lane has now been remediated live in waves using `qb-zfs-relocate`
  - current qB non-healthy set is no longer `missingFiles`; the live stoppedDL repair lane is now clear
- current qB state snapshot after the repair lane clear:
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
4. `hashall refresh --verbose` has now returned `OK` after the stale-root / stoppedDL cleanup work.
   - `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` now returns `0`
5. The `West Wing S07` cross-device `REUSE` pilot is now green:
   - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-155600-8277eae774b3591b/`
   - all three siblings ended `stalledUP 100%` on `/pool/media/...`
   - catalog now shows:
     - `2d9004e9... -> payload_id 13703, device_id 141, save_path /pool/media/.../Aither (API)`
     - `8bf2aec2... -> payload_id 13703, device_id 141, save_path /pool/media/.../TorrentLeech`
     - `f18b8cd0... -> payload_id 13703, device_id 141, save_path /pool/media/.../_rehome-unique/...`
6. The `Megalopolis.2024.REPACK...` `MOVE` pilot is now green:
   - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-173250-692ffa9407a574f4/`
   - all three sibling views verified `exact_tree`
   - qB ended `stalledUP 100%` on the target roots
   - catalog now shows:
     - `14e3deab... -> payload_id 13557, device_id 141, save_path /pool/media/.../Aither (API)`
     - `4da8ec78... -> payload_id 9704, device_id 141, save_path /pool/media/.../PrivateHD`
     - `6befda30... -> payload_id 13557, device_id 141, save_path /pool/media/.../_rehome-unique/...`
   - source removal stayed deferred and manual
7. The first mixed live scale-up is now green in curated form:
   - bad candidate excluded:
     - `Shining.Girls...` REUSE group from `mixed4`
     - reason: all `3` rows failed destination offline verify as `partial_match`, so this is a real bad reuse candidate, not a planner-only false positive
   - successful batch plan:
     - `out/rehome-plan-pool-data-to-media-mixed3-no-shining.json`
   - successful live results:
     - `Longlegs...` REUSE completed via `rehome_reconcile_subset`
       - `8` rows reconciled cleanly on `/pool/media/...`
       - `1` `dest_missing` row was left untouched on `/pool/data/...`
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-180840-a1041c6049c66abe/`
     - `Brave.New.World.US.S01...` MOVE completed successfully
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-182010-66eebb2df636b12a/`
       - all `4` torrents ended `stalledUP 100%` on `/pool/media/...`
     - `Greenland.2020.Repack...` MOVE completed successfully
       - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-183147-adf55dffe6443f6a/`
       - all `8` torrents ended `stalledUP 100%` on `/pool/media/...`
   - source cleanup remained deferred/manual for all three payload groups
8. Second curated live scale-up is now also green:
   - plan file: `out/rehome-plan-pool-data-to-media-next4c.json`
   - all four `MOVE` payload groups completed successfully:
     - `Brave.New.World.US.S01...`
     - `Greenland.2020.Repack...`
     - `Azrael...`
     - `Stranger.Things.S03...`
   - shared log ended with:
     - `✅ Summary: 25 torrent(s) checked, all in acceptable state`
9. Two `MOVE` carve-outs are now known and should stay out of the clean batch lane until separately investigated:
   - `Magic.City.S01...`
     - failed after copy with `Target file count mismatch after move`
     - observed runtime stats:
       - source: `8 files / 106474639951 bytes`
       - target: `9 files / 110028001871 bytes`
     - interpretation: dirty/preexisting target content, not a broad fastresume corruption signal
   - `Wilding.2023...`
     - copy completed and target verify passed
     - offline verify then sat at `checking_files 0.00%` for `15m+`
     - interpretation: verifier-control-path issue until re-tested, not proof of mover corruption
10. Deep audit conclusion on the recent failures:
    - there is no evidence of a broad errant fastresume scribbler in current `rehome` / `qb-zfs-relocate`
    - the recent failures have been:
      - stale-root drift already remediated
      - dirty/preexisting destination content (`Magic City`)
      - bad reuse candidate (`Shining.Girls`)
      - verifier stall behavior (`Wilding`)
11. Preserve the staged cleanup contract: qB online, live save-path match, prior verify report present, rename-to-staging, observe, then delete.
12. Keep future direct `qb-zfs-relocate` runs on timestamped manifests or pass explicit per-run `--manifest` paths.

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
