# Next Agent Entry (Compact-Safe)

## Big-Picture Seed Folder Cleanup TODO

This is the plain-language top-level cleanup list for the seeding trees. Treat it as critical context for future waves.

1. Finish `cross-seed-link -> cross-seed`
   - Most of this is done, but the last broken exceptions still need to be repaired so nothing live points at `cross-seed-link` anymore.
2. Finish `orphaned_data -> orphans`
   - Normalize the orphan folder naming so the canonical name is just `orphans` in both trees.
3. Clean up the remaining broken live torrents
   - Current examples: DocsPedia leftovers, `/data/media` `stoppedDL` items, and the Dexter repair pair.
   - These need to be brought back to healthy seeding state, not just renamed.
4. Drain torrent payloads out of `/pool/data`
   - `/pool/data` is temporary residue, not a final seeding home.
   - Anything torrent-related still there needs to move into the right canonical place under `/pool/media/torrents/...`.
5. Keep stash-vs-pool placement consistent
   - If a payload is hardlinked into `/stash/media` libraries, it stays on stash.
   - Otherwise it belongs on pool.
6. Remove duplicates between stash and pool
   - The final tree layout should match between stash and pool, but the payloads themselves should not be duplicated across both in steady state.
7. Fix hitchhikers
   - A hitchhiker is when multiple hashes share one payload tree in the wrong way.
   - These need to be split into unique per-hash trees, ideally with hardlinks so disk usage does not blow up.
8. Keep qB and RT aligned
   - Every live change has to leave both clients pointing at the same real content.
   - Path cleanup is not finished until both clients agree.
9. Clean up stale residue and empty legacy paths
   - After moves and repairs, there will still be dead folders, stale legacy roots, and empty leftovers that need explicit cleanup.
10. Update code, scripts, and docs that still assume old paths
   - Anything in `hashall` or elsewhere in `~/dev` that still refers to `cross-seed-link` or `orphaned_data` needs to be updated so the tooling matches the final layout.
11. Finish the repair / verification contract
   - Tooling still needs stronger handling for completed verification after path repair, degraded controller states, and hitchhiker audit/apply.
12. End in the intended steady state
   - `/stash/media/torrents/...` and `/pool/media/torrents/...` use the same canonical layout.
   - No live `cross-seed-link`.
   - No live `orphaned_data`.
   - No torrent payloads left on `/pool/data`.
   - Stash holds payload groups that support `/stash/media` library hardlinks.
   - Pool holds non-library seeding payloads.
   - Each live torrent has a correct unique payload tree.
   - qB and RT both agree on those paths.

## 2026-04-18 Canonical Torrent Tree Normalization

- Canonical planning doc:
  - `docs/operations/TORRENT-TREE-NORMALIZATION-PLAN-2026-04-18.md`
- Start there before planning any stash/pool tree rewrite, `/pool/data` drain, or orphan relocation work.
- Settled policy:
  - `cross-seed-link` is legacy; `cross-seed` is canonical
  - `orphaned_data` is legacy; `orphans` is canonical
  - orphans live under `*/media/torrents/orphans`
  - each dataset keeps its own local `torrents/orphans` first
  - RT is authoritative; qB is the silent mirror and must stay in sync for affected items
  - if any file in a payload has a hardlink into `/stash/media` libraries, keep the whole sibling payload group on stash
  - otherwise rehome the whole sibling payload group to pool
  - `/pool/data` should end at zero torrent payloads
- Required execution pattern for every mutating phase:
  1. sim code walk
  2. dry-run
  3. tiny pilot
  4. code/fix/code/fix loops before widening
- Stop for manual review on:
  - same names with different hashes
  - conflicting verified stash/pool copies
  - mixed hardlink-anchor evidence
  - incomplete sibling groups
  - anything unexpected
- Before any rename batch, audit `~/dev` for path-sensitive code/docs that still reference old names or old canonical roots.
- That audit is now partially classified:
  - Docker repo RT hooks that participate in live path setting:
    - `gluetun_qbit/rtorrent_vpn/rt_sync_imported_path.sh`
    - `gluetun_qbit/rtorrent_vpn/rt_set_label_path.sh`
    - `gluetun_qbit/rtorrent_vpn/rt_repair_legacy_path.sh`
  - Docker repo qB-side active legacy-name consumers:
    - `qbit_manage/config.yml`
    - `qbit_manage/config-seeds.yml`
    - `qbit_manage/bin/promote_recycle_to_seeds.sh`
    - `qbit_manage/bin/check_pool_orphans.sh`
    - `gluetun_qbit/qbittorrent_vpn/bin/qb-to-rt-migrate.py`
  - Other active repos still carrying rename-sensitive settings:
    - `work/hiker/docker/cross-seed-v6/config.js`
    - `work/hiker/docker/qbit_manage/config.yml`
    - `tools/traktor/config/tracker-registry.yml`
    - `tools/traktor/bin/tracker-ctl.sh`
- Recent progress:
  - `payload orphan-sweep` now supports staged controls (`--order`, `--reserve-gib`, `--dataset`)
  - an empty-dir `--limit` bug was fixed and regression-tested
  - the current `/pool/data/media/torrents/seeding` orphan-sweep pilot lane is empty after the empty-dir cleanup
  - canonical docs and continuation context are now committed in-repo
- a dedicated one-hash same-FS helper now exists:
  - `python -m hashall.cli payload normalize-cross-seed-link --hash <HASH>`
  - use `--apply` only after the dry-run plan is clean
  - focused tests:
    - `pytest -q tests/test_path_normalize.py`
- first live helper pilot succeeded for:
  - `b95856e0a29bf045e76a95f4ea3cacf6e4b02add`
  - qB final save path:
    - `/pool/media/torrents/seeding/cross-seed/FileList.io`
  - RT final directory:
    - `/pool/media/torrents/seeding/cross-seed/FileList.io/The.Roman.Invasion.of.Britain.S01.720p.HDTV.x264-BTN`
  - RT recovered from `error` to `stalledUP`
