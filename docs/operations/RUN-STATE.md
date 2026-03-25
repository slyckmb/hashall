# Operational Run State

Last updated: 2026-03-21

## 2026-03-21 Fastresume Rollback Fix

**Version:**
- `hashall=0.8.9`

**New fix in code:**
- hardened fastresume failure handling now restores fastresume backups when patching had already
  succeeded but a later post-patch step failed
- qB is then restarted after backup restore so runtime metadata can return to the pre-run source
  paths instead of remaining stranded on `/pool/media`

**Why this was needed:**
- the `0.8.8` live `West Wing` retry showed all five siblings in `missingFiles` on `/pool/media`
  even though the target files were gone
- fastresume backups from the failed patched run still existed, which confirmed rollback had not
  restored them automatically

**Validation:**
- focused fastresume rollback regressions passed

## 2026-03-21 qB Runtime Settle Fix

**Version:**
- `hashall=0.8.8`

**New fix in code:**
- hardened fastresume post-patch now waits for qB restart/auth settle before runtime verification
- runtime `save_path` verification now requires live qB API data and ignores cache-fallback reads
- if runtime `save_path` stays stale after a good fastresume patch, executor retries with an
  explicit `set_location()` nudge before failing
- post-patch qB accounting now waits to settle, but still fails fast for clear bad states
  (`pausedDL`, `stoppedDL`, `downloading`, nonzero `amount_left`)

**Why this was needed:**
- the prior `West Wing` pilot already proved copy, verify, view build, and sibling relocate
- the remaining failure was qB runtime handoff after restart, not another data-path problem

**Validation:**
- rehome regression pack: `81 passed`
- live dry-run of `out/rehome-plan-west-wing-s02-2026-03-21-v087.json` completed cleanly

## 2026-03-21 Content-Proofed Reuse + Shining Girls Conflict

**Version:**
- `hashall=0.8.7`

**New fix in code:**
- target-family reuse is now proven from live file content, not just file count / total bytes
- planner + executor compute a real payload hash from the current files before treating a target
  family as reusable
- same-size same-byte sibling roots that differ by content now block before apply instead of
  falling through to target-view preflight

**What this exposed:**
- `Shining.Girls...` on `/pool/media` is a real target-side content conflict
- `TorrentDay` and `Aither` sibling roots match by counts/bytes but differ by actual content
- this is a data repair problem, not another planner/apply bug

**Validation:**
- targeted rehome sim suite: `78 passed`
- `West Wing` fresh live dry-run on 2026-03-21 remains a clean `MOVE`
- `Shining Girls` live plan generation is expected to run longer now because it hashes the actual
  files to prove or reject reuse

## 2026-03-20 West Wing Rehome Root Cause + Current Dry-Run State

**Version:**
- `hashall=0.8.6`

**Root cause of the bad 2026-03-20 `West Wing S02` run:**
- planner chose `MOVE` from the absence of one canonical target root and ignored alternate sibling
  target views already present on `/pool/media`
- target-view preflight mutated existing target files instead of only comparing them
- rollback removed a pre-existing good `/pool/media` sibling view because it did not track which
  views were created by the current run

**Fixes now in code:**
- family-level target reuse before donor copy
- fail-fast alternate-sibling conflict detection before rsync
- read-only target-view preflight
- rollback only deletes target views created in the current run
- extra `failure-pre-rollback` and `failure-post-rollback` reality snapshots

**Fresh live dry-run on 2026-03-20 (`/pool/data/media/torrents/seeding` → `/pool/media/torrents/seeding`):**
- `Shining.Girls...` -> `REUSE`
- `The.West.Wing.S02...` -> `MOVE`
- `Alien Romulus` -> `MOVE`

**Important current reality for `West Wing`:**
- the old good `/pool/media` sibling donor is already gone from the earlier buggy run
- so the new live plan correctly reports:
  - `target_family_exact_views=0`
  - `target_family_conflicts=0`
- this is expected current reality, not another planner miss

**Recommended pilot after this fix set:**
- pilot the `Shining.Girls...` `REUSE` family first
- do **not** expect `West Wing` to be a reuse pilot until a good target-side donor exists again

## 2026-03-19 Migration Analysis

**Live counts (as of 2026-03-19):**
- Pool-data torrents remaining: `old_path_count=41` (up from 34 in 2026-03-13 docs)
- Pool-media torrents: `new_path_count=344`
- `/stash` torrents: `0`
- Migration seed-root-state: `in_progress`

**Current live split of the 41 pool-data torrents (confirmed from qB cache on 2026-03-19):**
- `8` under `/pool/data/media/torrents/seeding`
- `28` under `/pool/data/cross-seed-link`
- `5` under `/pool/data/cross-seed`
- state mix: `40 stalledUP`, `1 uploading`

