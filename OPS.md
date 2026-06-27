# OPS — Opportunities and Observations

Numbered items noticed during work. Not yet scheduled.
Lead cherry-picks clusters into job plans.

**Status values:** `open` | `in-job:<JNN>` | `closed:<JNN>`
**Types:** `bug` | `ux` | `reliability` | `perf` | `test` | `doc`

---

## Open
| OP-44 | bug | `chatrap job --name` consumes job counter even on failed/rolled-back attempts — during j33 setup, two prior attempts (intended j31, j32) were rolled back by chatrap but their job numbers were not reclaimed; actual repair job landed at j33 instead of j31; job numbers are non-contiguous in git log; fix: chatrap job rollback should decrement the job counter, or the counter should be derived from the highest successfully merged job rather than a monotonic increment *(merged: OP-49 evidence: 2026-06-26)* | 2026-06-25 |

| ID | Type | Title | Observed |
|----|------|-------|----------|

| OP-09 | reliability | Execute slice 12c — 10 `cross-seed/<hash>/` items: resolve tracker → rename dir → repoint RT+qB | 2026-05-26 |
| OP-10 | reliability | RT container restart to activate `event.download.hash_done` hook (implemented in rtorrent.rc, not yet live) | 2026-05-20 |
| OP-12 | doc | Migrate qB cache daemon from hashall → silo (3 files, update imports, delete hashall copies; carry zombie fix from b6c3f8d) | 2026-04-21 |
| OP-14 | reliability | Merge hashall CR branch to main — j05 (--repair) and j06 (--escalating-search) Makefile fixes pending | 2026-06-16 |
| OP-15 | doc | Audit all cross-seed folder references across repo (src/, docs/, scripts/, Makefile, SPRINT.md, RUNBOOK.md, AGENTS.md) — ensure all are aligned with §4.4 policy: cross-seed/<prowlarr-tracker-name>/ is canonical; no "prefix removal" framing anywhere | 2026-06-17 |

| OP-17 | reliability | Migrate ~2000 cross-seed items from bare `<tracker>/` back to `cross-seed/<tracker>/` — consequence of OP-16 rogue mutation; requires OP-16 code fix first, then 4-gate validated migration (rename dir + repoint RT + repoint qB per item) | 2026-06-17 |
| OP-50 | reliability | Build `hashall canonicalize` unified tool — wire `DemotionPlanner._detect_external_consumers` (placement) + `infer_canonical_save_path` (path formula) into a single orchestrator (`src/hashall/canonicalize.py`) that cross-validates both dimensions per torrent, emits structured drift verdicts (placement_drift, path_structure_drift), generates repair plans consumable by lane1_execute and rehome apply, and exposes `hashall canonicalize <hash>` + `hashall canonicalize-batch` CLI; mutation block on rehome/save_path_inference lifted only after pilot verification passes (false positive rate ≤ 5%) | 2026-06-27 |
| OP-19 | bug | Spurious subdirectory around bare single-file torrents — RT creates a release-name folder even when the torrent defines no internal folder; canonical form is `<root>/<cat>/<filename>` with no subdirectory; scope unknown, needs audit | 2026-06-17 |
| OP-23 | reliability | 12 conflict items need operator resolution — both source and target paths exist with different content; excluded from lane1 automation; need decision: keep source, keep target, or merge; blocked until decision made | 2026-06-20 |
| OP-24 | reliability | 4 anomalous items need manual review — dangerous source paths excluded from all automation: seeding root itself, cross-seed dir root, and 2 content subdirs 2 levels deep (FileList.io/Beetlejuice, FileList.io/UEFA); require human inspection before any path repair | 2026-06-20 |

