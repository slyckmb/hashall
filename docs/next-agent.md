# Next Agent Entry (Compact-Safe)

Primary run-state source:
`docs/operations/RUN-STATE.md`

If context is compacted, recover with this sequence:

0. Recover the new guarded qB relocation tooling state:
   - `bin/qb-zfs-relocate.py` (`v0.1.4`)
   - `src/hashall/qb_zfs_relocate.py`
   - `src/hashall/bencode.py`
   - repo-root `python3 -m hashall` bootstrap now works via local `hashall/` + `rehome/` packages.
   - wrapper runs now keep timestamped manifests under `out/qb-zfs-relocate/pool-data-to-media/runs/<stamp>/manifest.json`
1. Confirm branch/worktree:
   - `chatrap/codex-hashall-20260307-234425`
   - `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260307-234425`
2. Confirm stoppedDL pipeline baseline:
   - run `qb-stoppeddl-bucket` and verify `active=0` or current live count.
   - note: drain no-op fix is commit `657eccc` (`v0.1.23`).
3. Current active rehome state:
   - `hashall` semver is `0.7.0`
   - active docs are now reduced to the canonical set in `docs/README.md`; do not recreate active-tree stubs, use `docs/archive/2026-doc-consolidation/` for superseded material
   - anchor invariant:
     - each qB item needs its own correct payload tree on disk
     - that tree should normally be instantiated from donor bytes via hardlinks, not redundant physical copies
     - `unique target root` means unique per-item payload structure
   - newest scan/refresh drift hardening:
     - `hashall scan` now supports `--drift-policy metadata|quick|full`
     - `hashall refresh --verbose` now accepts:
       - `--scan-hash-mode fast|full|upgrade`
       - `--drift-policy metadata|quick|full`
     - use `--drift-policy quick` for routine confidence scans and `--drift-policy full` for true drift-audit passes
   - latest hardlink-normalization fixes:
     - `src/rehome/view_builder.py` now relinks identical preexisting destination files to donor inodes
     - `bin/qb-repair-fresh.py` now does the same during fresh repair prep
     - these two fixes close the known duplicate-byte leak that was leaving new jdupes groups behind after otherwise-successful runs
   - latest planner stale-no-op hardening:
     - `relocate-plan` now skips groups when all per-hash view targets are already `source_save_path == target_save_path`
     - this removes fully converged families from the active remainder even when source cleanup is still deferred
   - live Brave proof:
     - `~/.logs/hashall/reports/rehome-relocate/20260313-114142-66eebb2df636b12a/`
     - fresh remainder plan drops from `31` to `29` candidates
   - latest bridge hardening after the first Twisters failures:
     - planner prefers surviving target donors for stale already-targeted rows
     - single-file unique views keep `root_dir/file` layout
     - mixed `reconcile_subset + patch_one` hardened manifests are now supported
     - qB is restarted automatically if validate/patch fails after `qb_stop`
     - reality snapshots classify these rows as `stale_runtime_and_fastresume_root`
   - live Twisters proof:
     - `~/.logs/hashall/reports/rehome-relocate/20260313-112558-9962465e30b69544/`
     - `9/9` verified `exact_tree`
     - `reconcile_rows=8 patch_rows=1`
   - latest planner-expansion hardening:
     - `relocate-plan` now includes already-targeted same-`payload_hash` siblings instead of silently planning only source-root members
   - latest de-hitchhike hardening:
     - multi-hash root-relocation plans now default to per-hash unique target roots
     - `qb-missing-remediate` reconnect plans now do the same
     - stash->pool `rehome` view planning now also routes multi-hash groups into `_rehome-unique/<hash>` targets
     - successful attaches now remove an unused intermediate donor root when the full sibling group is covered in-plan
     - this is about unique per-item trees backed by hardlinks, not forced duplicate byte copies
   - `refresh6` is now the source of truth for the remaining pool-data -> pool-media lane:
     - `out/rehome-plan-pool-data-to-media-refresh6-20260313.json`
     - `out/rehome-plan-pool-data-to-media-refresh6-20260313-drift.json`
     - `plans=31`
     - `rows=189`
     - `attention_rows=167`
     - `plans_with_out_of_plan_siblings=11`
     - `23 ready_repoint_or_reconcile`
     - `5 blocked_qbit_sibling_gap`
     - `3 blocked_target_view_missing`
   - live proof immediately before this hardening:
     - `Cinderella.2021...` succeeded at `~/.logs/hashall/reports/rehome-relocate/20260313-095751-578fffbfe4fc2f8c/`
     - its post snapshot still warned about one shared payload row because that run started before the de-hitchhike planner landed
   - next clean live slice already prepared:
     - `out/rehome-plan-pool-data-to-media-twisters-only-20260313.json`
     - `out/rehome-plan-pool-data-to-media-twisters-only-20260313-drift.json`
     - `MOVE`, `affected_torrents=9`, `out_of_plan_siblings=0`, `unique_view_targets=9`
   - latest preflight feedback hardening:
     - `_preflight_existing_view_conflicts()` now emits progress / view-done / complete heartbeat lines
     - this closes the long silent window between `step=verify_target` and `step=build_views` when an existing target tree is large but healthy
   - latest preflight-view hardening:
     - `rehome` now runs `step=preflight_target_views` before `build_views`
     - conflicting preexisting target-view files are detected read-only and block the whole plan before any sibling hardlinks are created
     - this specifically closes the `Novitiate...` partial-view-build risk
     - live proof:
       - `The.Long.Walk.2025...` `REUSE` completed cleanly at `~/.logs/hashall/reports/rehome-relocate/20260312-214219-38c7f2c20c7af677/`
   - current live migration baseline:
     - `old_path_count=34`
     - `new_path_count=317`
     - active remainder plan:
       - `out/rehome-plan-pool-data-to-media-liveqb-20260313.json`
       - `seed_scope=live_qb_root`
       - `qbit_hashes=34`
       - `mapped_payloads=14`
       - `candidates=14`, `reuse=7`, `move=7`, `covered old-root hashes=34/34`
       - `29` candidates (`22 REUSE`, `7 MOVE`, `2` skipped as already targeted no-ops)
    - qB health:
      - `stalledup=5147`
      - `uploading=5`
      - `stoppeddl=1` (`Alien Romulus`, repair lane only)
      - `stalleddl=2` (outside the pool-data lane under `/data/media/.../radarr`)
    - explicit next proving task to preserve:
      - `Alien Romulus` mixed sibling family
      - current observed scope:
        - `14` sibling candidates
        - `7` `~noHL` siblings
        - one `PD` row (`1376e795...`) already known incomplete
      - use this family next to prove that rehome/repair can lift the `~noHL` siblings to `pool-media`
      - the success condition is unique per-item payload trees backed by hardlinks, not redundant physical copies
   - `qb-zfs-relocate` semver is `0.1.13`
   - latest stale reconnect proof:
     - `Peppermint...` old `/data -> /pool/data` reuse-drift lane is now remediated
     - `qb-missing-remediate` now accepts `root_drift_after_rehome_reuse` rows when the mapped target payload lives under a different catalog `payload_hash`
     - live report dir:
       - `~/.logs/hashall/reports/rehome-relocate/20260312-212329-4f2ac41db39d760f/`
     - `hashall rehome qb-missing-audit --source-root /data/media/torrents/seeding --target-root /pool/data/media/torrents/seeding` now returns `0`
   - `rehome` now has a shared reality snapshot / drift-audit layer:
     - module: `src/rehome/reality.py`
     - CLI: `hashall rehome drift-audit --plan <plan.json>`
     - `rehome apply` artifact dirs now contain `reality-pre.json`, `reality-post.json`, and `reality-failure.json`
     - preflight failures include plain-English guidance from those live snapshots
   - latest follow-up fix after the first `Wakanda` failure:
      - `qb-libtorrent-verify.py` now promotes instant-complete `exact_tree` verifies that never emit `checking_files`
      - `reality.py` now classifies normal source-only `MOVE` rows as `source_only`
      - post-apply reality snapshots now report `post_apply_settling` / `settling_after_apply` for brief healthy target-side qB checking instead of a false blocked state
      - `rehome apply` now accepts sliced batch plan files with only a `plans` list
      - drift snapshots now surface uncovered same-payload siblings before cleanup time
      - successful report dir:
        - `~/.logs/hashall/reports/rehome-relocate/20260312-145812-6bb9bb5432f39cbb/`
   - single-plan live pilots are green on both major paths:
     - `REUSE`: `The.West.Wing.S07...`
     - `MOVE`: `Megalopolis.2024.REPACK...`
   - first curated mixed batch is also green:
     - `Longlegs...` REUSE via `rehome_reconcile_subset`
     - `Brave.New.World.US.S01...` MOVE
     - `Greenland.2020.Repack...` MOVE