**Wrapper warning — `bin/migrate-pool-data-to-media.sh` is not the full 41-torrent resume path:**
- The wrapper's default `SOURCE_ROOT` is `/pool/data/media/torrents/seeding`.
- A dry-run on 2026-03-19 selected only the `8` torrents under that exact root.
- It did **not** include the other `33` remaining `/pool/data` torrents under
  `/pool/data/cross-seed-link` and `/pool/data/cross-seed`.
- The wrapper dry-run also included `Alien Romulus`, which remains a deliberate repair/proving lane
  and should not be treated as a normal plain-migration batch item.
- Practical meaning: use the fresh `relocate-plan` flow to reason about the full `41`-torrent
  remainder; do not assume the wrapper resumes the whole lane as-is.

**Current special cases within the live 41-torrent remainder:**
- `Alien Romulus` (`1376e795...`) remains a real special-case/proving lane item:
  - still lives under `/pool/data/media/torrents/seeding/cross-seed/hawke-uno`
  - still tagged `~noHL`
  - still belongs to the mixed sibling family called out in the active project docs
  - status: **not resolved** for plain migration batching
- `Shining.Girls...` remains a known bad reuse candidate:
  - live pool-data hashes are `57316294...`, `0fff0ce2...`, and `4511c5f4...`
  - the two rows under `/pool/data/media/torrents/seeding` are exactly the ones the old wrapper
    would try to include
  - project continuity docs already say to exclude this group from future plain batches
  - status: **not resolved** for plain migration batching
- `The.West.Wing.S02...` appears as a multi-row family in the old wrapper dry-run:
  - hashes `62c3d90c...`, `cbe76a6e...`, `ce2445dd...`, `2179ba97...`, `71cdd51d...`
  - this is not a blocker by itself, but it confirms the wrapper is row/per-torrent oriented rather
    than a clean "unique payload family" batcher
  - status: **not a separate blocker**, but a reason to prefer `relocate-plan` over the wrapper
- `V for Vendetta` remains only a refresh follow-up anomaly, not an active migration blocker
  for the pool-data remainder

**Blockers — must resolve before resuming migration:**

1. **Stale rehome.lock** (`~/.hashall/rehome.lock`)
   - Lock is 5 days old (last written 2026-03-14 10:02)
   - Process is almost certainly dead; verify and remove:
     ```bash
     cat ~/.hashall/rehome.lock
     ps -p <pid-from-lock> || echo "process dead → safe to remove"
     rm ~/.hashall/rehome.lock
     ```

2. **640 consecutive qB API failures** in cache meta
   - Cache is fresh (`source=daemon_live`, updated `2026-03-19T15:32`)
   - Failure count may be a transient artifact from a qB restart; verify before trusting plan output:
     ```bash
     python3 -c "
     import json, pathlib
     m = pathlib.Path.home() / '.cache/hashall-qb/torrents-info.meta.json'
     d = json.loads(m.read_text())
     print('last_error:', d.get('last_error'))
     print('last_error_at:', d.get('last_error_at_iso'))
     print('consecutive_failures:', d.get('consecutive_failures'))
     print('source:', d.get('source'))
     "
     hashall qb status 2>&1 | head -5
     ```

3. **Catalog freshness** — confirm before running a new plan:
   ```bash
   hashall refresh --verbose 2>&1 | tail -20
   ```

**Cross-repo naming note:**
- The external dashboard/cache repo previously referenced in older notes as `qbitui` is now `silo`.
- Treat `silo` as canonical. Any `qbit-*` names in that repo are compatibility shims, not the preferred integration target.

**Phase 0 → Phase 1 resumption workflow:**
```bash
# Phase 0: clear blockers (operator)
rm ~/.hashall/rehome.lock        # only after confirming process dead
hashall qb status                # verify live API responds
hashall refresh --verbose        # confirm catalog fresh

# Phase 1: generate fresh plan
hashall rehome relocate-plan \
  --source-root /pool/data \
  --target-root /pool/media/torrents/seeding \
  --output out/rehome-plan-pool-data-to-media-2026-03-19.json \
  2>&1 | tee ~/.logs/hashall/rehome/relocate-plan-2026-03-19.log

# Phase 1: verify plan covers all 41 qB pool-data torrents
python3 -c "
import json, pathlib
cache = json.loads((pathlib.Path.home()/'.cache/hashall-qb/torrents-info.json').read_text())
torrents = cache if isinstance(cache, list) else cache.get('result', cache.get('torrents', []))
pool_data = [(t.get('hash',''), t.get('name','')[:60], t.get('state',''))
             for t in torrents if '/pool/data' in t.get('save_path','')]
plan = json.loads(pathlib.Path('out/rehome-plan-pool-data-to-media-2026-03-19.json').read_text())
plan_hashes = {h for p in plan.get('plans', []) for h in (p.get('affected_torrents') or [])}
print(f'qB pool-data torrents: {len(pool_data)}')
print(f'Plan covers: {len(plan_hashes)} hashes')
for hash_, name, state in pool_data:
    covered = '✓' if hash_ in plan_hashes else '✗ NOT IN PLAN'
    print(f'  {covered}  {state:15s}  {name}')
"
```