| OP-26 | reliability | Lane 2 execution strategy decision needed — 1030 ROOT_DRIFT + 2361 compound drift items require STASH→POOL cross-device copy; no executor exists yet; 19.4 TB unique data vs ~3.1 TB free on pool; full migration not feasible without storage expansion or phased approach | 2026-06-20 |
| OP-42 | bug | `chatrap lead after-job` Steps A/B skipped every run because opencode agent task-logs are written to the opencode run log (`<job-wt>/.agent/logs/<job>/<job>-tNN-opencode.log`) but NOT to the chatrap artifact directory (`<job-wt>/.agent/artifacts/.../`); after-job scans only the artifact dir so task-log friction, ops_closed entries, and file-change reports are never surfaced to the lead; `ops_closed=` lines in task-logs are silently ignored, preventing automatic OP closure; fix: after-job should also scan opencode logs in `.agent/logs/` for task-log blocks, OR the dispatch wrapper should copy/mirror the task-log block into the artifact dir on agent completion | 2026-06-25 |
| OP-43 | reliability | 4 items seeding at 99.9x% with complete=0 after j33 repair — River Monsters S07 (127C3834, 99.92%), Transformers (96D896CA, 99.99%), Dexter.S02.720p 245F2BCE (99.97%), Dexter.S07.720p E36553B1 (99.96%). Root cause: nested subfolder content was missing last piece of E01 episode + .nfo file (zero-byte in nested = skip_nested_also_zero); hardlink repair applied for all other pieces; items are seeding and downloading missing pieces from peers. Monitor: if any remain complete=0 after 48h, locate missing E01 data on disk and investigate | 2026-06-25 |
| OP-45 | reliability | j33 opencode agent ran out-of-scope `d.check_hash` on Diary of Teenage Girl (5CACA88D) — agent included Diary in its hash-check loop despite it not being a target item in the brief; Diary was left at state=0 complete=0 98.42% (2 files genuinely missing, confirmed by hash-check); no new damage (was already broken per OP-36), but agent scope violation confirms agents will act on any stopped torrent visible in RT without explicit filtering; briefs must explicitly state excluded hashes or use --limit with explicit hash list only | 2026-06-25 |
| OP-47 | bug | RCCA: Beetlejuice (E04E524750C999AC) and UEFA (3E82F6F7A3A5ADAE) had RT d.directory pointing to `/pool/media/torrents/seeding/FileList.io/<name>/<name>` — path missing `cross-seed/` prefix, directory did not exist on disk; both stuck state=0 complete=0 (0%); content was actually at `cross-seed/FileList.io/<name>/<name>/` all along; fix applied manually (repoint + hash-check → both now state=1 complete=1). Root cause unknown — need RCCA: (1) identify what process wrote these paths (cross-seed injection? rehome apply? set_location?); (2) inspect cross-seed config save_path for FileList.io tracker — should be `cross-seed/FileList.io/` not `FileList.io/`; (3) check if other FileList.io cross-seed items are similarly broken; (4) add pre-repoint path-exists validation to `rt_apply_directory_repoint()` so broken paths are caught before being written to session; (5) add post-inject RT path audit step to cross-seed/rehome workflows | 2026-06-26 |

---

## In-Job

| ID | Type | Title | Job |
|----|------|-------|-----|
| | | | |

---

## Closed
| OP-49 | superseded | superseded:OP-44 | closed:auto-combine |

| ID | Type | Title | Closed |
|----|------|-------|--------|
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
| OP-04 | bug | Fixed in j37: _load_tracker_registry_keys() added to save_path_inference.py; "speed" alias removed from SYSTEM_TAGS; tag selection now prefers canonical registry keys. Version → 0.8.68. | j37 |
| OP-05 | bug | Fixed: should_apply guard skips fastresume patch when files_moved=0 and qB not at staging dir. | j09 |
| OP-06 | bug | Fixed in j09/j10: _resolve_full_hash() raises ValueError on ambiguous prefix match. | j10 |
| OP-16 | bug | Fixed in j14: derive_policy_base_save_path() returns cross-seed/{provider} correctly; 3 tests updated. | j14 |
| OP-01 | doc | `save-path-repair` fully documented in RUNBOOK.md (safe command sequence, per-item steps, guards) | j40-t01 |
| OP-02 | doc | Canonical tree repair execution protocol documented in RUNBOOK.md (5-class table, prerequisites, qB repoint rule, all class steps) | j40-t01 |
| OP-03 | doc | External repo dependency map added to AGENTS.md | j40-t02 |
| OP-07 | doc | SPRINT.md slice 12a updated with 3-group breakdown | j40-t03 |
| OP-08 | doc | Superseded — REQUIREMENTS.md §4.4 establishes canonical policy; 12b is historical record | j40-t03 |

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
