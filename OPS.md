# OPS — Opportunities and Observations

Numbered items noticed during work. Not yet scheduled.
Lead cherry-picks clusters into job plans.

**Status values:** `open` | `in-job:<JNN>` | `closed:<JNN>`
**Types:** `bug` | `ux` | `reliability` | `perf` | `test` | `doc`

---

## Open

| ID | Type | Title | Observed |
|----|------|-------|----------|
_(all OPs are slotted or closed — see In-Job/Closed below)_



_(all other OPs are slotted — see In-Job below)_

---

## In-Job

| ID | Type | Title | Job |
| OP-09 | reliability | Execute slice 12c — 10 `cross-seed/<hash>/` items: resolve tracker → rename dir → repoint RT+qB | j39 |
| OP-15 | doc | Audit all cross-seed folder references across repo (src/, docs/, scripts/, Makefile, SPRINT.md, RUNBOOK.md, AGENTS.md) — ensure all are aligned with §4.4 policy: cross-seed/<prowlarr-tracker-name>/ is canonical; no "prefix removal" framing anywhere | j39 |
| OP-17 | reliability | Migrate ~2000 cross-seed items from bare `<tracker>/` back to `cross-seed/<tracker>/` — consequence of OP-16 rogue mutation; requires OP-16 code fix first, then 4-gate validated migration (rename dir + repoint RT + repoint qB per item) | j39 |
| OP-19 | bug | Spurious subdirectory around bare single-file torrents — RT creates a release-name folder even when the torrent defines no internal folder; canonical form is `<root>/<cat>/<filename>` with no subdirectory; scope unknown, needs audit | j39 |
| OP-24 | reliability | 4 anomalous items need manual review — dangerous source paths excluded from all automation: seeding root itself, cross-seed dir root, and 2 content subdirs 2 levels deep (FileList.io/Beetlejuice, FileList.io/UEFA); require human inspection before any path repair | j39 |
| OP-47 | bug | RCCA: Beetlejuice (E04E524750C999AC) and UEFA (3E82F6F7A3A5ADAE) had RT d.directory pointing to `/pool/media/torrents/seeding/FileList.io/<name>/<name>` — path missing `cross-seed/` prefix, directory did not exist on disk; both stuck state=0 complete=0 (0%); content was actually at `cross-seed/FileList.io/<name>/<name>/` all along; fix applied manually (repoint + hash-check → both now state=1 complete=1). Root cause unknown — need RCCA: (1) identify what process wrote these paths (cross-seed injection? rehome apply? set_location?); (2) inspect cross-seed config save_path for FileList.io tracker — should be `cross-seed/FileList.io/` not `FileList.io/`; (3) check if other FileList.io cross-seed items are similarly broken; (4) add pre-repoint path-exists validation to `rt_apply_directory_repoint()` so broken paths are caught before being written to session; (5) add post-inject RT path audit step to cross-seed/rehome workflows | j39 |
| OP-23 | reliability | 12 conflict items need operator resolution — both source and target paths exist with different content; excluded from lane1 automation; need decision: keep source, keep target, or merge; blocked until decision made | j42 |
| OP-26 | reliability | Lane 2 execution strategy decision needed — 1030 ROOT_DRIFT + 2361 compound drift items require STASH→POOL cross-device copy; no executor exists yet; 19.4 TB unique data vs ~3.1 TB free on pool; full migration not feasible without storage expansion or phased approach | j42 |
| OP-10 | reliability | RT container restart to activate `event.download.hash_done` hook (implemented in rtorrent.rc, not yet live) | j43 |
| OP-12 | doc | Migrate qB cache daemon from hashall → silo (3 files, update imports, delete hashall copies; carry zombie fix from b6c3f8d) | j43 |
| OP-42 | bug | `chatrap lead after-job` Steps A/B skipped every run because opencode agent task-logs are written to the opencode run log (`<job-wt>/.agent/logs/<job>/<job>-tNN-opencode.log`) but NOT to the chatrap artifact directory (`<job-wt>/.agent/artifacts/.../`); after-job scans only the artifact dir so task-log friction, ops_closed entries, and file-change reports are never surfaced to the lead; `ops_closed=` lines in task-logs are silently ignored, preventing automatic OP closure; fix: after-job should also scan opencode logs in `.agent/logs/` for task-log blocks, OR the dispatch wrapper should copy/mirror the task-log block into the artifact dir on agent completion *(j46 additional evidence: lead wrote LOG_DIR to job worktree path instead of CR_WORKTREE per INIT.md Step 3 — all j46 task logs deleted when chatrap job done removed the worktree; secondary failure: flat `.agent/logs/j46/` instead of `.agent/logs/<session-id>/j46/`)* | j44 |
| OP-45 | reliability | j33 opencode agent ran out-of-scope `d.check_hash` on Diary of Teenage Girl (5CACA88D) — agent included Diary in its hash-check loop despite it not being a target item in the brief; Diary was left at state=0 complete=0 98.42% (2 files genuinely missing, confirmed by hash-check); no new damage (was already broken per OP-36), but agent scope violation confirms agents will act on any stopped torrent visible in RT without explicit filtering; briefs must explicitly state excluded hashes or use --limit with explicit hash list only | j44 |
| OP-57 | reliability | Orphan migration must skip files hardlinked to active seeding content — recent orphan offload run (WD6TB) rsync'd files from orphan dir to external filesystem, but some orphan files were hardlinked to actively-seeding torrent content within the same filesystem. Migrating hardlinked orphans to a different filesystem: (a) breaks the inode-level hardlink, (b) duplicates storage since both orphan copy and seeding copy exist independently, (c) inflates transfer size vs `du` estimate (rsync counts each link as separate data). Fix: before migration, scan orphans for inode overlap with active seeding content on the same device; skip orphans where `(inode, device_id)` matches any seeding content file. Only migrate true unique orphans (nlinks=1 or nlinks>1 but all links within orphan dir). **WD6TB cleared and repurposed as spare** — the failed offload data (5.4T partial copy, 0% SHA256) was wiped 2026-07-01. Drive reformatted as ext4 (label: WD6TB_SPARE), mounted at `/mnt/wd6tb`. Available as fallback rsync target (5.2T free). | j50 |
| OP-60 | enhancement | `hashall link analyze --cross-device` uses SHA256 as exclusive cross-device dedup key, but all 4 scanned devices have 100% quick_hash coverage. Add `--quick-hash` mode joining on `(quick_hash, size)` instead of `(sha256, size)` for instant cross-device matching without SHA256 bottleneck. After match, lazily compute full SHA256 only for matched pairs. Scope: ~10 lines in `analyze_cross_device()`, one new flag, alternate SQL path. Observed during orphan dedupe — 425k cross-device matches blocked by SHA256-only constraint. | j50 |
| OP-61 | perf | Pool orphan dedupe via cross-device content matching — 18,645 quick_hash matches (1,599 GB) across stash library, hotspare, and WD6TB; pool/media snapshot destroyed (809 GB freed); pilot SHA256-confirmed deletion (66 GB) executed; SHA256 upgrade scan complete (21,943 files, 19,370 updated, 810G free on pool); ready to delete SHA256-confirmed orphan files, recover ~2.2 TB. Supersedes OP-54 migrate-all approach — dedupe is smarter (delete only what's confirmed safe elsewhere). | j50 |
| OP-63 | reliability | Pool cross-seed item duplicate of stash ARR copy needs rehome (pool→stash) with hardlink payload — Elemental.2023 confirmed on stash (inode 99558, nlink=3: Plex + rTorrent + cross-seed payload) with separate pool duplicate (inode 3265, nlink=2, `~noHL`). Correct fix: rehome 55a3df42 from pool→stash per §5.3 — build unique payload tree on stash for 55a3df42, hardlink ef1071a1's existing inode into it (same device, no cross-filesystem violation), repoint RT, delete pool copy. This is the canonical rehome pattern from REQUIREMENTS.md §1.4/§5.3/§6.3. Also check scope: how many other cross-device payload duplicates exist? Related to OP-58/OP-59 (TorrentDay mirror race). | j50 |
| OP-58 | bug | RT→qB mirror left 2 TorrentDay cross-seed items stalledUP in qB while RT has them stoppedUP — `Cold Case Files 2017 S01` (a98fc34) and `The Bear S04` (acb52ed) are `stalledUP` in qB with state not synced to RT's `stoppedUP`; both have `~rt-mirrored`, `~noHL`, `~share_limit_950.public` tags; seeding from stash `/data/media/torrents/seeding/cross-seed/TorrentDay/` despite `~noHL` tag (should be pool); stalled since ~Jan 2026 (177 days); root cause unknown: `hashall-client-drift` mirror handler may have missed stop signal, or qB share-limit reached (`~share_limit_950`) before client-drift could stop them; fix: investigate mirror flow for share-limit race; stop both in qB and repoint to pool path per `~noHL` | j52 |
| OP-59 | bug | 2 cross-seed TorrentDay items in `PU` (Paused/Uploading) state in rTorrent — same hashes as OP-58 (a98fc34 Cold Case Files 2017 S01, acb52ed The Bear S04); both are 100% complete with `~noHL` tag but stuck in PU instead of stopped or SD; RT UL sidebar shows `stopped: 2` — these are the 2 PU items; root cause unknown; fix: determine what process set PU state, transition both to stopped, and harden whatever workflow touched these to prevent recurrence | j52 |
| OP-62 | bug | 440 qB torrents at `missingFiles` state (0%) — qB save_path points to stale stash paths (`/data/media/torrents/seeding/<tracker>/`) after rehome migration moved data stash→pool but didn't update qB. All have `~noHL` + `~rt-mirrored` tags. Files exist on pool at RT's save_path. 265 single-file (fast fix), 177 multi-file (need dir move). Fix: batch `set_location` from stash path → pool path + recheck. | j51 |
| OP-65 | ux | `hashall link show-plan` output uses "Keep" and "Replace" labels that imply directionality — user/agent interprets this as "orphan becomes canonical, seeding becomes dependent" which is misleading. Hardlinks have no direction: all paths to the same inode are equal. Plan output should clarify that both paths are retained, only the duplicate inode is freed. Replace "Keep" and "Replace" with "Canonical" and "Deduplicated" or add a note explaining hardlink semantics. Affects: `link show-plan`, `link execute --dry-run` output. | j51 |
| OP-14 | reliability | Merge hashall CR branch to main — j05 (--repair) and j06 (--escalating-search) Makefile fixes pending | j45 |

---

## Closed
| OP-49 | superseded | superseded:OP-44 | closed:auto-combine |
| OP-43 | reliability | 4 items seeding at 99.9x% with complete=0 after j33 repair — confirmed normal stalledDL behavior; no action required | closed:no-action |
| OP-44 | superseded | job counter consumed on failed/rolled-back attempts — superseded by OP-49 (evidence: 2026-06-26) | closed:superseded |

| ID | Type | Title | Closed |
|----|------|-------|--------|
| OP-53 | reliability | SHA256 library content anchor — `_Sha256ContentMatcher` added for cross-device content matching; library-dupe flow wired through j48. | j48 |
| OP-55 | bug | 83 blocked Gate 2 false positives — j48 SHA256/library-dupe work made the blocked FP class resolvable. | j48 |
| OP-56 | reliability | qB recheck gap after `set_location` — j48 extended apply/rank flow with explicit recheck handling. | j48 |
| OP-64 | doc | Repo mastery doc audit delivered; AGENT-MASTERY coverage expanded and gaps documented. | j53 |
| OP-11 | doc | config/healthchecks.json stub created; operator must register and fill UUID | j40-t05 |
| OP-13 | doc | TRACKER_ISSUE_SCRIPT alias added to Makefile; TRK_WARN_SCRIPT kept as compat alias | j40-t05 |
| OP-25 | reliability | pip editable install gate added to Makefile mutation targets | j40-t04 |
| OP-C1 | bug | `auth_err` + escalation: plan_action never checked escalation hits → report_only | j03 (v1.9.6) |
| OP-C2 | bug | `deleted/HOLD` + escalation: hold_wait_for_ep returned report_only without checking escalation | j03 (v1.9.6) |
| OP-C3 | bug | `candidate_replace_individual` execution block re-read ep_rep from scratch — erase without reload | j03 (v1.9.6) |
| OP-C4 | bug | `trk-warn-replace-individual` Makefile target missing `--repair` flag — auth_err bucket blocked | j05 |
| OP-C5 | bug | `trk-warn-replace-individual` Makefile target missing `--escalating-search` flag | j06 |
| OP-20 | bug | English Grammar Boot Camp stoppedDL investigation — pre-j23 FNF bypass during j17/j18 pilot; PDF landed at wrong dir level; no new bug needed; see `docs/RCCA-GRAMMAR-BREAK.md` | j24 |
| OP-21 | reliability | Repair English Grammar Boot Camp qB to stoppedUP — hardlinked PDF to content_path level; recheck → stoppedUP; stoppedDL = 5 (pre-existing only) | j26 |
| OP-22 | bug | Audit 34 j22-touched items for FNF bypass damage — all stoppedUP confirmed; only Grammar Boot Camp was damaged (pre-j23 pilot); no j22 damage | j25 |
| OP-27 | bug | j20 MISSING_DATA false-negative audit — 27/28 recovered; Grammar Boot Camp only outlier (confirmed j24 root cause) | j25 |
| OP-28 | reliability | 11 missingFiles after qB restart — 4 patterns: double-nested (4), deadpool-hardlink (1), FileList.io root (2), stash-pointer (2), displaced (2); all set_location+recheck; missingFiles: 11→0 | j27 |
| OP-30 | bug | `rt_apply_directory_repoint(..., restart=True)` unconditional `d.start` — fixed: `check_before_start` param added; `rt_recheck_torrent` fixed; `lane1_execute.py` updated; 5 new tests; see `docs/RCCA-RT-LEECHING-INCIDENT.md` | j28 |
| OP-31 | reliability | All mutation callers of `rt_apply_directory_repoint` updated to use `check_before_start=True` — all 8 callers (lane1_execute.py ×2, save_path_repair.py, hitchhiker_split.py, save_path_recovery.py, nested_folder_repair.py, cli.py ×4); after-job A/B skipped (OP-42) so closure recorded here. | j29 |
| OP-33 | reliability | Snowfall S05 pool copy damaged — E01 downloaded (nlinks=1) + E02-E10 zero stubs; j28 batch repair hardlinked stubs from nested; hash-check passed complete=1; item now seeding; E01 downloaded copy verified correct by hash; no repoint needed | j28 |
| OP-34 | reliability | River Monsters S07 (127C3834) + Transformers (96D896CA) repaired via repair_cross_seed_nested_stubs.py --execute --hash; hash-checked and started; seeding at 99.92%/99.99% (missing .nfo + last chunk of E01 — zero-byte in nested, will complete from peers). | j33 |
| OP-35 | reliability | 6 720p items repaired via repair script per-hash — Chicago.Fire.S12.720p ×3 (1FEB6EDA, 39378378, 40A1D9DC) seeding 100%; Dexter.S02.720p ×2 (E56E8C57 100%, 245F2BCE 99.97%) + Dexter.S07.720p (E36553B1 99.96%) seeding; .nfo + last E01 chunk missing for 3 items (will complete from peers). Quality policy evaluation deferred per plan. | j33 |
| OP-36 | reliability | EGB Boot Camp erased from RT; 24 MP3 stub files (nlinks=1) deleted. Diary of Teenage Girl erased from RT; Sample.mkv (374MB, nlinks=1) + .nfo (nlinks=1) deleted. 26 unshared stub files removed. Main .mkv (nlinks=5) + .srt×4 (nlinks=4) preserved. RT stopped count: 80→2. | j35 |
| OP-37 | bug | `rt_check_and_conditionally_start()` final `d.complete` read after poll timeout — if complete=1, start torrent; prevents stoppedUL stalls on large multi-episode seasons; fixed in j29; after-job A/B skipped (OP-42) so closure recorded here. | j29 |
| OP-38 | bug | 9 missed batch items repaired individually via --hash --execute: all 8 confirmed in RT started (127C3834, 96D896CA, 1FEB6EDA, 39378378, 40A1D9DC, E56E8C57, 245F2BCE, E36553B1). Root cause still unknown (batch scan race/cache issue); workaround applied successfully. | j33 |
| OP-39 | reliability | M3GAN repointed to /data/media/torrents/seeding/movies (30.6GB, state=1 complete=1); Novitiate subfolder created + hardlinked + repointed to /data/.../darkpeers/Novitiate.2017.../; West.Wing.S02 repointed to /data/.../hawke-uno/The.West.Wing.S02... (71GB, 22ep); all seeding. | j34 |
| OP-40 | reliability | English.Teacher.S01 located at stash/PrivateHD/ (nlinks=19, all ep present); repointed to /data/.../PrivateHD/English.Teacher.S01... (7.7GB, state=1 complete=1). Beetlejuice+UEFA remain OP-24 scope (human inspection required, not touched). | j34 |
| OP-41 | reliability | 4 course/BLURAY items removed from RT and partial download data deleted — erased DB1175F8, 247303F4, F8C32150, CFE048E5 from RT; deleted nlinks=1 partial data from disk. Injected by j22 leeching incident, never in seeding inventory. | j30 |
| OP-29 | reliability | 80→0 stopped resolved. Final 2 (Beetlejuice+UEFA) repointed to cross-seed/FileList.io/ + hash-checked 2026-06-26. | manual+j35 |
| OP-32 | bug | RCCA documented in docs/RCCA-MAIN-MERGE-INCIDENT.md; process fix in place. | lead |
| OP-46 | bug | RT Docker path (/stash/media→/data/media) documented in INIT.md; all briefs updated to use /data/ paths. | lead |
| OP-48 | bug | OPS.md migrated from docs/OPS.md to repo root; docs/OPS.md is now a redirect stub; broken refs in BACKLOG.md + AGENT-MASTERY.md fixed; opscan open=32. | lead |
| OP-18 | reliability | Exploration complete — docs/EXPLORE-UNIFIED-TOOL.md produced; split-brain root cause documented; unified `hashall canonicalize` orchestrator design sketched (~730-1340 lines); mutation block on rehome/save_path_inference remains until unified tool is built and 4-gate validated | j41 |
| OP-50 | reliability | canonicalize.py built (j46): src/hashall/canonicalize.py, hashall canonicalize/canonicalize-batch CLI, 6 tests, pilot run 0% FP on fix_placement_only; canonical_seeding_root bug found+fixed; mutation block LIFTED for placement drift detection | j46 |
| OP-04 | bug | Fixed in j37: _load_tracker_registry_keys() added to save_path_inference.py; "speed" alias removed from SYSTEM_TAGS; tag selection now prefers canonical registry keys. Version → 0.8.68. | j37 |
| OP-05 | bug | Fixed: should_apply guard skips fastresume patch when files_moved=0 and qB not at staging dir. | j09 |
| OP-06 | bug | Fixed in j09/j10: _resolve_full_hash() raises ValueError on ambiguous prefix match. | j10 |
| OP-16 | bug | Fixed in j14: derive_policy_base_save_path() returns cross-seed/{provider} correctly; 3 tests updated. | j14 |
| OP-01 | doc | `save-path-repair` fully documented in RUNBOOK.md (safe command sequence, per-item steps, guards) | j40-t01 |
| OP-02 | doc | Canonical tree repair execution protocol documented in RUNBOOK.md (5-class table, prerequisites, qB repoint rule, all class steps) | j40-t01 |
| OP-03 | doc | External repo dependency map added to AGENTS.md | j40-t02 |
| OP-07 | doc | SPRINT.md slice 12a updated with 3-group breakdown | j40-t03 |
| OP-08 | doc | Superseded — REQUIREMENTS.md §4.4 establishes canonical policy; 12b is historical record | j40-t03 |
| OP-51 | reliability | Run 4-gate validated canonicalize repair pass — build hashall canonicalize-apply executor; run Gate 0+1 pre-flight, Gate 2 dry-run manifest, Gate 3 single-item live pilot, Gate 4 gated batch; formalize 4-gate protocol as institutional doc (j47-t01 output); mutation block fully lifted only after Gate 4 batch complete and stoppedDL delta=0 | j47 |
| OP-52 | reliability | qB path update needed after Gate 4 canonicalize batch — `set_location` blocked for cross-device moves (stash→pool); ~465 qB torrents have stale save_path pointing to staged stash locations; items are stoppedUP so no immediate stoppedDL risk, but qB paths need update via rehome/fastresume-edit before any forced recheck; scope: all fix_placement_only items processed in Gate 4 | j47 |
| OP-54 | reliability | pool/media orphan offload blocked — `rsync -a` without `-H` expands internal hardlinks in orphans dir: `du` shows 3.9T (ZFS counts each inode once) but rsync transfers each directory entry independently, inflating actual transfer to ~8T; WD6TB (5.2T usable) filled at 71% (~5.4T copied, rsync died); pool still at 0 bytes free; **superseded by OP-61** — switched to dedupe-based strategy (delete confirmed dupes instead of migrate) | j47 |

---

| OP-66 | reliability | qB stoppedDL pipeline fails to prevent 425 torrents at 0% after setLocation batch, and active downloads re-emerge post-stop. Root cause: `setLocation` + recheck transitions missingFiles→stoppedDL but files at stash paths don't hash-match qB expectations. Existing `bucket→drain→apply→roundloop` pipeline can handle this (offline libtorrent verification before mutation) but was bypassed during ad-hoc repair. Six tooling gaps identified by DSV4 Pro analysis in comms/docs/STOPPEDDL-SOP.md: (1) `pause_mirror_seeders.py` doesn't handle download states; (2) no post-mutation watchdog; (3) Gate 4 protocol missing `pause_mirror_seeders.py` step; (4) drain lacks `--extra-root-file` flag; (5) rollback lacks `--restore-from-backup`; (6) no survive-restart verification. Fix: spec, build, and test the 6 gaps; integrate into a standardized `qb mirror quiesce` procedure enforced after any repair batch. | closed:j54 |

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