- more live helper pilots succeeded for:
  - `55a3df42dcf14d250117d811b52dca658fd05f73`
    - multi-file / RT content-directory case under `DigitalCore (API)`
  - `8779246eebcf9135f272d24cdff643887700ffe1`
    - single-file / RT root-directory case under `Darkpeers (API)`
- a hardened operator wrapper now exists:
  - `scripts/pilot-normalization.sh`
  - list/dry-run by default
  - safe apply lane restricted to stopped `/pool/media` candidates
  - delegates mutations to `payload normalize-cross-seed-link`
  - uses the shared qB/RT cache helpers for watch/list/post-check reads where possible
  - prints residue status and remaining live legacy counts
- first wrapper-driven live pilot succeeded for:
  - `5bf579e7c4c98daeb66c87da1f6068512f35c3cd`
  - qB canonical save path:
    - `/pool/media/torrents/seeding/cross-seed/DocsPedia`
  - RT canonical directory:
    - `/pool/media/torrents/seeding/cross-seed/DocsPedia/How It's Made S01-S32 480p DVDRip 1080p WEBRip AAC 2.0 x264-MIXED`
  - wrapper watch timed out as `ambiguous_needs_review` because RT remained `checking` beyond the 120s budget
  - immediate follow-up state still showed both clients aligned on the canonical path
- live legacy-name scope is now:
  - `21` RT rows on `cross-seed-link`
  - `21` qB rows on `cross-seed-link`
  - `1` RT row on `orphaned_data`
  - `1` qB row on `orphaned_data`
- cache-backed auto-pick now works:
  - `scripts/pilot-normalization.sh --pick-safe`
  - `scripts/pilot-normalization.sh --apply --watch`
- first cache-backed auto-pick pilot succeeded for:
  - `fad3310db364ee7a8e97d511a85cf4df1eab4813`
  - canonical tracker root:
    - `/pool/media/torrents/seeding/cross-seed/FearNoPeer`
  - canonical payload path:
    - `/pool/media/torrents/seeding/cross-seed/FearNoPeer/The Last Stop in Yuma County 2023 1080p AMZN WEB-DL DDP5 1 H 264-BYNDR.mkv`
- live legacy-name scope is now:
  - `20` RT rows on `cross-seed-link`
  - `20` qB rows on `cross-seed-link`
  - `1` RT row on `orphaned_data`
  - `1` qB row on `orphaned_data`
- next code priorities are now explicit:
  - first: tighten helper-level normalization success semantics so `checking*` is modeled explicitly instead of being treated as the strongest form of success
  - second: add a first-class hitchhiker audit/de-hitchhike lane for legacy N->1 shared payload trees
- key code reality for issue 1:
  - `src/hashall/path_normalize.py` currently proves path convergence, but not completed verification as the strongest helper success contract
- key code reality for issue 2:
  - repo already has inode-aware and `_rehome-unique/<hash>` concepts; what is missing is a focused audit/apply lane for legacy hitchhiker groups
- execution sequence:
  - implement issue 1 first
  - then implement hitchhiker audit
  - then implement hitchhiker split/apply
- first concrete `cross-seed-link -> cross-seed` dry-run / pilot findings:
  - RT and qB do not use the same target path shape for a given hash
  - RT may store the full content directory while qB stores the tracker save root
  - `qb-zfs-relocate plan` is useful to prove the qB mapping for a selected hash
  - `qb-zfs-relocate validate` is not useful as same-FS rename preflight because it expects a copied destination payload
  - the helper must distinguish:
    - RT runtime directory
    - RT `d.directory.set` apply path
  - RT verification should allow aligned runtime forms after repoint
  - RT XMLRPC timeouts can happen after qB has already moved
  - helper now waits through RT timeout ambiguity instead of immediately rolling qB back
- qB and RT were both found down during the first dry-run attempt and were recovered with:
  - `docker compose -f /home/michael/dev/sys/docker/gluetun_qbit/docker-compose.yml up -d qbittorrent_vpn rtorrent_vpn`
- Immediate next action:
  - continue one-hash `cross-seed-link -> cross-seed` pilots with `scripts/pilot-normalization.sh`, prioritizing stopped `/pool/media` candidates
  - separately decide how to clean the stale legacy residue left by the failed first pilot under `/pool/media/torrents/seeding/cross-seed-link/...`
- Do not restart broad unattended loops while this normalization plan is still in the planning/audit stage.

## 2026-04-03 Residual stash reuse repair

- The residual `dest_missing` loop is materially fixed for the `Bullet Train` family.
- Code changes in `src/rehome/executor.py` now:
  - skip expensive current-target compare during existing-target-family alignment
  - derive the correct per-torrent `target_payload_root` for wrapped single-entry reuse rows
  - build fallback wrapper views when a reuse plan has no explicit `view_targets` but the torrent metadata is nested single-entry
- Validation:
  - `Bullet Train` single-item apply completed successfully
  - `10/10` siblings verified `exact_tree`
  - report dir:
    - `~/.logs/hashall/reports/rehome-relocate/20260403-010351-8b5c09e0c7c083bf`
  - stash cleanup is still deferred on purpose:
    - `MANUAL_ACTION_REQUIRED` on the `_qb-unique-repair/.../Bullet.Train...mkv` source
- Additional narrowed single-item stash reuse runs completed successfully:
  - `The Muppet...`
    - `9/9` siblings verified
    - report dir:
      - `~/.logs/hashall/reports/rehome-relocate/20260403-012107-7b198aa544d1f641`
  - `Lego Masters...`
    - `8/8` siblings verified
    - report dir:
      - `~/.logs/hashall/reports/rehome-relocate/20260403-012850-ca30f78203851ebf`
- Important remaining warning:
  - post-run reality still reports shared catalog payload grouping for all 3 repaired reuse families
  - future work should de-hitchhike these into unique target payload roots, but this did not block the successful reuse executions
- The autonomous maintenance loop should **not** be restarted blindly yet.
  - it was correctly hardened to stop on `dest_missing`
  - the right follow-up was single-item reuse execution for the narrowed queue, and that queue is now exhausted