**Notes on 2026-03-18/19 code audit (may affect plan output):**
- `planner.py` bind-mount false-positive fix: may reclassify previously-BLOCKED candidates
- `planner.py` single-torrent unique-view fix: target paths change for 1-torrent payloads
- Both are LOW-risk corrections; executor logic unchanged

---

Last updated: 2026-03-13 (historical section below)

## Live Reality / Drift

- `hashall` is now `0.8.5` (see version history below for prior milestones).
- New 2026-03-15 qB compatibility/cache hardening:
  - local cache implementation now lives in this repo:
    - `src/hashall/qb_cache.py`
    - `bin/qb-cache-agent.py`
    - `bin/qb-cache-daemon.py`
  - the cache now uses the shared qB client, not silo’s legacy pre-refactor raw-API implementation
  - `src/hashall/qbittorrent.py` now detects and caches a qB server profile:
    - `app_version`
    - `webapi_version`
    - `qt_version`
    - `libtorrent_version`
  - state alias normalization is now centralized:
    - `pausedDL` / `stoppedDL` => `stoppedDL`
    - `pausedUP` / `stoppedUP` => `stoppedUP`
  - current cache root:
    - `~/.cache/hashall-qb/`
  - current read-heavy scripts using that cache:
    - `qb-checking-watch`
    - `qb-start-seeding-gradual`
    - `qb-path-watch`
    - PD triage/score/finder scripts
    - triage step scripts
    - `qb-repair-batch` list discovery reads
  - important limit:
    - silo’s external dashboard/cache path has not been updated in this repo; treat that as separate follow-up work if cross-repo alignment is still wanted
- Active docs are now intentionally minimal and stub-free:
  - canonical active docs:
    - `README.md`
    - `docs/README.md`
    - `docs/REQUIREMENTS.md`
    - `docs/architecture/SYSTEM.md`
    - `docs/tooling/CLI-OPERATIONS.md`
    - `docs/tooling/REHOME-RUNBOOK.md`
    - `docs/operations/RUN-STATE.md`
    - `docs/project/AGENT-PLAYBOOK.md`
    - `docs/project/PLAN.md`
  - continuity docs:
    - `docs/handoff.md`
    - `docs/ops-log.md`
    - `docs/next-agent.md`
    - `docs/NEXT-AGENT-PROMPT.md`
  - superseded material now lives in `docs/archive/2026-doc-consolidation/`
- Anchor the current migration/rehome model on this invariant:
  - each qB item needs its own correct payload tree on disk
  - that tree should normally be instantiated from donor content via hardlinks
  - `unique target` means unique per-item file structure, not mandatory duplicate physical copies
- New 2026-03-14 content-drift hardening:
  - `hashall scan` now has `--drift-policy metadata|quick|full`
  - `hashall refresh` / `rehome refresh` now thread through:
    - `--scan-hash-mode fast|full|upgrade`
    - `--drift-policy metadata|quick|full`
  - unchanged-file behavior is now explicit:
    - `metadata` trusts unchanged size+mtime
    - `quick` recomputes quick hashes on unchanged files and escalates to full hashing if drift is detected
    - `full` recomputes full hashes for unchanged files in scope
  - targeted validation:
    - `pytest tests/test_scan_hardlinks.py tests/test_scan_incremental.py tests/test_rehome_refresh_safety.py -q`
    - result: `36 passed`
- New 2026-03-13 duplicate-byte hardening:
  - `src/rehome/view_builder.py` now relinks preexisting identical destination files to the donor inode instead of silently accepting copied bytes
  - `bin/qb-repair-fresh.py` now normalizes existing identical targets the same way
  - this closes the known “successful run leaves new jdupes groups behind” leak in both the rehome path and the fresh repair-prep path