4. Preserve and remediate known drift:
   - `payloads`/`torrent_instances` rows with missing or stale `device_id` values.
   - parked negative `device_id` row in `devices`.
5. Identity repair status now:
   - `/pool/media` mapping has been registered in `devices` (`device_id=141`).
   - identity repair dry-run returns zero candidates and zero unresolved.
   - keep refresh step-2 scanning `/pool/media` to prevent recurrence.
6. Active uncommitted WIP is broader than identity repair:
   - implemented and rolled out: `devices.files_table` now owns stable physical binding.
   - compatibility plan remains active: `files_<device_id>` are views, not physical truth.
7. First thing to recover after compact:
   - read `docs/operations/RUN-STATE.md` sections:
     - `Stable Files Table Binding WIP`
     - `Copied-DB Validation`
     - `Live Files-Table Migration Execution`
8. Current posture:
   - live migration is active again.
   - `rehome apply` now uses the hardened `qb-zfs-relocate` transport for guarded relocation attachment.
9. qB relocation-specific current state:
   - direct `qb-zfs-relocate` pilots already proved the guarded backend earlier
   - the old `/pool/data -> /pool/media` stale-root and stoppedDL repair lanes are clear
   - the old `/data == /stash` sibling-root drift lane is now remediated live:
     - `hashall rehome qb-missing-remediate` succeeded for:
       - `Megalopolis...` (`4`)
       - `Cleverman.S02...` (`2`)
     - current qB state after that run:
       - `missingFiles=0`
       - `stoppedUP=6` (intentionally paused remediated hashes)
   - latest refresh returned `OK`
   - `hashall rehome qb-missing-audit ...` now returns `0`
   - current scale-up target is `rehome apply`, not direct `qb-zfs-relocate`