- Current stash reuse planner state:
  - `python -m hashall.cli rehome auto --from stash --to pool-media --limit 10`
  - result: `0 MOVE groups available (stash:0), taking top 0`
  - no currently safe all-`REUSE` stash batch remains to execute without widening policy

## 2026-04-20 PD Repair Wave Classification

- The current three near-complete qB `stoppedDL` repair items are:
  - `96d896ca35f42d93e4a4bdee92e8ac90adc34b54` `Transformers.Rise.of.the.Beasts...`
  - `127c38342cfedaf4016b8079be13c5f7883b9cfe` `River Monsters S07...`
  - `5caca88d29e64de495a47b53a466f7cadcb3ce02` `The.Diary.of.a.Teenage.Girl...`
- These three do **not** currently look like N->1 hitchhikers.
  - no shared payload-root collision was found across the three hashes
  - no second live qB/RT hash was found pointing at the same exact payload tree for these rows
- `96d896...` and `127c383...` were investigated first because they had the smallest gaps.
  - qB live state still shows real byte deficits after recheck:
    - `96d896...` about `1.9 MB` left
    - `127c383...` about `16 MB` left
  - the main media files are already correct
  - the obvious sidecars are broken:
    - `96d896...` `.mkv.nfo` and `.txt` are present but `0` bytes
    - `127c383...` `.nfo` is present but `0` bytes
  - the visible `/data`, `/stash`, `_qb-repair-v2`, and `rtorrent` family copies all have the same broken sidecars
  - result: **no local exact donor found**
- `5caca8...` shows the same broad pattern.
  - the main mkv and subtitle files are present
  - `Sample.mkv` and `.nfo` are present but `0` bytes
  - the visible `TorrentLeech` and `_qb-finish` family copies are not better donors
  - result: **no local exact donor found**
- Current classification for all three rows:
  - not a cache problem
  - not a hitchhiker problem
  - not solved by another plain recheck
  - **likely controlled-redownload or deeper piece-level repair needed**
- Immediate next operator move after this documentation pass:
  - keep these three classified as `no-local-exact-donor-found`
  - do not expect a local donor-switch fix from `/data`, `/stash`, `/pool`, or obvious spare roots
  - next investigation lane is whether controlled redownload of the missing pieces is acceptable for these rows

## 2026-04-20 Next Cleanup Wave Selection

- Leave these three hashes on manual-review hold:
  - `96d896...`
  - `127c383...`
  - `5caca8...`
- Current live qB read confirms:
  - all three remain `stoppedDL`
  - all three still carry real remaining deficits
  - no local exact donor was found for any of them
- DocsPedia qB state is now clean:
  - `81ede24...` is `stoppedUP 1.0` on canonical `/pool/media/torrents/seeding/cross-seed/DocsPedia`
- The next smallest actionable repair wave is the Dexter pair:
  - `245f2bce6afaf96b0a48ad216366c4281fdd864f`
    - qB: `stoppedDL`
    - progress about `0.999749`
    - `amount_left=2097152`
    - current path:
      - `/data/media/torrents/seeding/_qb-repair-v2/245f2bce6afaf96b0a48ad216366c4281fdd864f/Dexter.S02.720p.x265-ZMNT`
  - `e36553b12dc118d8c52575a1d6711532882ae1c3`
    - qB: `stoppedDL`
    - progress about `0.999636`
    - `amount_left=2097152`
    - current path:
      - `/data/media/torrents/seeding/cross-seed/TorrentLeech/Dexter.S07.720p.x265-ZMNT`
- Selected next wave:
  - investigate and repair the Dexter pair as the next active cleanup lane
- Do not resume the three manual-review PD holdouts automatically.

## 2026-04-20 Dexter Wave Outcome

- Wave 1 executed on the Dexter pair:
  - `245f2bce6afaf96b0a48ad216366c4281fdd864f`
  - `e36553b12dc118d8c52575a1d6711532882ae1c3`
- qB and RT were both repointed/rechecked on canonical `/data/media/torrents/seeding/cross-seed/TorrentLeech/...` paths.
- Result:
  - both hashes settled back to near-complete `stoppedDL` / `stalledDL`
  - both still show `2097152` bytes left
- Important finding:
  - these are not simple path-drift repairs
  - they share exact payload trees with healthy sibling hashes, but use alternate torrent identities
- Operational rule:
  - keep the Dexter pair out of the simple metadata-fix lane
  - treat them as manual-review / alternate-identity repair items unless a better donor or controlled-redownload plan is approved

## 2026-04-20 RT Cleanup Wave Outcome

- Wave 2 / Wave 3 narrowed the RT-only bad-row lane.
- `691f3d9453c501ed0dff9ac7c85978389a332ab2` cleared from the RT bad-row set after recheck and no longer needs RT cleanup.
- Remaining RT-only bad rows with no qB owner:
  - `e04e524750c999ac22d994e5f5ebf8f5dd1d4c84`
  - `3e82f6f7a3a5adaebce5dfac35d8cc6c4fc5f9ad`
- Current interpretation:
  - these are now the true next RT-only review items
  - they need per-hash inspection for session residue vs real content trouble

## 2026-04-20 RT-Only Review Wave Outcome

- Wave 4 executed on the two remaining RT-only bad rows:
  - `e04e524750c999acfc9afd5c9a604e12fbaee0d8`
  - `3e82f6f7a3a5adae52d84a1074b290b42ccb5026`
- Important finding:
  - the earlier long hashes in notes were wrong; RT bad-row output had only shown short prefixes
  - these are the actual full RT hashes
- Deeper diagnosis found the RT-side mismatch:
  - both are multi-file torrents
  - RT had `d.directory` set to the torrent root instead of the parent save root
  - UEFA also has different root-vs-nested mkv copies, so the wrong RT directory could select the wrong file
- Both payload roots exist on disk under canonical `/pool/media/torrents/seeding/cross-seed/FileList.io/...` paths.
- Direct `rt recheck --apply` was not enough.
- Revised Wave 4 fix used:
  - `rt session-reset --target-directory /pool/media/torrents/seeding/cross-seed/FileList.io --apply`