- New 2026-03-13 refresh / jdupes diagnosability hardening:
  - the previous `refresh --verbose` orchestration did not remain alive as a clear owner of the dedupe backlog after step 3.5
  - observed failure signature:
    - `refresh --verbose` run `pid=1386781` reached pool-media dedupe planning
    - `27` duplicate groups were surfaced
    - a failing group like `Cinderella.2021...` only appeared deep in jdupes group logs as `jdupes did not link files with matching SHA256`
  - hardening now added:
    - `hashall link execute` prints the jdupes log glob for the plan and a failed-action preview when link failures occur
    - `bin/db-refresh-step4_5-link-dedup.sh` now writes a structured per-device summary JSON and logs the plan status / failed-action preview after dry-run and apply
  - operator meaning:
    - a refresh/dedupe run should now end with an explicit step-3.5 summary artifact instead of forcing diagnosis from a raw shared log tail
  - latest refresh status:
    - `~/.logs/hashall/rehome/refresh/20260313-172217.log`
    - ended `OK`
    - one follow-up anomaly remains:
      - root `99/99` `V.for.Vendetta...` under `/pool/media/torrents/seeding/cross-seed/hawke-uno/...`
      - logged `files=0 bytes=0`
      - `Upgrade ended incomplete: groups=0`
    - this is an explicit backlog item, not a refresh-run failure
- New 2026-03-13 planner stale-no-op hardening:
  - `relocate-plan` now skips groups when all per-hash view targets already have `source_save_path == target_save_path`
  - this removes fully converged families from the live remainder even when source cleanup is still deferred
  - live proof:
    - `Brave.New.World.US.S01...` succeeded at `~/.logs/hashall/reports/rehome-relocate/20260313-114142-66eebb2df636b12a/`
    - refresh-seeded stale-no-op trimming dropped the older remainder from `31` (`refresh8`) to `29` (`refresh9`)
- New 2026-03-13 Twisters bridge hardening:
  - surviving target donors are now preferred for stale already-targeted rows
  - single-file unique targets preserve `root_dir/file` layout
  - mixed `reconcile_subset + patch_one` hardened manifests now work
  - validate/patch failures after `qb_stop` now restart qB before returning
  - reality snapshots now call this class `stale_runtime_and_fastresume_root`
  - live proof:
    - `Twisters.2024...` succeeded at `~/.logs/hashall/reports/rehome-relocate/20260313-112558-9962465e30b69544/`
    - `9/9` rows verified `exact_tree`
    - `reconcile_rows=8 patch_rows=1`
- New 2026-03-13 de-hitchhike invariant:
  - root-to-root relocation planning now defaults multi-hash groups to per-hash unique target roots
  - missing-file reconnect plans now do the same
  - stash->pool `rehome` view planning now also routes multi-hash groups into `_rehome-unique/<hash>` targets
  - successful attaches now remove an unused intermediate donor root when the full sibling group is covered in-plan
  - operator meaning:
    - newly constructed migrations/reconnects should stop manufacturing fresh N->1 hitchhiker targets
    - older shared-target groups remain visible as legacy debt until explicitly de-hitchhiked
    - the replacement form is a unique per-item payload tree backed by hardlinks, not a separate byte copy per item
  - targeted validation for this slice:
    - `pytest tests/test_rehome_normalize.py tests/test_rehome_qb_missing.py tests/test_rehome_mapping.py tests/test_rehome_catalog_sync.py -q -k 'unique or payload_rows or preflight_existing_view_conflicts_logs_progress_for_missing_targets'`
    - `pytest tests/test_rehome_atomic_relocation.py -q -k cleanup_unused_target_donor_removes_intermediate_root`
    - result: `7 passed`
- Earlier live proof under the older pre-fix planner:
  - `Cinderella.2021...` completed successfully at `~/.logs/hashall/reports/rehome-relocate/20260313-095751-578fffbfe4fc2f8c/`
  - qB ended healthy on `/pool/media/...`
  - its post snapshot still warned about one shared payload row because the run started before the de-hitchhike planner landed
- Current live remainder after the Twisters + Brave success is now seeded from live qB old-root rows:
  - `old_path_count=34`
  - `new_path_count=317`
  - qB health snapshot:
    - `stalledup=5152`
    - `stoppeddl=1` (`Alien Romulus`, real repair lane)
    - `stalleddl=2` (non-pool-data `/data/media/.../radarr` outliers)
  - next source-of-truth artifact:
    - `out/rehome-plan-pool-data-to-media-liveqb-20260313.json`
    - `seed_scope=live_qb_root`
    - `qbit_hashes=34`
    - `mapped_payloads=14`
    - `candidates=14`, `reuse=7`, `move=7`, `skipped=0`
    - `covered old-root hashes=34/34`
