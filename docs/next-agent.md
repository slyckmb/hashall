# Next Agent Entry (Compact-Safe)

## 2026-03-25 Active Findings (compact-safe) — UPDATED

- External report `hashall-bug-9a731a-fastresume-root-corruption-20260325.md` was correct about a
  current bug in the repair path:
  - `src/hashall/qb_repair_payload_group.py` could trust `broken_info.save_path`
  - that bad runtime path could then be written into fastresume
  - example failure mode: `/tmp` becomes persisted `save_path` / `qBt-savePath`
- Current code now:
  - anchors repair target-save-path selection to catalog state instead of the broken torrent's
    live runtime save path
  - logs chosen target save path plus the reason it was selected
  - regression coverage includes the `/tmp` drift case
- Key design finding on `/pool/data` coverage:
  - the scan itself is not the missing piece
  - `scan /pool/data` populates `files_*`
  - `payload sync` then materializes `payloads` only for qB torrent roots
  - that matches the current definition of payloads as "the on-disk content tree a torrent points
    to"
  - it does **not** match the broader operator intent of indexing as much content as possible
- Recommended remedy for that gap:
  - keep `payloads` qB/torrent-root scoped
  - add a separate durable non-qB content inventory layer for managed scan roots such as
    `/pool/data/orphaned_data`
  - if that broader inventory is not desired, update requirements/docs explicitly so operators do
    not assume whole-tree coverage
- Current pool headroom reality has tightened again:
  - `/pool/data`: `27G` free
  - `/pool/media`: `27G` free
  - largest reclaim/policy targets currently visible:
    - `/pool/data/orphaned_data`: `2.3T`
    - `/pool/data/seeds`: `1.2T`
    - `/pool/data/cross-seed-link`: `413G`
- Recommended reclaim order:
  1. decide orphan-donor policy first
  2. audit `/pool/data/seeds`, especially `_qbm_recycle`, `RecycleBin`, `_qb-unique-repair`
  3. only then consider broader cleanup under `cross-seed-link` / `cross-seed`

## 2026-03-21 Rehome Fastresume Rollback Fix (compact-safe) — UPDATED

- `hashall` is now `0.8.9`
- The `0.8.8` pilot exposed one more real failure path:
  - a hardened fastresume apply could fail after patching
  - payload/file rollback would run
  - but fastresume metadata was not restored from backups
  - qB could then stay pointed at `/pool/media` even though rollback removed the target files
- Current code now:
  - restores fastresume backups on post-patch hardened-fastresume failure
  - restarts qB after that restore so runtime metadata returns to the pre-run source paths
- Fresh validation on 2026-03-21:
  - focused rollback regressions: passed
  - this is the fix needed before another real `West Wing` pilot

## 2026-03-21 Rehome qB Runtime Settle Fix (compact-safe) — UPDATED

- `hashall` is now `0.8.8`
- `West Wing` already proved the data path was good through copy, verify, view build, and sibling
  relocate; the remaining failure was the post-patch qB runtime handoff.
- Root cause was qB restart jitter plus cache-fallback API reads:
  - `.fastresume` files were patched correctly to `/pool/media`
  - but executor checked runtime `save_path` too early
  - and cache-fallback qB API reads could still report stale `/pool/data` runtime info
- Current code now:
  - waits for qB restart/authentication before post-patch verification
  - requires live qB runtime info for `save_path` checks instead of trusting cache fallback
  - retries stale post-patch `save_path` with an explicit `set_location` nudge when needed
  - waits for post-patch qB accounting to settle, but still fails fast for definite bad states
- Fresh validation on 2026-03-21:
  - rehome regression pack: `81 passed`
  - live dry-run of `out/rehome-plan-west-wing-s02-2026-03-21-v087.json` is clean

## 2026-03-21 Rehome Content-Proofed Reuse (compact-safe) — UPDATED

- `hashall` is now `0.8.7`
- Rehome target-family reuse no longer trusts only file counts / total bytes.
- Planner + executor now compute a real payload hash from the live files before calling a target
  family reusable; same-size same-byte roots with different bytes are treated as conflicts.
- This directly explains the `Shining.Girls...` lane:
  - `/pool/media` `TorrentDay` and `Aither` sibling roots match by counts/bytes
  - but they diverge by actual content
  - the lane should be treated as a real repair conflict, not a reusable family