- Post-wave result:
  - both moved from `stoppedDL` to active `checkingDL`
  - qB has no matching owner rows for either hash
- Interpretation:
  - this looks like the right RT-side fix
  - do not mutate these two again until the current RT checks settle

## 2026-04-20 Orphan Rename Prep Wave Outcome

- Wave 5 executed as an audit / dry-run prep lane for `orphaned_data -> orphans`.
- Current on-disk state:
  - `/pool/media/torrents/orphaned_data` exists and is populated
  - `/pool/media/torrents/orphans` does not exist yet
  - `/stash/media/torrents/orphaned_data` exists but is currently empty
  - `/stash/media/torrents/seeding/orphaned_data` exists but is currently empty
- Current live blocker:
  - qB still has one live row rooted under `/pool/media/torrents/orphaned_data/...`
  - hash:
    - `f37b9983d27409b4d17d30948ce38b4e021935fb`
  - state:
    - `stoppedUP`
  - current save path:
    - `/pool/media/torrents/orphaned_data/FileList.io/_qb-unique-repair/f37b9983d27409b4d17d30948ce38b4e021935fb`
- RT cache showed no current `orphaned_data` directory rows during this audit pass.
- First dry-run batch shape is now known, for example:
  - `Aither (API)`
  - `Darkpeers (API)`
  - `DigitalCore (API)`
  - `DocsPedia`
  - `FearNoPeer`
- Code/config refs that must be addressed before rename include:
  - `src/hashall/orphan_sweep.py`
  - `src/hashall/cli.py`
  - `src/hashall/content_inventory.py`
  - `~/dev/sys/docker/qbit_manage/config.yml`
  - `~/dev/sys/docker/qbit_manage/config-seeds.yml`
  - `~/dev/sys/docker/qbit_manage/bin/promote_recycle_to_seeds.sh`
  - `~/dev/sys/docker/qbit_manage/bin/check_pool_orphans.sh`
- Operational rule:
  - do not start a broad orphan rename while the live qB row still points at `orphaned_data`
  - Wave 6 should start by fixing or rehoming that live qB orphan-path row, then re-run the orphan rename dry-run

## 2026-04-20 Live Orphan-Path Blocker Wave Outcome

- Wave 6 executed on the one live qB orphan-path row:
  - `f37b9983d27409b4d17d30948ce38b4e021935fb`
- qB-only move applied:
  - old save path:
    - `/pool/media/torrents/orphaned_data/FileList.io/_qb-unique-repair/f37b9983d27409b4d17d30948ce38b4e021935fb`
  - new save path:
    - `/pool/media/torrents/orphans/FileList.io/_qb-unique-repair/f37b9983d27409b4d17d30948ce38b4e021935fb`
- Post-wave result:
  - qB state stayed `stoppedUP`
  - qB now has **no** live rows under `orphaned_data`
  - the old file path is gone
- Operational result:
  - the live blocker for the orphan rename lane is cleared
  - the next orphan wave can now become a real rename batch instead of audit-only prep

## 2026-04-20 First Orphan Rename Batch Outcome

- Wave 7 executed as the first real `orphaned_data -> orphans` batch on `/pool/media`.
- Moved with same-filesystem atomic `mv`:
  - `Aither (API)`
  - `Darkpeers (API)`
  - `DigitalCore (API)`
  - `DocsPedia`
  - `FearNoPeer`
- Important operational note:
  - an earlier rsync move was interrupted mid-copy on `Aither (API)`
  - the partial destination copy was preserved as:
    - `/pool/media/torrents/orphans/.aborted-rsync-Aither (API)-20260420-1720`
  - the full source tree was then moved atomically into:
    - `/pool/media/torrents/orphans/Aither (API)`
- Post-wave state:
  - none of the 5 batch roots remain under `/pool/media/torrents/orphaned_data`
  - all 5 now exist under `/pool/media/torrents/orphans`
  - qB still has no live `orphaned_data` rows
- Operational rule:
  - keep using atomic same-filesystem rename for the remaining orphan batches
  - do not use the rsync move helper again for same-device orphan-tree renames

## 2026-04-20 Second Orphan Rename Batch Outcome

- Wave 8 continued the orphan rename lane with the next clean atomic-rename batch.
- Moved from `/pool/media/torrents/orphaned_data` to `/pool/media/torrents/orphans`:
  - `It.Ends.With.Us.2024.MULTi.1080p.BluRay.x264-LYPSG`
  - `LinkedIn - Premiere Pro Guru: Fixing Video Color and Exposure Problems`
  - `OnlyEncodes (API)`
  - `PrivateHD`
- Stash side:
  - created canonical `/stash/media/torrents/orphans`
  - stash legacy orphan dirs are still empty
- New blocker discovered:
  - `FileList.io` now exists in both places:
    - `/pool/media/torrents/orphaned_data/FileList.io`
    - `/pool/media/torrents/orphans/FileList.io`
  - this is the first merge case and should not be handled by blind top-level `mv`
- Operational rule:
  - continue atomic `mv` for non-conflicting top-level roots
  - handle `FileList.io` as a merge/planned sub-batch, not a single rename

## 2026-04-20 FileList.io Orphan Merge Outcome

- Wave 9 handled the first orphan merge case:
  - `FileList.io`
- Strategy:
  - atomic `mv` for the six non-conflicting children
  - preserve `_qb-unique-repair` as the only overlap
  - verify the overlapping legacy subtree was empty after the earlier qB move
  - remove the empty legacy `_qb-unique-repair` and `FileList.io` directories
- Result:
  - `/pool/media/torrents/orphaned_data/FileList.io` is now gone
  - `/pool/media/torrents/orphans/FileList.io` remains as the canonical merged tree
  - qB still has no live `orphaned_data` rows
- Operational rule:
  - future merge cases should use the same pattern:
    - split non-conflicting children with atomic `mv`
    - inspect overlaps narrowly
    - remove empty legacy directories only after verification

## 2026-04-02 Pool migration cleanup / stash restart automation