10. New planner continuity to preserve:
   - `hashall rehome relocate-plan` now exists in commit `e572bf8`
   - `hashall` semver is `0.4.164`
   - planner lives in `src/rehome/normalize.py`
   - it can plan explicit root-to-root relocations and synthesize unique target views for shared-root sibling collisions
   - `rehome apply` execution is now wired to the guarded `qb-zfs-relocate` backend
11. New recovery/audit tool:
   - `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding`
   - use it before any mass remediation of qB `missingFiles` items
12. First thing to do after compact if the task continues:
   - do not resume the old `/pool/data` stale-root remediation or stoppedDL repair lanes; they are already clear
   - do not reopen the old `6` `/data == /stash` sibling-root drift lane; it is fixed
   - start from the latest successful mixed-batch artifacts:
     - `REUSE subset`: `~/.logs/hashall/reports/rehome-relocate/20260311-180840-a1041c6049c66abe/`
     - `MOVE`: `~/.logs/hashall/reports/rehome-relocate/20260311-182010-66eebb2df636b12a/`
     - `MOVE`: `~/.logs/hashall/reports/rehome-relocate/20260311-183147-adf55dffe6443f6a/`
   - exclude the bad `Shining.Girls` reuse group from future batches
   - generate the next curated batch from the remaining clean candidates rather than rerunning `mixed4`
13. Later 2026-03-11 continuity beyond `mixed3`:
   - `next4c` is now green:
     - `Brave.New.World.US.S01...`
     - `Greenland.2020.Repack...`
     - `Azrael...`
     - `Stranger.Things.S03...`
   - shared summary ended with:
     - `25 torrent(s) checked, all in acceptable state`
   - two current carve-outs from the clean MOVE lane:
     - `Magic.City.S01...` dirty/preexisting target (`8 files / 106474639951 bytes` source vs `9 files / 110028001871 bytes` target)
     - `Wilding.2023...` offline verify stalled at `checking_files 0.00%` for `15m+`
   - audit conclusion:
     - no broad fastresume-corruption signal was found
     - next code work should target dirty-target rejection, verify-stall detection, and stronger lock diagnostics
14. New 2026-03-12 cleanup continuity:
   - commit `f960483` added staged safe cleanup to `hashall rehome followup --cleanup`
   - commit `2511ce2` added follow-up-side catalog reconcile for healthy rows before cleanup
   - live cleanup succeeded for:
     - one pilot payload (`English.Teacher...`)
     - six additional `/pool/data` payload groups
     - two final retried groups after narrow ownership fixes on their source-side paths
   - post-cleanup qB snapshot:
     - `stalledUP=5147`
     - `uploading=4`
   - remaining follow-up backlog:
     - exactly one failed group remains
     - payload `a1041c6049c66abe...` (`Longlegs...`)
     - reason: one member still points at `/pool/data/...`
15. New 2026-03-12 relocate proof continuity:
   - commit `f3071ff` fixed a real code bug exposed by `Mickey.17...`
   - new current safeguard:
     - follow-up cleanup now blocks if any same-`payload_hash` sibling row still points at a non-target device or old `/data`/`/stash` alias
   - direct source verify proved the payload was good
   - the bug was:
     - false qB recheck completion detection without a real state transition
     - too-narrow retry gating for transient exact-tree `partial_match` verifies in `rehome`-shaped manifests
   - live rerun report dir:
     - `~/.logs/hashall/reports/rehome-relocate/20260312-111522-36390ecee324f1af/`
   - final result:
     - `MOVE` succeeded
     - qB ended `stoppedUP 100%` on `/pool/media/...`

Historical snapshot:
`docs/archive/2026-doc-reduction/snapshot/docs/next-agent.md`
