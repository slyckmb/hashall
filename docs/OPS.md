# OPS — Opportunities and Observations

Numbered items noticed during work. Not yet scheduled.
Lead cherry-picks clusters into job plans.

**Status values:** `open` | `in-job:<JNN>` | `closed:<JNN>`
**Types:** `bug` | `ux` | `reliability` | `perf` | `test` | `doc`

---

## Open

| ID | Type | Title | Observed |
|----|------|-------|----------|
| OP-01 | doc | Document `save-path-repair` operation in RUNBOOK (no safe command sequence exists) | 2026-05-20 |
| OP-02 | doc | Document canonical tree repair execution protocol in RUNBOOK (taxonomy exists, steps don't) | 2026-05-20 |
| OP-03 | doc | Add external repo dependency map to AGENTS.md (traktor registry, rt-tracker-manual-report, qbm config, cross-seed config, sys/docker repo) | 2026-05-20 |
| OP-04 | bug | `save_path_inference.py` SYSTEM_TAGS hardcoded — new tracker names added without consulting registry | 2026-05-20 |
| OP-05 | bug | `save-path-repair` patches qB fastresume when 0 files moved → `missingFiles` on restart | 2026-05-20 |
| OP-06 | bug | `save-path-repair` ambiguous prefix match in `_resolve_full_hash()` — short hash matches multiple torrents, picks wrong item | 2026-05-20 |
| OP-07 | doc | Fix SPRINT.md slice 12a description — Class 4 repairs had 3 groups (A=data movement, B=empty deletion, C=nested staging), not uniform repoint | 2026-05-20 |
| OP-08 | doc | Slice 12b policy review — "legacy prefix removal" description is stale; REQUIREMENTS.md §4.4 confirms cross-seed/<tracker>/ IS canonical. Superseded unless operator reauthorizes with revised transform. | 2026-05-26 |
| OP-15 | doc | Audit all cross-seed folder references across repo (src/, docs/, scripts/, Makefile, SPRINT.md, RUNBOOK.md, AGENTS.md) — ensure all are aligned with §4.4 policy: cross-seed/<prowlarr-tracker-name>/ is canonical; no "prefix removal" framing anywhere | 2026-06-17 |
| OP-16 | bug | `save_path_inference.py` line 223 policy inversion — `derive_policy_base_save_path` returns bare `<tracker>/` for cross-seed category items instead of `cross-seed/<tracker>/`; ~2000 items mutated to wrong paths by rogue code; fix: add `cross-seed/` prefix on line 223 + update 3 affected tests | 2026-06-17 |
| OP-17 | reliability | Migrate ~2000 cross-seed items from bare `<tracker>/` back to `cross-seed/<tracker>/` — consequence of OP-16 rogue mutation; requires OP-16 code fix first, then 4-gate validated migration (rename dir + repoint RT + repoint qB per item) | 2026-06-17 |
| OP-19 | bug | Spurious subdirectory around bare single-file torrents — RT creates a release-name folder even when the torrent defines no internal folder; canonical form is `<root>/<cat>/<filename>` with no subdirectory; scope unknown, needs audit | 2026-06-17 |
| ~~OP-20~~ | ~~bug~~ | ~~English Grammar Boot Camp stoppedDL investigation~~ | ~~closed:j24~~ |
| ~~OP-21~~ | ~~reliability~~ | ~~Repair English Grammar Boot Camp qB to stoppedUP~~ | ~~closed:j26~~ |
| ~~OP-22~~ | ~~bug~~ | ~~Audit 34 j22-touched items for FNF bypass damage~~ | ~~closed:j25~~ |
| OP-23 | reliability | 12 conflict items need operator resolution — both source and target paths exist with different content; excluded from lane1 automation; need decision: keep source, keep target, or merge; blocked until decision made | 2026-06-20 |
| OP-24 | reliability | 4 anomalous items need manual review — dangerous source paths excluded from all automation: seeding root itself, cross-seed dir root, and 2 content subdirs 2 levels deep (FileList.io/Beetlejuice, FileList.io/UEFA); require human inspection before any path repair | 2026-06-20 |
| OP-25 | reliability | Editable install must be pinned to CR worktree before any mutation run — `pip show hashall` currently shows `~/.venvs/hashall` (stale); stale install was root cause of j18 pilot failure (115 stoppedDL); add explicit `pip install -e <worktree>` gate to all mutation pre-flights | 2026-06-20 |
| OP-26 | reliability | Lane 2 execution strategy decision needed — 1030 ROOT_DRIFT + 2361 compound drift items require STASH→POOL cross-device copy; no executor exists yet; 19.4 TB unique data vs ~3.1 TB free on pool; full migration not feasible without storage expansion or phased approach | 2026-06-20 |
| ~~OP-27~~ | ~~bug~~ | ~~j20 MISSING_DATA false-negative audit~~ | ~~closed:j25~~ |
| ~~OP-28~~ | ~~reliability~~ | ~~11 missingFiles after qB restart — 4 patterns: double-nested (4), deadpool-hardlink (1), FileList.io root (2), stash-pointer (2), displaced (2); all set_location+recheck; missingFiles: 11→0~~ | ~~closed:j27~~ |
| OP-18 | reliability | EXPLORE: unified single-pass placement+path tool for all ~4k RT items — two broken tools (rehome planner: WHERE stash/pool; save_path_inference: WHAT PATH category formula) have each caused mass damage when run independently; explore building one validated tool that resolves both dimensions per item (placement policy → seeding-root, category → path formula → full target path, diff vs actual, migrate if needed, sync qB); NO further mutations from rehome or save_path_inference until this exploration is complete and 4-gate validated | 2026-06-17 |
| OP-29 | reliability | 82 RT stopped items — ALL were seeding before agent damage; ALL require investigation and repair (not skip); policy: all repair code must go through 4-gate validation before mutations resume. Groups: (A) 67 Group A items need check_hash+start; (B) 3 near-complete items (River Monsters, Dexter S02 720p, Transformers) — were seeding, need root cause + repair path; (C) 6 missing-dir items (Beetlejuice OP-24, UEFA OP-24, English Teacher, M3GAN, West Wing S02, Novitiate) — paths broken by agent, need locate+repoint; (D) 5 720p items (Chicago Fire S12 ×3, Dexter S07, Dexter S02 720p) — were seeding before damage, need repair to seeding state then evaluate keep/remove; (E) Group A items that fail hash-check (file naming mismatch from cross-seed daemon) — need locate correct files or correct torrent | 2026-06-24 |
| OP-34 | reliability | 3 near-complete stopped items (River Monsters S07, Dexter S02 720p, Transformers) — were seeding before agent damage; `d.complete=0` but completed_bytes≥99%; investigate what caused the damage, locate source files on disk, determine if files are intact or partially corrupted, then repair path to seeding; 4-gate required before any mutation | 2026-06-25 |
| OP-35 | reliability | 5 stopped 720p items (Chicago.Fire.S12 ×3, Dexter.S07, Dexter.S02 720p) — were seeding before agent damage; investigate root cause of each (lane1 repoint? leeching?); repair to seeding state; then evaluate per-item keep-or-remove per quality policy; 4-gate required before any mutation | 2026-06-25 |
| OP-36 | reliability | Group A items that fail hash-check (file naming mismatch): cross-seed daemon injected torrents whose internal filenames differ from the hardlinked source files on disk (e.g. How.Its.Made.S17 — short vs long episode title naming); gate 3 pilot found `complete=0` after hash-check; investigate scope of naming-mismatch items in Group A (68 items), identify correct file locations or correct torrent versions, repair; 4-gate required before any mutation | 2026-06-25 |
| ~~OP-30~~ | ~~bug~~ | ~~`rt_apply_directory_repoint(..., restart=True)` unconditional `d.start` — fixed: `check_before_start` param added; `rt_recheck_torrent` fixed; `lane1_execute.py` updated; 5 new tests; see `docs/RCCA-RT-LEECHING-INCIDENT.md`~~ | ~~closed:j28~~ |
| OP-31 | reliability | All mutation callers of `rt_apply_directory_repoint` must use `check_before_start=True` for any item that may be `d.complete=0` (all cross-seed items, all injected torrents); callers: `lane1_execute.py` (237, 515), `save_path_repair.py` (608), `hitchhiker_split.py` (320), `save_path_recovery.py` (446), `nested_folder_repair.py` (520), `cli.py` (3989, 4043, 5574, 6214); blocked on OP-30 code fix | 2026-06-24 |
| OP-33 | reliability | Snowfall S05 pool cross-seed copy damaged by leeching incident: `/pool/media/torrents/seeding/cross-seed/TorrentLeech/Snowfall.2017.S05.../` has E01 downloaded (nlinks=1, 3.3 GB) + E02-E10 as 0-byte stubs; stash copy (`/stash/media/torrents/seeding/cross-seed/TorrentLeech/` and `rehome/`) intact (nlinks=11); RT item 108E4C39B064 will fail hash-check (d.complete=0) and stay stopped; investigate: remove pool copy, repoint RT to stash path | 2026-06-25 |
| OP-32 | bug | Lead accidentally merged CR branch into `main` twice (commits 36157df, 235426a) by running `git -C <flat-j28-path> merge` — flat path `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j28` falls under main repo, not a registered worktree; main reset to `1879b35`; fix: verify `git -C <path> branch --show-current` before any merge/reset; never use flat `__jNN` paths for git ops; always use registered nested worktree path; see `docs/RCCA-MAIN-MERGE-INCIDENT.md` | 2026-06-25 |
| OP-37 | bug | `rt_check_and_conditionally_start()` leaves large torrents at stoppedUL after hash-check completes — poll_secs=180.0 default times out for multi-episode seasons (>180s hash time); function returns `complete=-1, started=False` and exits; torrent finishes hashing minutes later at `d.complete=1` but stays stopped (stoppedUL) with no caller to trigger `d.start`; fix: (a) after poll timeout, do a final `d.complete` read before returning — if already 1, start it; or (b) raise default poll_secs to 600s; 24 items left stoppedUL in j28 Gate 4 batch, recovered manually | 2026-06-25 |
| OP-09 | reliability | Execute slice 12c — 10 `cross-seed/<hash>/` items: resolve tracker → rename dir → repoint RT+qB | 2026-05-26 |
| OP-10 | reliability | RT container restart to activate `event.download.hash_done` hook (implemented in rtorrent.rc, not yet live) | 2026-05-20 |
| OP-11 | doc | Create healthchecks.io monitor for "RT qB mirror sync apply" timer — UUID blank in healthchecks.json | 2026-05-20 |
| OP-12 | doc | Migrate qB cache daemon from hashall → silo (3 files, update imports, delete hashall copies; carry zombie fix from b6c3f8d) | 2026-04-21 |
| OP-13 | doc | Rename `TRK_WARN_SCRIPT` → `TRACKER_ISSUE_SCRIPT` in Makefile after docker repo rename; add one-cycle compatibility alias | 2026-06-16 |
| OP-14 | reliability | Merge hashall CR branch to main — j05 (--repair) and j06 (--escalating-search) Makefile fixes pending | 2026-06-16 |

---

## In-Job

| ID | Type | Title | Job |
|----|------|-------|-----|
| | | | |

---

## Closed

| ID | Type | Title | Closed |
|----|------|-------|--------|
| OP-C1 | bug | `auth_err` + escalation: plan_action never checked escalation hits → report_only | j03 (v1.9.6) |
| OP-C2 | bug | `deleted/HOLD` + escalation: hold_wait_for_ep returned report_only without checking escalation | j03 (v1.9.6) |
| OP-C3 | bug | `candidate_replace_individual` execution block re-read ep_rep from scratch — erase without reload | j03 (v1.9.6) |
| OP-C4 | bug | `trk-warn-replace-individual` Makefile target missing `--repair` flag — auth_err bucket blocked | j05 |
| OP-C5 | bug | `trk-warn-replace-individual` Makefile target missing `--escalating-search` flag | j06 |
| OP-20 | bug | English Grammar Boot Camp stoppedDL investigation — pre-j23 FNF bypass during j17/j18 pilot; PDF landed at wrong dir level; no new bug needed; see `docs/RCCA-GRAMMAR-BREAK.md` | j24 |
| OP-21 | reliability | Repair English Grammar Boot Camp qB to stoppedUP — hardlinked PDF to content_path level; recheck → stoppedUP; stoppedDL = 5 (pre-existing only) | j26 |
| OP-22 | bug | Audit 34 j22-touched items for FNF bypass damage — all stoppedUP confirmed; only Grammar Boot Camp was damaged (pre-j23 pilot); no j22 damage | j25 |
| OP-27 | bug | j20 MISSING_DATA false-negative audit — 27/28 recovered; Grammar Boot Camp only outlier (confirmed j24 root cause) | j25 |

---

## How to use

**Log a new op during work:**
Add a row to the Open table. Assign the next OP-NN id. Keep title to one line.

**Schedule ops into a job:**
Move rows from Open → In-Job, set `Job: JNN`. Lead includes them in the job plan.

**Close an op:**
Move to Closed when the fix is merged. Record which job closed it.

**Cherry-picking clusters:**
Look for ops that share a file, a subsystem, or a risk level.
Two or three related open ops often form a clean single-commit job.