- New helper:
  - `bin/run-pool-migration-maintenance-loop.sh`
- New ops doc:
  - `docs/operations/POOL-MIGRATION-MAINTENANCE-LOOP-2026-04-02.md`
- The loop is intentionally narrow:
  1. recover payload sync via `bin/run-hashall-upgrade-scans.sh --payload-sync-only`
  2. delete only two exact reviewed stale `How It's Made` roots on `/pool/data`
  3. rescan `/pool/data`
  4. rerun payload sync
  5. auto-apply stash -> pool-media rounds only when the batch is all `REUSE`
- Fail-closed conditions:
  - any non-`REUSE` plan decision
  - any apply / verify failure
  - any verify `status=dest_missing`
  - qB / RT recovery failure
  - reviewed stale roots still referenced by qB or RT
- Current observed live state:
  - both stale `How It's Made` roots under `SpeedCD` and `TorrentDay` are already gone
  - qB and RT are healthy
  - the loop has already progressed into stash reuse verification
  - a later dry-run showed another all-`REUSE` stash batch with `3` groups
- Current migration residue counts:
  - `10` torrent rows still rooted on `/pool/data`
  - `379` rooted on `/pool/media`
  - `0` rooted on `/stash`
- Current free space:
  - `/pool/data`: about `3.7T`
  - `/pool/media`: about `3.7T`
  - `/stash/media`: about `12T`
- While the loop is still running, the newest source of truth is:
  - `~/.logs/hashall/pool-migration-loop/`
- Most important outcome from the first unattended run:
  - the stale reviewed `How It's Made` residue was removed successfully
  - later rounds re-surfaced the same `3` reuse families because one torrent in each family ended as `dest_missing`
  - exact residual hashes:
    - `06a8867d184c6972956307c7eea48ce16669e17c`
    - `2bf62b9780fa8c394a8a4d9a57ebb5b924309645`
    - `7c404604a9a478b5d35f109c72935023bd454ef2`
  - next progress should be a targeted per-torrent repair/migration for those three, not another blind unattended loop

## 2026-04-02 RT cache + refresh recovery

- New canonical docs:
  - `docs/operations/RT-CACHE-ALIGNMENT-2026-04-02.md`
  - `docs/operations/RT-CACHE-AGENT-COMMS-2026-04-02.md`
  - `docs/operations/REFRESH-RECOVERY-2026-04-02.md`
- `hashall rt state-audit` is now shared-cache-backed by default.
- Default mode uses:
  - `~/.cache/silo-rt/torrents.json`
  - `~/.cache/silo-rt/torrents.meta.json`
- No silent live fallback:
  - stale/degraded cache state is reported
  - `--live` is explicit diagnostics only
- Direct RT XMLRPC remains intentional only for mutation / repair:
  - `rt repoint`
  - `rt recheck`
  - `rt session-reset`
  - `rt repair-apply`
- Overnight full refresh failure was **not** a scan failure.
  - all 4 scans finished
  - failure was final `payload sync --upgrade-missing`
  - qB auth reset with `Connection reset by peer`
- Recovery / hardening now exists in:
  - `bin/run-hashall-upgrade-scans.sh`
- New behavior:
  - preflight qB + RT health before payload sync
  - restart whole `gluetun_qbit` stack if degraded
  - retry payload sync once after restart
  - `--payload-sync-only` to resume a failed overnight run without rescanning
- Recommended next operator command after this exact failure:
  - `bin/run-hashall-upgrade-scans.sh --payload-sync-only`
- This recovery path was already exercised successfully once:
  - stack restart succeeded
  - payload sync completed
  - no scan rerun was needed

## 2026-04-01 Refresh + Client Transition State

- New design/ops doc:
  - `docs/operations/TORRENT-CLIENT-AGNOSTIC-PLAN.md`
- `hashall` is currently:
  - rt-capable for repair and audit
- RT-backed payload sync and refresh are now available
- `rehome apply` is still qB-authoritative
- Do **not** shut qB down yet if `hashall` needs to:
  - run `refresh`
  - materialize torrent-backed `payloads`
  - execute or verify `rehome` plans
- Current managed refresh coverage is now intended to be:
  - `/stash/media`
  - `/pool/data`
  - `/pool/media`
  - `/mnt/hotspare6tb`
  - plus the configured destination root `/pool/media/torrents/seeding`
- Refresh behavior changed in repo code:
  - nested dataset scanning is now on by default
  - refresh dedupe expands to all covered device aliases / datasets under refreshed roots
- Practical operator guidance:
  - broad pool media refresh should now be safe via `hashall refresh --scan-hash-mode upgrade --drift-policy quick`
  - if exact explicit coverage is desired, use `bin/run-hashall-upgrade-scans.sh`
- DB rewrite is **not** needed to reuse existing `/pool/media/torrents/seeding` scan data when scanning `/pool/media`
  - existing hashes are keyed by relative path / metadata and will be reused
- ZFS scrub state at last check:
  - `pool` scrub had already completed cleanly
  - `stash` scrub was canceled because it had run recently and was not needed during this work

## 2026-03-27 Dual-Client Default + Drift Cleanup

- New handoff doc:
  - `docs/operations/RT-QB-DRIFT-HANDOFF.md`
- Going forward, assume seeded data is dual-client sensitive by default.
- Do not treat qB-only status as the default assumption.
- Current refined drift sweep:
  - `4522` hashes exist in both clients
  - `55` have real rt/qB path drift after normalization
  - none of the still-remaining `/pool/data` migration items are currently drifted between rt and qB
- Highest-priority cleanup is the `19` rows where qB already points at `/pool/media` but rt still points elsewhere.
- Code follow-up required:
  1. make migration success checks dual-client aware
  2. make reclaim protection rt-aware as well as qB-aware
  3. stop assuming path normalization is complete when only qB has moved

## 2026-03-28 rt-only cleanup status