- Current code now:
  - content-proofs target reuse from live filesystem bytes
  - blocks apply before any work when the target family is internally divergent
  - still allows stale-source reuse fallback when the source root is already gone
- Fresh validation on 2026-03-21:
  - targeted sim suite: `78 passed`
  - `West Wing` dry-run remains clean `MOVE`
  - `Shining Girls` live plan generation now hashes real files and is expected to be slower
    because it is proving content, not assuming it

## 2026-03-20 Rehome West-Wing Fixes (compact-safe) — UPDATED

- `hashall` is now `0.8.6`
- Root cause of the failed `West Wing S02` rehome was confirmed and fixed in code:
  - planner previously chose `MOVE` from one canonical target path and ignored existing sibling
    views on `/pool/media`
  - target-view preflight was mutating existing target files instead of only inspecting them
  - rollback deleted a pre-existing good target-side sibling view because it did not track whether
    that view existed before the run
- Current code now:
  - prefers family-level target reuse when an exact target-side sibling view already exists
  - blocks `MOVE` before rsync when alternate sibling target views already exist but conflict
  - keeps target-view preflight read-only
  - rolls back only view paths created by the current run
  - writes extra `failure-pre-rollback` / `failure-post-rollback` reality snapshots during move failures
- Fresh live dry-run on 2026-03-20 for `/pool/data/media/torrents/seeding`:
  - `Shining.Girls...` = `REUSE`
  - `The.West.Wing.S02...` = `MOVE`
  - `Alien Romulus` = `MOVE`
- Important current reality:
  - the previously good `/pool/media` `West Wing` donor/sibling view is already gone from the
    earlier buggy run
  - because of that, the fresh `West Wing` plan now correctly shows `target_family_exact_views=0`
    and no longer tries to reuse a donor that is not actually present
- Historical note: `Shining.Girls...` was the next recommended reuse pilot before content-proofed
  target-family checks exposed the target-side divergence.

## 2026-03-19 Migration State (compact-safe) — UPDATED

- `hashall` is now `0.8.5`
- **41** pool-data torrents remain (all `stalledUP`); **344** on pool-media; state: `in_progress`
- Live split of those `41` rows on 2026-03-19:
  - `8` under `/pool/data/media/torrents/seeding`
  - `28` under `/pool/data/cross-seed-link`
  - `5` under `/pool/data/cross-seed`
- **Blockers CLEARED:**
  - `~/.hashall/rehome.lock` removed (pid confirmed dead)
  - `consecutive_failures=640` was a stale counter artifact — fixed in code; qB API healthy
- **Next step:** `hashall refresh --verbose` → generate fresh relocate-plan → execute in batches
- Important: `bin/migrate-pool-data-to-media.sh` is **not** the full 41-row resume path as currently wired.
  - Its dry-run on 2026-03-19 only selected the `8` rows under the exact
    `/pool/data/media/torrents/seeding` source root.
  - It also included `Alien Romulus`, which remains a special-case repair/proving lane item.
- Current known special cases:
  - `Alien Romulus` (`1376e795...`) is **still active as a special case**, not resolved for plain batching
  - `Shining.Girls...` is **still a bad reuse candidate** and should stay excluded from plain batches
- Phase 0→1 commands: `docs/operations/RUN-STATE.md` "2026-03-19 Migration Analysis" section
- Bug fixes this sub-session: `qb_cache.py` counter reset, `qb-checking-watch.sh` help text,
  stoppeddl bucket path, `migrate_common.sh` comment, version bump
- Full context: `docs/handoff.md` "2026-03-19 Migration Audit + Bug Fixes" section

---

## 2026-03-18/19 Audit Session Summary (compact-safe)

- `hashall` was `0.8.4` after the audit session (now `0.8.5` after the 2026-03-19 bug-fix sub-session).
- Branch `cr/claude-hashall-20260318-232039` has two commits beyond the session baseline:
  - `3fd06c0`: HIGH + MEDIUM bugs (followup GOOD_STATES, scan drift_policy, planner bind-mount)
  - `b88343f`: LOW bugs (unique-view shortcut, qb_cache daemon URL env var)
