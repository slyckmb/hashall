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
   - `hashall` semver is `0.4.178`
   - `qb-zfs-relocate` semver is `0.1.13`
   - `rehome` now has a shared reality snapshot / drift-audit layer:
     - module: `src/rehome/reality.py`
     - CLI: `hashall rehome drift-audit --plan <plan.json>`
     - `rehome apply` artifact dirs now contain `reality-pre.json`, `reality-post.json`, and `reality-failure.json`
     - preflight failures include plain-English guidance from those live snapshots
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