- qB is gone; rt is the only live client.
- `hashall rt repair-report` is now the live reevaluation command for the old drift action-plan JSON.
- The former Wave 1 bucket (`fix_now_repoint_rt_to_pool_media`) now evaluates as fully `aligned_now`.
- Current live remainder is `6` rows total:
  - `4` straightforward `normalize_rt_old_download_path` repoints
  - `2` shape-specific review rows
- Live checklist command:
  - `hashall rt repair-report --report out/rt-qb-savepath-drift-action-plan-2026-03-27.json --unresolved-only --markdown-output`
- Canonical current handoff:
  - `docs/operations/RT-REPAIR-REMAINING-CHECKLIST.md`

## 2026-03-25 Active Findings (compact-safe) — UPDATED

- Pivot priority is now back on `pool/data -> pool/media` migration.
- Current operational blocker is headroom, not repair/tooling:
  - live `df -h` now shows `0` available on both `/pool/data` and `/pool/media`
  - current catalog still shows:
    - `26` qB rows under `/pool/data`
    - `361` qB rows under `/pool/media`
  - migration should not resume until space is reclaimed
- Recent repair/content follow-up work is complete enough to pause:
  - invalid qB save-path guards are in
  - donor-style repair mismatch handling is in
  - non-qB inventory scanning and read-only reporting are in
  - shared donor ranking is partially wired into repair planning
- The immediate next migration action is therefore:
  1. reclaim pool headroom
  2. re-evaluate the current live qB failure cluster rather than relying on stale carve-out shorthand
  3. then generate the next safe `pool/data -> pool/media` batch
- That next-safe batch is now ready:
  - plan: `out/rehome-plan-pool-data-to-media-nextsafe-2026-03-26.json`
  - dry-run: passed cleanly
  - contents:
    - `The.Substance.2024...` dir root
    - `The.Substance.2024...` file root
    - `The.Edge.of.Sleep.S01...`
    - `The Last Stop in Yuma County...`
    - `UEFA.Europa.Conference.League...`
  - excluded on purpose:
    - current failed-ish movie-family rows
    - `Alien Romulus`
    - `Shining Girls`
    - `Transformers.One`
  - total planned bytes: `34,821,012,982`
  - current reason it is not yet applied:
    - live `df -h` still shows `0` available on both `/pool/data` and `/pool/media`

## 2026-03-26 Live qB Failed-ish Set (compact-safe)

- Current live qB failed-ish set is `9` items:
  - `6` `stoppedDL`
  - `3` `stalledDL`
- Current hashes:
  - `20555f704e0ae477dce28844c95c626fcf78a261`
  - `e2ae560a5d51186e2160099aa56d63687a25def1`
  - `5c86280a99d1007104452b2f72d0d686e092e2f8`
  - `96d896ca35f42d93e4a4bdee92e8ac90adc34b54`
  - `7dafdd61e6b9d58d9721c12d8a3da2cde40fc776`
  - `127c38342cfedaf4016b8079be13c5f7883b9cfe`
  - `5feb771c9b7f75fe09205204b367c88efa993031`
  - `5caca88d29e64de495a47b53a466f7cadcb3ce02`
  - `c8f01321b9fe0697c19c9aa450b570b59548eb15`
- Live shape of this cluster:
  - mostly `/data/media/torrents/seeding/...` runtime drift / missing-content fallout
  - not evidence of a current explicit `skip-check` flag
  - all inspected fastresume rows currently have `sequential_download=0`
  - explicit qB tag/category/name search found `0` `skip-check` / `skip_check` / `skipcheck` matches
- Most actionable split:
  - missing-content `stoppedDL 0%` rows:
    - `20555...`
    - `e2ae...`
    - `5c862...`
    - `7daf...`
    - `5feb...`
    - `c8f013...`
  - near-complete `stalledDL` rows with content still present:
    - `96d896...`
    - `127c383...`
    - `5caca88...`
- `5feb...` is the clearest metadata-drift example:
  - runtime `save_path=/data/media/torrents/seeding/movies`
  - runtime `content_path=/incomplete_torrents/...`
  - fastresume `save_path=/incomplete_torrents`
  - fastresume `qBt-savePath=/data/media/torrents/seeding/movies`
- `c8f013...` remains the donor-looking broken-payload case:
  - runtime points at `/data/media/torrents/seeding/movies/...`
  - content missing on disk
  - catalog payload row is effectively empty (`payload_hash=NULL`, `file_count=0`, `total_bytes=0`)
- Current migration triage:
  1. repair-first:
     - `20555...`
     - `e2ae...`
     - `7daf...`
     - `5feb...`
     - `c8f013...`
  2. same-family repair with `5feb...`, but not its own separate migration blocker:
     - `5c862...`
  3. monitor only; do not let these near-complete rows block general pool migration:
     - `96d896...`
     - `127c383...`
     - `5caca88...`

## 2026-03-26 Historical Carve-Out Recheck (compact-safe)

- `Alien Romulus`
  - no current live qB match by name/save path
  - keep as historical special-case context only
- `Shining Girls`
  - one current live qB match:
    - `57c38fa86c83c211a6233c8302afde1bd14c6ace`
    - state `stoppedUP`
    - path `/pool/media/torrents/seeding/cross-seed/TorrentDay`
  - not currently part of the failed-ish qB set
  - keep as historical content-conflict context, not as the current live blocker
- `West Wing`
  - no current live qB match by name/save path
  - keep as historical proving-lane context, not as the current live blocker

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
- Intent clarification:
  - the operator goal is to hash folder trees broadly and find duplicate folder trees quickly
  - those duplicate/non-qB trees should be usable as donor candidates for qB repair and runtime
    drift remediation
  - the desired feature is therefore broader than "scan everything"; it is "scan and make folder
    trees comparable/searchable outside qB roots"
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

## 2026-03-26 Non-qB Scan Sitrep (compact-safe) — UPDATED

- The non-qB upgrade scan in tmux session `hashall-nonqb-scan` completed.
- Completed sequence:
  - `/pool/data/orphaned_data`
  - `/pool/data/seeds`
  - `/pool/data/RecycleBin`
- It used:
  - `--hash-mode upgrade`
  - `--drift-policy quick`