- Full details in `docs/handoff.md` top section ("2026-03-18/19 Audit Session").
- Test baseline: 636 pass / 13 pre-existing failures (see handoff.md for breakdown).
- `docs/REQUIREMENTS.md` is now v1.1 — the canonical requirements reference for all rehome work.
- No operational migration work was done in this session; live migration state is unchanged
  from the 2026-03-13/15 baselines documented below.

---

- `hashall` is now `0.8.4`.
- qB cache compatibility is now partially internalized:
  - use `bin/qb-cache-agent.py --status` to inspect the local cache
  - local cache path is `~/.cache/hashall-qb/`
  - qB profile detection and state alias normalization now live in `src/hashall/qbittorrent.py`
  - read-heavy hashall qB scripts should prefer the local cache by default
- Remaining follow-up:
- silo’s external dashboard/cache path was not modified from this worktree
  - historical note: earlier docs may still call this external repo `qbitui`
  - if you need the same cache/profile behavior there, that is a separate cross-repo task

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

## 2026-03-24 Current TODO Split

- Must do:
  - let the current tmux `%61` refresh finish; do not start another refresh concurrently
  - generate a fresh `/pool/data -> /pool/media/torrents/seeding` relocate plan after that refresh completes
  - keep `Alien Romulus` and `Shining.Girls...` out of plain migration batches
  - re-check the `West Wing` lane on current code before treating it as a normal migration slice
  - investigate why `hashall refresh` scanned `/pool/data` but the catalog still does not cover the whole `/pool/data` tree
    - confirmed current catalog counts: `0` rows under `/pool/data/orphaned_data`, `17` under `/pool/data/cross-seed-link`, `23` under `/pool/data/cross-seed`, `87` total under `/pool/data`
    - this conflicts with the operator expectation that the whole `/pool/data` tree would be represented after `scan /pool/data`
    - important current finding: `scan /pool/data` populates per-device `files_*` tables, but `payloads` are materialized later by `build_payload()`
    - in the refresh flow, those `build_payload()` calls come from `payload sync`, which iterates qB torrents, so non-qB trees like `/pool/data/orphaned_data` may never become payload rows
    - determine whether that is the intended model or a real gap in coverage/documentation
  - evaluate requirements and design gaps around non-qB tree scans, and propose a remedy
    - operator intent is to hash as much content as possible, not only qB-backed roots
    - goal is to let `cross-seed`, `jdupes`, and `hashall` reason over the same broader content surface and manage seed data correctly
    - specifically assess whether non-qB trees under managed scan roots should also materialize into `payloads`, or whether a second content-index layer is needed
    - produce a concrete recommendation covering schema, refresh behavior, pruning, and operator expectations
    - treat this as a likely product gap unless the requirements explicitly say non-qB trees are out of scope
    - compare the intended model against actual behavior for:
      - managed scan roots such as `/pool/data`
      - non-qB subtrees such as `/pool/data/orphaned_data`
      - downstream consumers: `cross-seed`, `jdupes`, `hashall` planning, and future space-reclaim analysis
    - remedy proposal must say which layer owns broad content coverage:
      - expand `payload` materialization beyond qB roots
      - or add a separate durable content-index / inventory layer for non-qB trees
    - document any resulting requirement change explicitly if the current qB-centric design is intentional
  - develop a concrete plan to increase headroom on `pool`
    - current state after pilot + batch 2: `/pool/data` ≈ `99G` free, `/pool/media` ≈ `99G` free
    - current relocation batches are not increasing reported free space enough to justify continuing blindly
    - produce ranked reclaim options with estimated GiB impact and operational risk
  - review the external fastresume corruption report, investigate, and report findings
    - report path: `/mnt/config/docker/.agent/worktrees/cr-docker-20260323-114236-codex/docs/hashall-bug-9a731a-fastresume-root-corruption-20260325.md`
    - determine whether it describes:
      - a current `hashall` bug already present in this branch
      - a stale behavior already fixed here
      - or a new cross-repo / deployment-specific integration issue
    - produce a concrete finding with impact, affected code path, and required remediation if any
- Proposals:
  - improve refresh lock-holder diagnostics further if `refresh-status` still leaves operator ambiguity
  - do any future cross-repo qB helper alignment against `silo`, not the old `qbitui` identity