- New explicit next proving task:
  - use the `Alien Romulus` payload family as the next focused `rehome` / repair / `~noHL` engineering lane after the current cleanup + planner work
  - current observed live shape:
    - `14` sibling candidates
    - `7` `~noHL` siblings
    - one known incomplete row (`1376e795...`, `PD`, about `43.72%`) that remains repair-lane only
    - multiple healthy `/data/...` siblings that should be usable as donor candidates
  - engineering objective:
    - prove that `~noHL` siblings can be lifted to `pool-media`
    - ensure each resulting qB item gets its own correct payload tree there
    - keep those per-item trees hardlink-backed instead of creating redundant physical byte copies
  - do not treat this as a plain pool-data remainder batch item; it is a deliberate feature/proving task

- `hashall` is now `0.6.8`.
- Latest 2026-03-12 preflight feedback note:
  - `preflight_target_views` now emits bounded heartbeat lines during long existing-target scans:
    - `preflight_target_views_progress`
    - `preflight_target_views_view_done`
    - `preflight_target_views_complete`
  - this closes the quiet UX gap where a large healthy target tree could look stalled between `step=verify_target` and `step=build_views`
- Latest 2026-03-12 guarded target-view note:
  - `rehome` now runs `step=preflight_target_views` before `build_views` on guarded `REUSE` / donor-target paths
  - any preexisting destination view file is compared read-only against the source before new hardlinks are created
  - if one target-view path already contains different bytes, the whole plan now aborts before any sibling view mutation
  - this closes the `Novitiate...` partial-view-build risk
  - live proof:
    - `The.Long.Walk.2025...` `REUSE` completed cleanly after this change
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-214219-38c7f2c20c7af677/`
  - current live pool-data baseline after the Twisters rerun:
    - `old_path_count=34`
    - `new_path_count=317`
    - qB health snapshot:
      - `stalledup=5152`
      - `stoppeddl=1` (`Alien Romulus`, real repair lane)
      - `stalleddl=2` (outside the pool-data lane)
- Latest stale reconnect hardening on 2026-03-12:
  - `qb-missing-remediate` now builds guarded reconnect plans for `root_drift_after_rehome_reuse` rows when the mapped target payload exists under a different catalog `payload_hash`
  - that exact gap was proven live on `Peppermint...`:
    - `4` stale `/data/...` `missingFiles` rows
    - surviving payload already alive at `/pool/data/...`
    - previous behavior: `selected_plans=0`
    - current behavior: `selected_plans=1`, `verified=4`, `patched=4`
    - report dir: `~/.logs/hashall/reports/rehome-relocate/20260312-212329-4f2ac41db39d760f/`
  - resulting qB state:
    - `missingFiles=0`
    - `stoppedDL=1` (`Alien Romulus`, real repair lane)
    - `stoppedUP=4` (the reattached `Peppermint` rows left paused)
- `hashall` is now `0.4.181`.
- `rehome` now has a shared live-reality snapshot layer in `src/rehome/reality.py`.
- New proactive audit command:
  - `hashall rehome drift-audit --plan <plan.json> [--output <file>]`
- Each `rehome apply` run now writes live drift snapshots beside its hardened manifest:
  - `reality-pre.json`
  - `reality-post.json`
  - `reality-failure.json`
- Snapshot purpose:
  - compare qB runtime state, fastresume paths, catalog rows, and actual filesystem existence before trusting a plan
  - explain blocked/skipped rows in plain English instead of only raw qB state strings
- Latest verifier/reality follow-up on 2026-03-12:
  - `qb-libtorrent-verify.py` now treats instant-complete `exact_tree` results as healthy when libtorrent jumps directly to `seeding`/`stalledUP` without a visible `checking_files` transition
  - this closed the false-negative exposed by `David Khune - Wakanda - Native American Magic.epub`
  - `rehome` reality snapshots now classify plain source-only `MOVE` rows as `source_only` rather than `target_view_missing`
  - post-apply reality snapshots now downgrade short-lived target-side qB checking to:
    - row classification: `post_apply_settling`
    - group state: `settling_after_apply`
  - that means a clean apply no longer writes a misleading `blocked_qbit_transient` post snapshot just because qB is briefly checking the newly patched target
  - the `Wakanda` rerun completed successfully at `~/.logs/hashall/reports/rehome-relocate/20260312-145812-6bb9bb5432f39cbb/`
- Latest proactive stale-sibling follow-up on 2026-03-12:
  - `rehome apply` now treats any plan file with a top-level `plans` list as a batch apply input, even when `batch=true` is absent
  - the reality layer now reports out-of-plan sibling coverage directly in each snapshot:
    - `payload_group_siblings`
    - `plan_rows`
    - `out_of_plan_siblings`
    - `group_warnings`
  - `hashall rehome drift-audit` now summarizes how many plans still have uncovered same-`payload_hash` siblings
  - executor logs those uncovered-sibling warnings during apply so later cleanup drift does not stay silent
- Current group-state outputs include:
  - `ready_catalog_reconcile`
  - `ready_repoint_or_reconcile`
  - `blocked_qbit_transient`
  - `blocked_incomplete`
  - `blocked_target_view_missing`
  - `mixed_attention_required`

## Pool Migration Status

- Donor acquisition and offline attach are the shared backbone for both `REUSE` and `MOVE`.
- The current rsync-based donor transfer is still the data mover; qB is metadata-only.
- `REUSE` continues in small batches; each apply must finish with `stoppedup`/`stalledup`, no new downloads, and clean cleanup messages.
- `qb-zfs-relocate` has already proven the guarded live `pool-data -> pool-media` mover for pilot batches.
- `qb-zfs-relocate` `v0.1.13` / `hashall 0.4.179` now include live-proven verifier fixes for both:
  - the `Mickey.17...` false-partial case
  - the `Wakanda` instant-complete false-negative case
  - qB source recheck completion now requires a real transition into/out of `checking*`
  - verify retries one time when quick/exact evidence is clean but libtorrent transiently reports `partial_match` in `downloading*`
  - verify also now promotes `exact_tree + verify_ratio=1.0 + no_recheck_transition + healthy upload state` to a successful result
- `rehome` now has an explicit root-to-root planner for this domain:
  - `hashall rehome relocate-plan --source-device pool-data --source-root /pool/data/media/torrents/seeding --target-device pool-media --target-root /pool/media/torrents/seeding`
  - shared-root sibling collisions are now surfaced and get synthesized unique destination views.
- `rehome apply` now uses the hardened `qb-zfs-relocate` backend for donor verification, offline fastresume patching, restart checks, and deferred cleanup.
- Successful `MOVE` waves can now be drained safely after green apply:
  - `hashall rehome followup --cleanup` stages source roots into hidden `.rehome-cleanup-stage/<payload_hash>/...`
  - qB is observed on the target save paths before final delete
  - any qB regression restores the staged roots automatically
- Cross-device `REUSE` reruns now have a catalog-reconcile path:
  - if qB is already on the target save paths and offline verify passes, `rehome apply` logs `rehome_reconcile_only`
  - relocation validate/patch are skipped
  - catalog sync still runs and updates `torrent_instances` / target payload rows
- Mixed-state REUSE reruns now have a partial-reconcile path:
  - if a batch contains a subset of rows already repointed and verified, `rehome apply` logs `rehome_reconcile_subset`
  - the good subset is reconciled into the catalog
  - skipped/bad rows are left untouched instead of aborting the whole batch
- Non-reconcile `MOVE` runs now stop qB before patch-mode validate:
  - this avoids false `torrent_not_stopped` blocks after a successful copy + offline verify
  - the `Megalopolis.2024.REPACK...` live `MOVE` pilot proved this path on 2026-03-11

## Current `MOVE` Risk

- `MOVE` has been refactored to use the same offline fastresume attach constructor after donor acquisition.
- The new path now has a successful live pilot:
  - `Megalopolis.2024.REPACK...`
  - report dir `~/.logs/hashall/reports/rehome-relocate/20260311-173250-692ffa9407a574f4/`
  - all three sibling views verified `exact_tree`
  - qB ended `stalledUP 100%` on `/pool/media/...`
  - source cleanup remained deferred/manual
- Long `MOVE` copy windows now stream rsync progress:
  - commit `21ea673`
  - new runs emit `copy_progress percent=... elapsed=... eta=...`
  - a long silent pause after `step=move_payload` on new runs is now abnormal
- Operational guard remains: scale `MOVE` in small batches even after the pilot; keep cleanup deferred until post-run observation is established.
- Do not treat `rehome auto` returning `0 MOVE groups` as the final answer for explicit root-to-root relocation anymore; use `rehome relocate-plan` for that case.
- The current safe model is unified:
  - use `rehome relocate-plan` or `rehome auto` for planning
  - use `rehome apply` for execution
  - keep `qb-zfs-relocate` available for direct wrapper-driven dataset migration or troubleshooting

## Refresh / Identity State

- The stale-root cleanup and stoppedDL repair lane are now reflected in refresh:
  - latest `hashall refresh --verbose` finished `OK`
  - `hashall rehome qb-missing-audit --source-root /pool/data/media/torrents/seeding --target-root /pool/media/torrents/seeding` returns `0`
- Stable `fs_uuid` entries are enforced; `device_id` stays as runtime metadata.
- The catalog now updates known movers immediately rather than waiting for a later refresh.
- Do not treat the prior `PARTIAL` refresh as the current truth forever; the stale-root qB cohort has since been remediated and refresh should be rerun after the remaining repair lane is reduced.

## qB Guarding

- `qb-start-seeding-gradual.sh` now halts only on newly flipped downloading-like torrents; preexisting download-like states no longer trigger safety gates.
- StoppedDL drain/apply wraps and path watchers continue to use the shared cache agent for observability.
- `hashall rehome qb-missing-audit` now classifies stale-root `missingFiles` cohorts against qB, fastresume, and rehome history.
- Historical live audit result on 2026-03-08:
  - `49` `missingFiles` items mapped cleanly from old `/pool/data/...` roots to existing `/pool/media/...` payloads
  - tool classification: `root_drift_fastresume_stale`
  - interpretation: legacy stale-root drift, not current `qb-zfs-relocate` pilot mutations
- That stale-root `missingFiles` lane has now been remediated live.
- Current qB health snapshot:
  - `stalledUP=5144`
  - `uploading=1`
  - `stoppedUP=6`
  - `missingFiles=0`
  - no active `stoppedDL`
- The 2026-03-12 stale sibling-root drift cohort is now remediated:
  - original scope:
    - `Megalopolis...` (`4`)
    - `Cleverman.S02...` (`2`)
  - new reconnect CLI:
    - `hashall rehome qb-missing-remediate`
  - live result:
    - both payload groups were reattached successfully via guarded `REUSE`
    - `hashall rehome qb-missing-audit --source-root /data/media/torrents/seeding --target-root /pool/media/torrents/seeding` now returns `0`
  - the `6` current `stoppedUP` rows are the freshly reattached hashes intentionally kept paused after reconnect
- `qb-start-seeding-gradual` halt at `2026-03-08 14:34` is explained historically:
  - `35` halted hashes were a direct subset of the old audited `49`
  - the daemon tripped on preexisting `missingFiles` rows in protected scope, not on a newly started torrent

## Known Gaps

1. Shared-root payload groups can now be planned; the new execution path has now proven both single-plan pilots and a curated mixed batch, but not yet a live `2-to-1 -> 2-to-2` case.
2. `rehome auto` still favors donor-backed MOVE discovery and does not replace `rehome relocate-plan` for explicit root-to-root cases.
3. Cleanup/canonical-root accounting should continue to dedupe by payload root, not by torrent hash.
4. The next live gap is scaling from the first successful curated mixed batch to another curated batch from the remaining clean candidates.
5. `hashall payload siblings` read-only catalog bug is fixed in commit `74ea2b5`; use that command freely against the live catalog now.
6. Cleanup is now hardened against stale sibling refs:
   - follow-up cleanup blocks when any same-`payload_hash` torrent row still points at a non-target device or old `/data`/`/stash` alias
   - this closes the cleanup hole that could strand stale sibling hashes after source removal
7. `Mickey.17...` is no longer a carve-out:
   - the original failure looked like bad source data because offline verify died around `71%` while qB still said `100%`
   - root cause was code, not content
   - direct source verify and a clean target-copy verify both proved `exact_tree`
   - rerun result on 2026-03-12: `MOVE` completed successfully and qB ended `stoppedUP 100%` on `/pool/media/...`
8. Staged follow-up cleanup is now proven live for pool-data and adjacent backlog groups:
   - one pilot payload plus six additional `/pool/data` groups completed `cleanup_result=done`
   - follow-up reconcile then converted the healthy catalog-only cleanup backlog into actionable groups
   - two final retries initially restored because of narrow source-side ownership/permission errors, then completed after targeted ownership fixes
   - post-cleanup qB remained healthy (`stalledUP=5147`, `uploading=4`)
   - same-pool migration waves no longer need to leave every green source payload behind

## Logs to Watch

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

## 2026-03-24 Current Must-Do vs Proposal Split

### Must Do

1. Let the live `hashall refresh --verbose` run finish before starting any other refresh.
   - A concurrent second refresh on 2026-03-23 failed with `sqlite3.OperationalError: database is locked`.
   - Current live owner was verified in tmux pane `%61`.
   - Treat parallel refresh as an operationally unsafe action.
2. After the live refresh completes, generate a fresh relocation plan for the active `/pool/data -> /pool/media/torrents/seeding` lane.
   - Do not trust older plan output after the in-flight refresh changes catalog freshness.
3. Keep the known carve-outs out of plain migration batches:
   - `Alien Romulus`
   - `Shining.Girls...`
4. Re-validate the `West Wing` lane on current code before using it as a normal migration example if that lane is still pending.
   - Earlier bugs and rollback behavior changed the donor/view state enough that old assumptions are not trustworthy without a fresh check.

### Proposals

1. Add a `hashall refresh status` or similar lock-inspection helper.
   - Goal: make the live-owner / stale-lock distinction explicit without manual tmux + `/proc` inspection.
2. Improve refresh lock-holder diagnostics further.
   - Current code now rejects a second refresh even if `refresh.lock` was deleted and recreated while a live owner survived.
   - A dedicated operator-facing status command would still be clearer.
3. Add lightweight operator docs for payload-sync resume state.
   - Explain the per-scope state files under `~/.hashall/payload-sync-upgrade-state/`.
   - Explain when they are removed automatically and when an interrupted run may resume from them.
4. If cross-repo alignment work is reopened, update the external `silo` repo to follow the current `hashall` qB helper/cache contract.
   - Treat this as separate from required migration execution work in this repo.

## Immediate Checklist

1. The `West Wing S07` cross-device `REUSE` pilot is now proven end-to-end:
   - offline verify passed for all three siblings
   - `rehome_reconcile_only` fired on rerun
   - qB stayed `stalledUP 100%` on `/pool/media/...`
   - catalog now points all three torrents at device `141` / target save paths
2. The `Megalopolis.2024.REPACK...` live `MOVE` pilot is now green:
   - report dir: `~/.logs/hashall/reports/rehome-relocate/20260311-173250-692ffa9407a574f4/`
   - copy to `/pool/media/...` completed
   - all three sibling views offline-verified `exact_tree`
   - validate passed after explicit `qb_stop phase=validate reason=prepare_for_patch`
   - qB ended `stalledUP 100%` on:
     - `/pool/media/torrents/seeding/cross-seed/Aither (API)`
     - `/pool/media/torrents/seeding/cross-seed/PrivateHD`
     - `/pool/media/torrents/seeding/_rehome-unique/6befda30838dbbee444769501bece3fdc5848a3e`
   - source cleanup remained deferred, manual, and explicit
3. First mixed-batch scale-up is now proven:
   - `mixed4` exposed a real bad REUSE candidate:
     - `Shining.Girls...` (`3` torrents) failed destination offline verify as `partial_match`
     - it is now an explicit exclusion, not a planner bug
   - curated replacement batch:
     - `out/rehome-plan-pool-data-to-media-mixed3-no-shining.json`
   - successful results:
     - `Longlegs...` REUSE completed via `rehome_reconcile_subset` with `8` good rows reconciled and `1` skipped `dest_missing` row left alone
     - `Brave.New.World.US.S01...` MOVE completed successfully
     - `Greenland.2020.Repack...` MOVE completed successfully
   - qB now shows all affected `Brave New World` and `Greenland` torrents as `stalledUP 100%` on `/pool/media/...`
4. Preserve the narrow ownership fix pattern for future sidecar fetches: if qB can read media files but cannot create missing sidecars, check for `root:root 755` payload directories first.
5. The next curated live batch is now also green:
   - plan: `out/rehome-plan-pool-data-to-media-next4c.json`
   - successful payload groups:
     - `Brave.New.World.US.S01...`
     - `Greenland.2020.Repack...`
     - `Azrael...`
     - `Stranger.Things.S03...`
   - shared post-apply summary:
     - `25 torrent(s) checked, all in acceptable state`
6. Current carve-outs from the clean `MOVE` lane:
   - `Magic.City.S01...`
     - failed after copy with `Target file count mismatch after move`
     - observed runtime stats: source `8 files / 106474639951 bytes`, target `9 files / 110028001871 bytes`
     - treat as dirty-target/preexisting-content case until code rejects this earlier
   - `Wilding.2023...`
     - copy completed and target verify passed
     - offline verify then stalled at `checking_files 0.00%` for `15m+`
     - treat as verifier-stall case until code adds stagnation detection
7. Audit conclusion from the recent failures:
  - no evidence of a broad fastresume patch corruption bug
  - the remaining code gaps are:
    - preexisting-target rejection/reporting for `MOVE`
    - offline-verify stagnation detection
    - better lock-holder diagnostics on `~/.hashall/rehome.lock`
9. Remaining follow-up backlog after the 2026-03-12 cleanup + reconcile wave:
   - only `1` tagged group remains in follow-up
   - payload `a1041c6049c66abe...` (`Longlegs...`) is still a real live failure because one member remains on `/pool/data/...` and reports `save_path_mismatch`
10. Remaining live remediation gap:
   - add a direct reconcile/remediate path for stale sibling-root drift groups so the `6` old `/data == /stash` hashes can be repointed onto their surviving `/pool/media/...` payload groups without another copy