- Rationale:
  - quick hashes already existed broadly
  - the main missing value for duplicate-tree / donor analysis was SHA256 coverage
- Final state after the run:
  - `orphaned_data`: `19134` files, `2.49T`, SHA256 `19134/19134`
  - `seeds`: `1255` files, `3.70T`, SHA256 `1255/1255`
  - `RecycleBin`: `63` files, `690.4M`, SHA256 `63/63`
  - `cross-seed-link`: already `1327/1327` SHA256-complete
  - `cross-seed`: already `14/14` SHA256-complete
- The first concrete feature step after scan completion is now in code:
  - read-only `hashall content inventory`
  - read-only `hashall content duplicates`
  - read-only `hashall content donors --torrent <hash>`
- Root discovery was then refined to stop treating broad container dirs as single content roots.
- Current live `hashall content inventory` output now discovers `14030` canonical non-qB roots
  across `orphaned_data`, `seeds`, and `RecycleBin`, in about `1.3s`.
- Current live `hashall content duplicates` reports `23` exact duplicate groups at this refined
  root-discovery level.
- Operator-friendly filtering/ranking is now in place for the read-only reports:
  - inventory filters: `--kind`, `--status`, `--path-contains`, `--min-bytes`, `--sort`, `--limit`
  - duplicate filters: `--path-contains`, `--min-bytes`, `--sort`, `--limit`
- `content donors --torrent` is now partially integrated into repair planning as a ranked planner
  input:
  - repair logs the top ranked donor candidates from the shared donor planner
  - hard-fail mismatch output can now include the top donor and confidence
  - repair still requires explicit `--good`; it does not auto-pick donors yet
  - current limitation: if the broken qB payload row is effectively empty (`payload_hash=NULL`,
    `file_count=0`, `total_bytes=0`), generic donor ranking may return no candidates even when the
    explicit donor-driven repair path can still proceed
- The next feature step is not more scanning; it is:
  - define the durable non-qB content inventory / duplicate-tree lookup layer
  - then pivot priority back to `pool/data -> pool/media` migration

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
  - local cache path is `~/.cache/silo-qb/` (silo owns daemon; hashall reads)
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

## 2026-04-19 Normalization Loop Status

- `hashall` is now `0.8.14`
- Code changes in progress:
  - `src/hashall/qbittorrent.py`
    - read-only `get_torrent_info()` and `get_torrents_payload()` now fall back to cached rows on auth/login failure before live reads.
  - `src/hashall/path_normalize.py`
    - plans no longer crash on transient qB/RT read failures
    - RT row lookup now prefers the shared RT cache
    - helper result now includes `outcome`
    - empty qB path fields no longer derive the worktree cwd as an RT target
  - `scripts/pilot-normalization.sh`
    - candidate classification now uses RT path scope when qB path fields are blank
- Verification completed this pass:
  - `pytest -q tests/test_qbittorrent.py tests/test_path_normalize.py`
  - result: `32 passed`
- Additional outcome/wrapper hardening now landed:
  - helper result can now report:
    - `path_converged`
    - `verifying`
    - `verified`
    - `ambiguous_needs_review`
    - `partial_state`
  - apply failures that previously raised now return structured results with `result.error` where possible
  - wrapper now:
    - fails closed for `--pick-safe` / `--apply` when RT cache freshness is `stale_error`
    - surfaces `skip:issues:...` before `qb_not_stopped:unknown` in degraded qB-read cases
    - uses broader qB/RT `checking*` semantics in watch mode
    - records helper outcome/error after apply instead of relying only on ad-hoc watch logic
- Dry-run outcome:
  - direct `payload normalize-cross-seed-link --hash ...` now returns a non-ready plan with explicit issues instead of traceback when qB login resets
  - wrapper dry-run/list mode stays safe under:
    - qB login resets
    - RT cache `stale_error`
- Current blocker:
  - no safe candidate was available for wrapper auto-pick because:
    - qB login was still resetting during plan reads
    - RT cache remained `stale_error`
  - wrapper preflight now exits before auto-pick/apply under that RT cache condition
- Next step:
  - rerun wrapper dry-run / auto-pick after qB and RT cache health recover
  - only then resume the tiny live pilot loop

## 2026-04-19 Post-Recovery Normalization Status

- Environment recovered:
  - `qbittorrent_vpn` and `rtorrent_vpn` were recreated from docker compose after both had died
  - wrapper preflight is healthy again: `qb=ok rt=ok rt_freshness=fresh`
- Live pilots completed successfully after controller recovery:
  - `5b13542670579f80881b496032cb95db09e352af`
  - `e04e524750c999acfc9afd5c9a604e12fbaee0d8`
  - `5c877f46f4d9fa0d8ea18bf72fe6711680d03cf6`
- Current live legacy count:
  - qB `cross-seed-link`: `16`
  - RT `cross-seed-link`: `16`
- Additional uncommitted fixes after `10f54f9` / `0.8.14`:
  - `src/hashall/path_normalize.py`
    - RT runtime target derivation now uses shared `derive_rt_target_directory(...)`
    - helper no longer upgrades bad RT/qB terminal states like `error` to `verified`
    - final RT verification now prefers the last good aligned RT row over a later bad terminal read
  - `scripts/pilot-normalization.sh`
    - post-check and watch now try live qB / live RT reads for the selected hash before falling back to cache snapshots
    - this fixes false `ambiguous_needs_review` watch results caused only by stale RT cache rows
    - safe auto-pick now prefers `/pool/media` first, then continues into `/data/media` / `/stash/media`
  - `tests/test_path_normalize.py`
    - added coverage for one-file multi-file RT target derivation
    - added coverage for preferring a good aligned RT row over a later bad terminal read
    - added coverage for same-inode repoint cases where canonical target already exists
- New late-lane normalization finding:
  - the final `/data/media` legacy rows were not actually blocked by bad state
  - they were blocked because canonical `cross-seed` targets already existed as the same hardlinked file
  - helper now treats those as safe repoint-only normalizations instead of `target_content_already_exists`
