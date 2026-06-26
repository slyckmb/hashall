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
| OP-29 | reliability | **UPDATED post-j30/j33** — 80→8 truly stopped (state=0). j30 removed 4 leeching-started (Coursera, Domestika ×2, Priscilla BLURAY); j33 repaired 8 stub items (all now state=1, 4 at 99.9x% completing from peers). Remaining 8 stopped: (B) path-broken 5 — Novitiate (RT→pool torrentleech/, content at stash/darkpeers/), M3GAN (RT→pool/movies/ root), West.Wing.S02 71CDD51 (RT→cleaned-up rehome staging path), English.Teacher (RT→pool/tv/ nonexistent), Beetlejuice+UEFA (OP-24 anomalous paths); (C) partial content 2 — EGB Boot Camp 4BF5C39 (24 mp3 stubs, no source), Diary of Teenage Girl 5CACA88D (2 files missing, state=0 98.42% confirmed j33); root cause all groups: j22 leeching incident + prior lane1/rehome path mutations | 2026-06-25 |
| OP-36 | reliability | **UPDATED post-j33**: (1) EGB Boot Camp (4BF5C39): 24 MP3 stubs, no source — zero-byte in nested, cannot hardlink; likely remove. (2) Diary of Teenage Girl (5CACA88D): hash-check confirmed 98.42% complete (2 files missing — .nfo 0/1 chunk + Sample.mkv 0/1 chunk — zero-byte in nested); state=0 complete=0; 2 files genuinely missing from all known locations; options: remove torrent or locate source for missing files. | 2026-06-25 |
| ~~OP-30~~ | ~~bug~~ | ~~`rt_apply_directory_repoint(..., restart=True)` unconditional `d.start` — fixed: `check_before_start` param added; `rt_recheck_torrent` fixed; `lane1_execute.py` updated; 5 new tests; see `docs/RCCA-RT-LEECHING-INCIDENT.md`~~ | ~~closed:j28~~ |
| ~~OP-31~~ | ~~reliability~~ | ~~All mutation callers of `rt_apply_directory_repoint` must use `check_before_start=True`; all 8 callers updated in j29~~ | ~~closed:j29~~ |
| ~~OP-33~~ | ~~reliability~~ | ~~Snowfall S05 pool copy damaged — E01 downloaded (nlinks=1) + E02-E10 zero stubs; j28 batch repair hardlinked stubs from nested; hash-check passed complete=1; item now seeding; E01 downloaded copy verified correct by hash; no repoint needed~~ | ~~closed:j28~~ |
| OP-32 | bug | Lead accidentally merged CR branch into `main` twice (commits 36157df, 235426a) by running `git -C <flat-j28-path> merge` — flat path `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j28` falls under main repo, not a registered worktree; main reset to `1879b35`; fix: verify `git -C <path> branch --show-current` before any merge/reset; never use flat `__jNN` paths for git ops; always use registered nested worktree path; see `docs/RCCA-MAIN-MERGE-INCIDENT.md` | 2026-06-25 |
| ~~OP-37~~ | ~~bug~~ | ~~`rt_check_and_conditionally_start()` poll timeout — added final `d.complete` read after timeout; if complete=1 start torrent; fixed in j29~~ | ~~closed:j29~~ |
| OP-39 | reliability | 3 items need path repoint (per-item RCCA confirmed): (1) Novitiate — RT→`/pool/media/torrents/seeding/torrentleech/...` (wrong case, wrong pool); content at `/stash/media/torrents/seeding/darkpeers/Novitiate...mkv` (nlinks=?); repoint to stash canonical; (2) M3GAN.2.0.2025 — RT→`/pool/media/torrents/seeding/movies` (category root, pool doesn't have this dir); content at `/stash/media/torrents/seeding/movies/M3GAN...mkv` (nlinks=11, 30.6 GB); repoint to stash movies/; (3) West.Wing.S02 (71CDD51) — RT→rehome staging path cleaned up; other S02 copies seeding fine; locate S02 content and repoint; root cause all 3: prior lane1/rehome mutations left RT pointing to stale/wrong paths | 2026-06-25 |
| OP-40 | reliability | 2 items need path investigation (parent dirs missing entirely): (1) English.Teacher.S01 — RT→`/pool/media/torrents/seeding/tv/...` (pool has no tv/ dir); locate actual files; (2) Beetlejuice and UEFA — OP-24 anomalous double-nested FileList.io paths; content not found in stash FileList.io; require human inspection before any repair | 2026-06-25 |
| OP-42 | bug | `chatrap lead after-job` Steps A/B skipped every run because opencode agent task-logs are written to the opencode run log (`<job-wt>/.agent/logs/<job>/<job>-tNN-opencode.log`) but NOT to the chatrap artifact directory (`<job-wt>/.agent/artifacts/.../`); after-job scans only the artifact dir so task-log friction, ops_closed entries, and file-change reports are never surfaced to the lead; `ops_closed=` lines in task-logs are silently ignored, preventing automatic OP closure; fix: after-job should also scan opencode logs in `.agent/logs/` for task-log blocks, OR the dispatch wrapper should copy/mirror the task-log block into the artifact dir on agent completion | 2026-06-25 |
| OP-43 | reliability | 4 items seeding at 99.9x% with complete=0 after j33 repair — River Monsters S07 (127C3834, 99.92%), Transformers (96D896CA, 99.99%), Dexter.S02.720p 245F2BCE (99.97%), Dexter.S07.720p E36553B1 (99.96%). Root cause: nested subfolder content was missing last piece of E01 episode + .nfo file (zero-byte in nested = skip_nested_also_zero); hardlink repair applied for all other pieces; items are seeding and downloading missing pieces from peers. Monitor: if any remain complete=0 after 48h, locate missing E01 data on disk and investigate | 2026-06-25 |
| OP-44 | bug | `chatrap job --name` consumes job counter even on failed/rolled-back attempts — during j33 setup, two prior attempts (intended j31, j32) were rolled back by chatrap but their job numbers were not reclaimed; actual repair job landed at j33 instead of j31; job numbers are non-contiguous in git log; fix: chatrap job rollback should decrement the job counter, or the counter should be derived from the highest successfully merged job rather than a monotonic increment | 2026-06-25 |
| OP-45 | reliability | j33 opencode agent ran out-of-scope `d.check_hash` on Diary of Teenage Girl (5CACA88D) — agent included Diary in its hash-check loop despite it not being a target item in the brief; Diary was left at state=0 complete=0 98.42% (2 files genuinely missing, confirmed by hash-check); no new damage (was already broken per OP-36), but agent scope violation confirms agents will act on any stopped torrent visible in RT without explicit filtering; briefs must explicitly state excluded hashes or use --limit with explicit hash list only | 2026-06-25 |

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
| OP-39 | reliability | Repoint M3GAN, Novitiate, West.Wing.S02 to correct content paths | j34 |
| OP-40 | reliability | Repoint English.Teacher.S01; Beetlejuice+UEFA human inspection required | j34 |
| OP-36 | reliability | Partial-content triage: EGB Boot Camp + Diary of Teenage Girl — erase + delete nlinks=1 | j35 |

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
| OP-41 | reliability | 4 course/BLURAY items removed from RT and partial download data deleted — erased DB1175F8, 247303F4, F8C32150, CFE048E5 from RT; deleted nlinks=1 partial data from disk. Injected by j22 leeching incident, never in seeding inventory. | j30 |
| OP-34 | reliability | River Monsters S07 (127C3834) + Transformers (96D896CA) repaired via repair_cross_seed_nested_stubs.py --execute --hash; hash-checked and started; seeding at 99.92%/99.99% (missing .nfo + last chunk of E01 — zero-byte in nested, will complete from peers). | j33 |
| OP-35 | reliability | 6 720p items repaired via repair script per-hash — Chicago.Fire.S12.720p ×3 (1FEB6EDA, 39378378, 40A1D9DC) seeding 100%; Dexter.S02.720p ×2 (E56E8C57 100%, 245F2BCE 99.97%) + Dexter.S07.720p (E36553B1 99.96%) seeding; .nfo + last E01 chunk missing for 3 items (will complete from peers). Quality policy evaluation deferred per plan. | j33 |
| OP-38 | bug | 9 missed batch items repaired individually via --hash --execute: all 8 confirmed in RT started (127C3834, 96D896CA, 1FEB6EDA, 39378378, 40A1D9DC, E56E8C57, 245F2BCE, E36553B1). Root cause still unknown (batch scan race/cache issue); workaround applied successfully. | j33 |
| OP-31 | reliability | All mutation callers of `rt_apply_directory_repoint` updated to use `check_before_start=True` — all 8 callers (lane1_execute.py ×2, save_path_repair.py, hitchhiker_split.py, save_path_recovery.py, nested_folder_repair.py, cli.py ×4); after-job A/B skipped (OP-42) so closure recorded here. | j29 |
| OP-37 | bug | `rt_check_and_conditionally_start()` final `d.complete` read after poll timeout — if complete=1, start torrent; prevents stoppedUL stalls on large multi-episode seasons; fixed in j29; after-job A/B skipped (OP-42) so closure recorded here. | j29 |

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