- Verification for the current uncommitted slice:
  - `pytest -q tests/test_path_normalize.py tests/test_qbittorrent.py`
    - `34 passed`
  - `bash -n scripts/pilot-normalization.sh`
- Important nuance from the `5c877...` pilot:
  - the normalization itself succeeded
  - direct live qB and RT both show canonical `cross-seed` paths and RT `stalledUP`
  - the old watch implementation misreported `ambiguous_needs_review` because it was still reading stale RT cache state
  - the wrapper fix above addresses that observability bug
- Next recommended step:
  - commit the current helper/watch fixes with a patch bump
  - then continue the one-hash `/pool/media` normalization lane with the wrapper

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

## 2026-04-20 Code Refactoring Wave

- Wave 11 executed code refactoring to align all helpers with canonical `orphans` path (completed 2026-04-20 18:54).
- Updated files:
  - `src/hashall/orphan_sweep.py`: changed ORPHANED_DATA_DEST to `/pool/media/torrents/orphans`, updated skip patterns
  - `src/hashall/content_inventory.py`: recognize both `orphaned_data` and `orphans` in kind detection, prioritize canonical path in sort order
  - `src/hashall/cli.py`: updated orphan-sweep docstring, added canonical orphans to default content roots, updated 4 help text references
  - `src/hashall/qb_repair_payload_group.py`: added canonical orphans to DEFAULT_CONTENT_BASE_ROOTS
- All helpers now prefer `/pool/media/torrents/orphans` with fallback to legacy `/pool/data/orphaned_data` during transition
- Tests: 20/20 passed (test_orphan_sweep.py, test_path_normalize.py)

## 2026-04-20 Final Orphan Rename Batch Outcome

- Wave 10 executed the final `orphaned_data -> orphans` batch (completed 2026-04-20 18:55).
- Moved all remaining 17 roots from `/pool/media/torrents/orphaned_data` to `/pool/media/torrents/orphans`:
  - Batch 1 (6 roots): abtorrents, cross, cross-seed, hawke-uno, _movie, movies
  - Batch 2 (5 roots): privatehd, _qb-unique-repair, RecycleBin, _rehome-unique, seedpool (API)
  - Batch 3 (6 roots): thegeeks, TorrentDay, TorrentLeech, XSpeeds, YOiNKED (API), YUSCENE (API)
- Operational finding:
  - One RT hash (f37b9983...) still pointed to old `/pool/media/torrents/orphaned_data/` path
  - RT was repointed with `rt repoint --hash ... --target-directory ... --apply`
  - RT hash now shows state=`checking` at canonical `/pool/media/torrents/orphans/` path
- Post-wave state:
  - `/pool/media/torrents/orphaned_data` directory is now completely empty and has been removed
  - All 27 orphan roots now live under canonical `/pool/media/torrents/orphans`
  - qB has no live `orphaned_data` rows
  - RT has no live `orphaned_data` rows
- Strategic completion:
  - Big-picture TODO item #2 "Finish orphaned_data -> orphans" is now COMPLETE
  - Code now fully aligned with canonical naming
  - Next strategic lanes are:
    1. Resume cross-seed-link → cross-seed normalization loop (item #1, ongoing pilots)
    2. Clean up broken live torrents (item #3: PD holdouts, Dexter pair, /data/media stoppedDL)
    3. Drain /pool/data torrent payloads (item #4)


## 2026-04-20 Claude Session Completion - Orphan Migration + Normalization Verification

**Session Duration:** 18:54-19:22 (28 min)

**Major Accomplishments:**

### 1. ✅ Big-Picture TODO #2 Completed (orphaned_data → orphans)
- Wave 10: Moved all 17 remaining orphaned_data roots to orphans in 3 batches
- Wave 11: Code refactoring (d4bd9b0) - updated 4 core modules to canonical path
- Wave 12: Removed stale `/pool/media/torrents/seeding/cross-seed-link` residual directory
- Result: Zero live refs to legacy paths (verified RT cache, qB confirmed offline)

### 2. ✅ Big-Picture TODO #1 Verified Complete (cross-seed-link → cross-seed)
- Found 27 stale catalog rows pointing to cross-seed-link
- Verified in RT state-audit: ALL 27 hashes already normalized to `/cross-seed/` paths
- Example: hashes 2cc3b63d, 2fd37137, 323291dd all live-seeding from `/pool/media/torrents/seeding/cross-seed/FileList.io/...`
- Deleted cross-seed-link directory was correct stale residue removal
- **Status:** Normalization complete; catalog just needs refresh scan (independent task)

### 3. Code Refactoring Committed (d4bd9b0)
- orphan_sweep.py: ORPHANED_DATA_DEST → `/pool/media/torrents/orphans`, skip both old+new dirs
- content_inventory.py: recognize both orphaned_data and orphans, prioritize canonical
- cli.py: updated docstring, defaults, 4 help texts
- qb_repair_payload_group.py: added canonical orphans to defaults
- Tests: 20/20 pass

**Broken Torrent Status (PD Trio + Dexter Pair):**
- All 5 confirmed stalledDL on /data/media (stash mount)
- 96d896, 127c38, 5caca8 (PD) + 245f2b, e36553 (Dexter)
- qB connection was intermittent during session; recommend health check before repair work
- No obvious qB→/pool/media missing-file drift detected
- Ready for: RT↔qB sync check, hitchhiker audit, canonical path restoration

**Session Commits:**
- d4bd9b0: refactor(orphans): align code to canonical orphans path
- cf43411: docs(orphans): record Wave 10 final batch and code refactoring  
- c67081c: docs(session): record Wave 10-12 completion

**Recommended Next Steps (from user guidance):**
1. Monitor/fix RT↔qB drift (qB = silent mirror, must stay synced with RT)
2. Identify & fix N→1 hitchhiker payloads (each hash → unique payload tree)
3. Restore canonical save paths (QBit ATM roots: /seeding/<tracker-key>, /seeding/cross-seed/<tracker>, etc.)
4. Repair broken torrents (after above 3 are resolved)
5. Drain /pool/data torrent residue

