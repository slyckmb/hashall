# Current Sprint

Last updated: 2026-05-26
Status: active

## Active Goal

Keep qBittorrent and rTorrent in sync for all seeded datasets; reduce same-hash
qB/RT save-path drift to zero; preserve placement policy.  Before any further
live rehome operations: complete a full doc review, code-vs-doc cross-check, and
multi-phase dry-run validation gate so that tools are trusted before use.

## Slice Progress

| Slice | Goal | Status |
|---|---|---|
| 0 | Housekeeping: clear lock, payload sync, fresh audit | ✅ done |
| 1 | Alien Resurrection: qB repointed to RT path (pool→stash) | ✅ done |
| 2 | Twin Peaks: qB repointed to RT path (onlyencodes→darkpeers) | ✅ done |
| 3 | **Doc review**: full repo doc audit — gaps, conflicts, consolidation | ✅ done |
| 4 | **Code vs doc**: cross-check all code against docs; plan fixes | ✅ done |
| 5 | **Test gate**: multi-phase walkthrough + dry-runs; pilot all tools; fix errors | ✅ done |
| 6 | Novitiate: pool rehome + client repoint | ✅ done |
| 7 | Top Gun Maverick IMAX: policy decision + action (RT-only) | ✅ done |
| 8 | Code fixes: db-lock on concurrent sync, orphan GC limit | ✅ done |
| 9 | Refresh: run catalog refresh, verify clean audit | ✅ done |
| 10 | Investigate RT→qB mirror watchdog failures (recurring down) | ✅ done |
| 11 | Canonical tree normalization report: script + Makefile target | ✅ done |
| 12a | Class 4 repairs: `_rehome-unique/<hash>/` — staging cleared, 376 dirs deleted | ✅ done |
| 12b | `cross-seed/<tracker>/` legacy prefix removal — ~2125 items: rename dir + repoint both clients | ⏳ pending |
| 12c | Class 1 repairs: `cross-seed/<hash>/` — resolve tracker → rename → repoint (10 items) | ⏳ pending |
| 12d | Class 3 repairs: `cross-seed/_<name>/` — resolve category → rename → repoint | ✅ done (0 items) |
| 12e | Class 5 repairs: `_qb-unique-repair/`, `_qb-finish/` — 38 repaired, 7 blocked (downloading/~issue) | ✅ done |
| 13a | trk_warns: 19 Kitsune season pack upgrades (Outlander/Frontline/Gold Rush) | ✅ done |
| 13b | trk_warns: 4–5 SNL items — manual Prowlarr check + execute | ✅ done |
| 13c | **Implement + execute:** individual-ep replacement (`candidate_replace_individual`) | ✅ done |
| 13d | Verify: SNL eps hashed in RT → hook fired → qB mirror synced | ✅ done |
| 14 | sys/docker commit: rt-mirror hash_done hook + sync-apply timer | ✅ done |
| 15 | Fix post-13a/13b drift: qB v5 login bug + 18 orphaned eps + 9 RT-only sync | ✅ done |
| 16 | RT execute-recovery: repair 90 RT items damaged by save-path-repair --execute | ✅ done |

## Slice 3 — Doc Review (done)

**Completed:**
- REQUIREMENTS.md v1.4–v1.6: RT-authoritative tiebreaker, canonical path spec §4.4, rehome
  mechanics, Prowlarr display names, §6.3 Type A/B hitchhiker taxonomy
- BACKLOG.md: Code Review Gate for stale `config.py default_dest_root`; Canonical Tree
  Normalization full taxonomy classes 1–5
- ARCHITECTURE.md: date updated, stale `tooling/*` refs replaced, RT path authority added
- REQUIREMENTS.md: 5x stale `docs/tooling/REHOME-RUNBOOK.md` / `CLI-OPERATIONS.md` refs fixed
- RUNBOOK.md: RT Path Authority Tiebreaker section added

**Gate met:** No known conflicts or gaps. No consolidation opportunities identified beyond
what was executed.

## Slice 4 — Code vs Doc Cross-Check (done)

**Scope:** All modules under `src/hashall/` and `src/rehome/`. Compare implementation
against REQUIREMENTS.md.

**Findings — ordered by severity:**

### Issue 1 — BLOCKING: `config.py` stale `default_dest_root`
- **File:** `src/rehome/config.py:25`
- **Code:** `"default_dest_root": "/pool/data/seeds"`
- **Spec:** §4.4 — canonical pool seeding root is `/pool/media/torrents/seeding`
- **Risk:** If operator's `~/.hashall/rehome.toml` doesn't override this, all rehome plans
  default to the legacy `/pool/data/seeds` root, producing non-canonical paths.
- **Proposed fix:** Change default to `"/pool/media/torrents/seeding"`.

### Issue 2 — BLOCKING: `planner.py` basename-only fallback (non-canonical path)
- **File:** `src/rehome/planner.py:284–285`
- **Code:** `return str((base_root / source_path.name).resolve()), None`
- **Spec:** §4.4.2 — canonical path must be `<seeding-root>/<category>/<item-payload-name>`.
  Basename-only fallback drops the category segment entirely, producing
  `<seeding-root>/<item-payload-name>` instead.
- **Risk:** Activates when `stash_seeding_root` is None in the Planner. Creates wrong
  target paths without alerting the operator.
- **Proposed fix:** Fail closed — return `(None, "stash_seeding_root is required for
  canonical path construction")` instead of silently returning the basename path.

### Issue 3 — NON-BLOCKING: `seed_state.py` includes legacy `/pool/data/seeds` in mirror_roots
- **File:** `src/rehome/seed_state.py:88–91` (`_legacy_seed_roots_for_managed_path`)
- **Code:** `/pool/data/seeds` appended when managed path is `/pool/data`
- **Spec:** §4.4 — `/pool/data/seeds` is a deprecated/legacy root. Including it in
  `mirror_roots` may confuse seed-root-state consumers (e.g. traktor).
- **Risk:** Low — this is a legacy compatibility branch, only activated if `/pool/data` is
  in `managed_roots`. But it can mislead tooling that uses `mirror_roots` to enumerate
  active seeding paths.
- **Proposed fix:** Remove the `/pool/data/seeds` line; keep only `/pool/data/media/torrents/seeding`.

### Issue 4 — NON-BLOCKING: `hitchhiker.py` does not detect Type A hitchhikers
- **File:** `src/hashall/hitchhiker.py:55–68`
- **Spec:** §6.3 — Type A = different items with different files cataloged under the same
  payload root_path (catalog collision); Type B = different hashes sharing same physical files.
- **Code:** Only queries `payload_id IN (... HAVING COUNT(*) > 1)` — detects Type B (same
  payload_id, multiple torrent_instances). Type A would appear as two separate payload rows
  with the same `root_path`, not a shared `payload_id`.
- **Risk:** Type A groups silently pass audit; hitchhiker report gives false-clean signal.
- **Proposed fix:** Add a second query: payloads with identical `root_path` but different
  `payload_id` and at least one torrent_instance each. Report them separately as `TYPE_A`.

### Issue 5 — NO ISSUE: `executor.py` — rsync flags and cross-filesystem guard
- `-aHAX` flags are correct (archive + hardlinks + ACLs + xattrs). Cross-filesystem guard
  uses `st_dev` comparison with conservative fail-closed fallback. Source cleanup is deferred
  per §8.3. No action needed.

### Issue 6 — NO ISSUE: `client_drift.py` — RT-authoritative tiebreaker and alias handling
- `rt_authoritative_path_wins` reason implemented at line 1321. The old broad blocker
  `both_clients_on_required_placement_but_paths_differ` is now only emitted when RT path
  is actually missing (line 1325) — this is the correct escalation path. Alias-aware path
  comparison uses `remap_to_mount_alias`. No action needed.

**Gate met:** All 4 issues fixed (commit ead9b06). 36 targeted tests pass.

### Test Plan for Slice 4 Fixes

#### Fix 1 — `config.py default_dest_root`
- **Unit:** `pytest tests/ -k config` — no existing direct test; the value flows into
  `DemotionPlanner` via `load_config()`. Covered indirectly by planner tests.
- **Manual check:** `python -c "from rehome.config import DEFAULTS; print(DEFAULTS['default_dest_root'])"`
  → must print `/pool/media/torrents/seeding`.
- **Integration:** In Slice 5 dry-run battery, verify `hashall rehome auto --from stash --to pool --limit 1 --dryrun`
  targets `/pool/media/torrents/seeding`, not `/pool/data/seeds`.

#### Fix 2 — `planner.py` fail-closed when `stash_seeding_root` is None
- **Unit:** No existing direct test for this path. Add in Slice 5 Phase 1 walkthrough:
  instantiate `DemotionPlanner` without `stash_seeding_root`; call `_compute_pool_move_target`;
  assert `(None, error_string)` returned. (Manual test above already confirms this.)
- **Integration:** If `~/.hashall/rehome.toml` is missing `active_root`, planner must fail
  with a clear error rather than producing a basename-only path. Verify in dry-run.

#### Fix 3 — `seed_state.py` `/pool/data/seeds` removed from legacy mirror_roots
- **Unit:** `test_rehome_seed_state.py::test_build_seed_root_state_surfaces_active_target_and_legacy_mirrors`
  — assertion updated and passing. Confirms `/pool/data/seeds` absent from `mirror_roots`
  when managed_roots contains `/pool/data`.
- **Integration:** After Slice 9 refresh, inspect `~/.hashall/seed-root-state.json`; confirm
  `/pool/data/seeds` is absent from `mirror_roots`.

#### Fix 4 — `hitchhiker.py` Type A detection
- **Unit:** Existing `test_hitchhiker.py` (12 tests) covers Type B. No Type A test exists.
  In Slice 5 Phase 1: add a test with two payloads sharing the same `root_path` and confirm
  `query_type_a_groups` returns a group with `status=TYPE_A`.
- **Integration:** `hashall hitchhiker audit` — if any Type A groups exist in the live catalog,
  they will now appear in the report. Baseline run in Slice 5 Phase 2 dry-run battery.

## Slice 5 — Test Gate (done)

**Phase 1 — Code walkthrough: COMPLETE, no issues**
- `repoint_both_to_pool` apply path: correctly fails-safe if pool target doesn't exist (cli.py:3268)
- No logic errors found in client-drift apply, payload sync, or catalog refresh flows

**Phase 2 — Dry-run battery: COMPLETE, 2 bugs caught and fixed**
- `client-drift-audit ANCHOR_SCAN=0`: Novitiate blocked (`catalog_payload_paths_missing`) — expected
- `client-drift-audit ANCHOR_SCAN=200000`: Novitiate shows `desired=pool, no_client_on_required_pool_placement` — expected, no pool sibling yet
- `client-drift-both-to-pool-dry HASH=2fb25fdf2ef20ae5 ANCHOR_SCAN=200000`: correctly blocked — `no_client_on_required_pool_placement`
- `hitchhiker-audit`: **caught 2 bugs** in Type A detection (COUNT(*) → COUNT(DISTINCT), INNER JOIN → LEFT JOIN); both fixed (faf537f); 54 genuine Type A groups now surfaced
- rsync dry-run stash→pool: clean — 1 file, 26.1 GB, no deletions

**Phase 3 — Pilot readiness: READY, awaiting operator sign-off**
- Canonical pool target: `/pool/media/torrents/seeding/cross-seed/seedpool/Novitiate.2017.BluRay.1080p.DTS-HD.MA.5.1.AVC.REMUX-FraMeSToR/`
  - Does not yet exist (correct — rsync hasn't run)
  - Pool space: 3.6 TB free (ample for 25 GB file)
  - Source: inode 69036, 5 hardlinks, both qB and RT paths point to same physical file
- Pilot sequence (Slice 6 = Phase 3 pilot):
  1. `rsync -aHAX --partial` stash→pool (cross-filesystem copy, 25 GB)
  2. `hashall payload sync`
  3. `client-drift-both-to-pool-dry HASH=2fb25fdf2ef20ae5 ANCHOR_SCAN=200000` — verify target found
  4. `client-drift-both-to-pool-apply HASH=2fb25fdf2ef20ae5 ANCHOR_SCAN=200000` — repoint RT+qB
  5. Post-check: verify RT and qB state, confirm pool seeding

**Gate criteria:** All three phases complete with no outstanding errors. Any fixes from
phases 1–2 committed before phase 3 begins. **Operator sign-off required before proceeding to slice 6.**

## Remaining Queue

**Slice 11 — Canonical tree normalization report:**
- Query catalog for non-canonical path patterns (classes 1–5 from BACKLOG.md taxonomy)
- Output: per-class count + sample paths; class 6 (Prowlarr display names) excluded
- Script: `scripts/canonical-tree-report.py` (or inline hashall CLI subcommand)
- Makefile target: `make canonical-tree-report`
- Counts update automatically after each catalog refresh (slice 9 first)

## Evidence Baseline (2026-05-20, post-slice-9)

- qB: 4818 rows, daemon_live
- RT: 4818 rows, daemon_live
- Catalog last scan: 2026-05-20 ✅ (db-refresh-fast-gated-parallel, 5m26s)
- Payload sync: 4762 complete, 56 incomplete, 1 missing-in-catalog
- Orphan GC candidates: 2480 (2477 aged, 2 new) — blocked (>1000 limit)
- **Drift: 0** (path drift: 0 high/medium/low)
- RT-only: 0
- Hitchhiker audit: 162 groups — 54 Type A, 60 safe-to-split, 47 blocked, 1 busy

## Slice 7 — Top Gun Maverick IMAX (done)

- `f3d70ba48ecbc51b`: RT-only `stalledUP`, YUSCENE (API), 7.5 GB, inode 385, nlinks=10
- Decision: mirror to qB (standard RT→qB policy for cross-seed items)
- Action: `make rt-qb-mirror-apply` — added to qB as stopped, recheck completed `stoppedUP 100%`
- RT mirror watchdog was `down` (3m) — manually triggered; watchdog resumed after

## Slice 8 — Code fixes (done)

### Fix 1 — `payload sync` advisory process lock
- **File:** `src/hashall/cli.py` (`payload_sync`)
- **Problem:** Concurrent `payload sync` runs (cron + manual, or `rehome followup` + cron) caused
  `sqlite3.OperationalError: database is locked` — the long-running upgrade loop held a write
  transaction that exhausted the 30s busy_timeout for other writers.
- **Fix:** Added `fcntl.flock(LOCK_EX)` advisory lock on `<db-dir>/payload-sync.lock` at sync start.
  If a concurrent run tries to acquire the lock it waits (blocking) rather than failing.
  Dry-run skips the lock (opens read-only, no contention).

### Fix 2 — Orphan GC count/fraction limits as CLI flags
- **Files:** `src/hashall/payload.py` (`prune_orphan_payloads`), `src/hashall/cli.py`
- **Problem:** With 2479 aged orphan candidates > `ORPHAN_GC_MAX_PRUNE_COUNT=1000`, the GC was
  permanently blocked. Only workaround was env vars (`HASHALL_ORPHAN_GC_MAX_PRUNE_COUNT=3000`).
- **Fix:** Added `max_prune_count` / `max_prune_fraction` params to `prune_orphan_payloads`
  (explicit args override env vars); exposed as `--orphan-gc-max-prune-count` and
  `--orphan-gc-max-prune-fraction` CLI flags on `payload sync`.
- **Usage:** `hashall payload sync --orphan-gc-max-prune-count 3000 --orphan-gc-max-prune-fraction 0.5`

## Slice 9 — Catalog Refresh (done)

- `make db-refresh-fast-gated-parallel` completed in 5m26s (5 roots, 4 with changes)
- `make client-drift-audit ANCHOR_SCAN=200000`: qB=4818, RT=4818, Drift=0 ✅
- `make hitchhiker-audit`: 162 groups — 54 Type A, 60 safe-to-split, 47 blocked, 1 busy
- Evidence baseline updated in this file

## Slice 10 — RT→qB Mirror Watchdog Investigation (done)

### Root cause (confirmed via cross-seed logs)

**Cross-seed RSS injections into RT bypass `event.download.finished` entirely.**

The complete failure chain for `f3d70ba4` (Top Gun Maverick IMAX, 2026-05-19):
1. `10:09:17` — cross-seed RSS found TGM on YUSCENE, matched to existing qB torrent `043c5b5c`
2. `10:09:20` — cross-seed hardlinked files to `/data/media/torrents/seeding/YUSCENE (API)/`
3. `10:09:21` — cross-seed injected torrent into RT via XMLRPC (`rtorrent@gluetun:8000`) — **"injected"**
4. RT ran hash check → 100% → immediately entered seeding state
5. **`event.download.finished` never fired** — rTorrent only fires this for torrents that actually download data; pre-seeded/linked injections skip directly to seeding
6. `rt_qb_mirror_enqueue.sh` was never called → no queue entry for `f3d70ba4`
7. qB never received the mirror → f3d70ba4 stuck RT-only
8. Watchdog `check_full_drift` flagged it every 15 min from ~21:00 (first watchdog run after queue had aged); resolved only at 04:16 on 2026-05-20 when `make rt-qb-mirror-apply` was run manually

**This is systematic**: every cross-seed injection into RT bypasses the finished hook. This happens for all RSS matches and search matches that land in RT.

### Why the watchdog architecture makes this visible but can't self-heal

Two fundamentally different check paths:
- `check_queue_drift` → `process-queue` dry-run: only inspects items in `QUEUE_DIR`
- `check_full_drift` → `sync` dry-run: inspects ALL RT-only items

The `rt-qb-mirror-queue-apply.timer` (every 5 min) runs `process-queue --apply`. It has nothing to process for RT items that never entered the queue. Only `make rt-qb-mirror-apply` (`sync --apply`) clears them.

### Secondary finding — stale queue entries
- 4 fake-hash test entries (111..., 333..., 444..., 555...) stuck for 360+ hours — match nothing in RT or qB, print `queued_not_ready_for_mirror` but don't cause failures
- 8 real-hash entries already mirrored to qB — same, harmless but noisy

### Remediation options

**Option A — Periodic `sync --apply` timer (recommended, sys repo):**
New systemd timer `rt-qb-mirror-sync.timer` (every 1-2 hours) runs `sync --apply` as a catch-all for RT-only items that bypass the queue. Self-healing within timer interval. Files: `rt_qb_mirror_sync_apply.sh` + `.service` + `.timer` in sys repo.

**Option B — rTorrent `event.download.hash_done` hook (proper fix, rt config):**
Add a hook in `rtorrent.rc` on `event.download.hash_done` that calls `rt_qb_mirror_enqueue.sh` when `d.complete=1`. This fires after every recheck; the enqueue script is idempotent (re-enqueuing an already-mirrored item is harmless). Catches cross-seed injections at the source. Requires modifying rtorrent.rc in sys repo.
```
method.set_key = event.download.hash_done, mirror_enqueue_if_complete, \
  "execute.nothrow.bg={/bin/bash,-c,/config/scripts/rt_qb_mirror_enqueue.sh $d.hash= $d.complete=}"
```
(enqueue script would need a `$2` complete-check guard added)

**Option C — Stale queue GC (cosmetic only):**
Remove queue files for hashes already in qB or with fake hashes. Safe, reduces noise, does NOT prevent future cross-seed gaps.

### Implementation (2026-05-20)

**Option B — `event.download.hash_done` hook:**
- `rt_qb_mirror_enqueue.sh` bumped to v1.1.0: accepts optional `$2` = `d.complete=` value;
  skips if `$2` is present and != "1"; sets `source=rt-hash-done-hook` for new queue files
- `rtorrent.rc`: added `method.set_key = event.download.hash_done, rt_qb_mirror_hook_hash_done, ...`
- **Requires RT container restart** to reload rtorrent.rc (`docker restart rtorrent_vpn`)
- Script is bind-mounted live — no restart needed for the script itself

**Option A — Periodic `sync --apply` timer:**
- New script: `rt_qb_mirror_sync_apply.sh` v1.0.0 in sys/docker repo
- New units: `/etc/systemd/system/rt-qb-mirror-sync.{service,timer}` — runs every 2h, `OnBootSec=15min`
- Timer enabled and verified: first run clean (`selected=0`, rc=0), next fire at 08:07
- `healthchecks.json` updated: added `RT qB mirror sync apply` entry (uuid blank — create monitor at healthchecks.io)

**Healthchecks review:**
- `RT qB mirror queue apply` (every 5 min, timeout=300) ✅ correctly configured
- `RT qB mirror watchdog` (every 15 min, timeout=900) ✅ correctly configured
- `RT qB mirror sync apply` (every 2h, timeout=7200) ⚠️ uuid blank — needs healthchecks.io monitor created

**Pending:**
- RT container restart to activate `hash_done` hook: `docker restart rtorrent_vpn`
- Create healthchecks.io monitor "RT qB mirror sync apply" and add UUID to `/etc/glider-backup/healthchecks.json`
- Commit sys/docker repo changes (currently on `main`, unstaged)

## Slice 12 — Canonical Path Class Table + Repair Plan

### Live counts (2026-05-20, post-slice-9 refresh)

| Class | Count | Pattern | Repair action |
|---|---|---|---|
| 1 | 10 | `cross-seed/<40-hex-hash>/` | Identify correct tracker from hash → rename dir → RT repoint → qB set_location |
| 2 | 6 | `cross-seed/other/` | Identify correct tracker → rename dir → RT repoint → qB set_location |
| 3 | 30 | `cross-seed/_movie/`, `cross-seed/_<name>/` | Identify correct tracker (check RT/qB tracker URL) → rename dir → RT repoint → qB set_location |
| 4 | 10 | `_rehome-unique/<hash>/` | Investigate each: determine canonical path from tracker label → move → RT repoint → qB set_location |
| 5 | 49 | `_qb-unique-repair/`, `_qb-repair-v2/`, `_qb-finish/` | Investigate staging state per item: if complete, repoint to canonical path; otherwise resume repair |

**Note:** counts from `torrent_instances` (both qB + RT rows). Canonical path = `<seeding-root>/<category>/<item-payload-name>` where category is the tracker name for cross-seed items or the media type (tv/, movies/) for ARR-imported items.

### Repair sequence (safe order per sprint baseline)

Classes 4 → 2 → 1 → 3 → 5 → Type A de-hitchhike (last)

### Per-class repair commands

**Class 1/2/3 (cross-seed path fixes):** For each torrent, look up tracker host from RT XMLRPC, then:
```bash
# 1. Rename dir on filesystem (data and stash are same fs — use mv)
# 2. RT repoint:
python3 -m hashall rt repoint --hash <hash> --target <new-save-path> --apply
# 3. qB repoint (set save_path to parent dir):
# use hashall client-drift-audit or direct qB set_location API
```

**Class 4 (_rehome-unique):** These have canonical hash names — use `hashall payload hitchhiker-plan` to check if they are hitchhikers, then split/repoint.

**Class 5 (_qb-unique-repair/_qb-repair-v2/_qb-finish):** Use `make client-drift-verify-layout-scan` to assess each. Items in `_qb-finish/` are likely complete and just need repoint. Items in `_qb-repair-v2/` may still need data validation.

**Next step:** Run `make canonical-tree-report` (Slice 11 builds this) to get per-item details and drive the repair loop.

## Slice 13 — trk_warns: 23 Deleted Aither Torrents

### What they are

All 23 are individual episode files on Aither (aither.cc) that were deleted from the tracker. The uploader (Kitsune for most; None/ppkhoa for SNL) deleted the individual episodes after uploading season packs.

| Group | Count | Deleted | Season pack found | Seeders |
|---|---|---|---|---|
| Outlander S08 (Kitsune) | 10 | E01–E05, E07–E10 | Outlander S08 1080p AMZN WEB-DL DD+ 5.1 H.264-Kitsune | 52 |
| Frontline S2025 (Kitsune) | 7 | E07–E13 | Frontline 1983 S2025 1080p AMZN WEB-DL DD+ 2.0 H.264-Kitsune | 12 |
| Gold Rush S16 (Kitsune) | 2 | E03–E04 | Gold Rush S16 1080p AMZN WEB-DL DD+ 2.0 H.264-Kitsune | 11 |
| SNL S51 (None/ppkhoa) | 4 | E09, E12, E13, E16, E18 | Individual Kitsune eps found (not a season pack) | 90 |

**Dry-run result:** All 23 classified as `action: candidate_upgrade_season_pack`. Prowlarr found season packs on Aither by the same group for Outlander/Frontline/Gold Rush.

**⚠️ SNL caveat:** The 4–5 SNL items show `candidate_upgrade_season_pack` but Prowlarr's top result is an individual episode (E16 by Kitsune), not a season pack. The 54-hit pool may include a season pack, but visually it's ambiguous. Run the SNL items separately or verify manually before executing.

### Commands

```bash
# Step 1 — dry-run already done; review output above
make trk-warn-dry BUCKET=deleted

# Step 2 — execute season pack upgrade for all 23
# Erases individual ep RT torrents, adds season packs to RT+qB, syncs
make trk-warn-upgrade-packs BUCKET=deleted

# Optional: run SNL items separately after manual check
make trk-warn-upgrade-packs BUCKET=deleted HASH=E9DC45E8F7  # etc.
```

`trk-warn-upgrade-packs` runs: `--cleanup --repair --prowlarr --bucket deleted`
What it does per item: (1) erases RT torrent via `d.erase`, (2) removes from qB, (3) adds season pack torrent to RT as stopped at the canonical save path, (4) triggers qB mirror via queue.

## Slice 13c — Plan: Individual-Episode Replacement for Deleted Torrents (no season pack)

### Problem

When a tracker deletes individual episodes and no season pack exists, the `candidate_upgrade_season_pack`
action fires but Prowlarr's best result is another individual ep (different uploader, same episode).
The script's `season_upgrade` path requires a pack-level match — it has no mechanism to use a per-episode
replacement. Affected: 5 SNL S51 items.

### Proposed action class: `candidate_replace_individual`

Fires when:
- `bucket == deleted`
- Prowlarr direct search finds no result on the same tracker (`hits=0`)
- `season_upgrade` exists but `best_title` looks like an individual ep (not a season pack) — heuristic: no `Sxx ` without `Exx` in title, or detect via episode count in Prowlarr result
- A per-episode Prowlarr search (by series + episode ID, e.g. `"Saturday Night Live S51E09"`) returns a hit with `best_download_url`

Action:
1. Erase the deleted RT torrent (`d.erase`) — same as current flow
2. Remove from qB (keep files)
3. Add the individual replacement ep torrent to RT at the same save path (not a new canonical path)
4. Trigger qB mirror queue

### Implementation plan

1. **Search change:** Add a per-episode Prowlarr search function alongside the existing `season_upgrade` query. Use the episode file stem stripped to `<Series> SxxExx` (e.g. `"Saturday Night Live S51E09"`) as the search term.
2. **Classification change:** In `classify_row()`, after `season_upgrade` is found, check if `best_title` contains an episode identifier (`E\d\d`). If so, classify as `candidate_replace_individual` instead of `candidate_upgrade_season_pack`.
3. **Cleanup change:** In `cleanup_rows()`, add `candidate_replace_individual` to `actionable`; populate `best_download_url` from the per-episode search result; use `compute_save_path_for_replacement()` with the existing save path (no category change).
4. **Makefile target:** `make trk-warn-replace-individual BUCKET=deleted` — new target using `--replace-individual-eps --cleanup --repair --prowlarr`.

### Why this resolves SNL

SNL seasons are not uploaded as packs on Aither; individual Kitsune eps are the correct replacement unit.
The 54-hit pool (E16 by Kitsune with 92 seeders) suggests Kitsune has replacements for most SNL eps.
A targeted `S51E09`, `S51E12`, etc. search would surface the right individual replacement for each.

### Files to change

- `rt-tracker-manual-report.py`: `classify_row()`, `cleanup_rows()`, add `prowlarr_search_individual_ep()`, add `--replace-individual-eps` CLI flag
- `Makefile`: add `trk-warn-replace-individual` target

## Slice 6 — Novitiate (done)

- rsync 25 GB stash→pool (ioniced, cross-filesystem, exit 0)
- mv `cross-seed/seedpool/` → `cross-seed/seedpool (API)/` (canonical tracker name)
- RT repointed via `hashall rt repoint --apply` to `seedpool (API)/Novitiate.../`
- qB repointed via `set_location` → `seedpool (API)/` (parent); recheck triggered; 100% stoppedUP
- Drift audit post-state: **0 path drift items**
- Lessons: `set_location` triggers a physical move (not just repoint); always set `save_path` to
  PARENT of torrent top-level folder (not the folder itself). `_find_pool_sibling_path` requires
  `payload_hash` in catalog — newly rsync'd paths without a qB torrent don't get payload_hash until
  after payload sync post-repoint. Workaround: direct `rt repoint` + qB `set_location` bypass.

## Done This Sprint

- Slice 0: cleared dead refresh.lock, ran payload sync (4818 torrents), fresh audit
- Slice 1: Alien Resurrection — qB repointed pool→stash to match RT (b21da72)
- Slice 2: Twin Peaks — qB repointed onlyencodes→darkpeers to match RT (b21da72)
- Slice 3 (partial): REQUIREMENTS.md v1.4–1.6; BACKLOG.md Code Review Gate + Canonical Tree Normalization taxonomy
- All prior hardening (v0.8.50, 36ea583): xmlrpc, RT check-hash, Case B guard, verify-layout-scan
- Cinderella pilot `97343f6005da2ed8` succeeded (drift 12→11)
- Alias-aware client drift tooling, hitchhiker split fail-closed

## Safety Rules (active every session)

- `/data/media` and `/stash/media` are the same filesystem — always canonicalize
- Dry-run → tiny pilot → post-check before widening any batch
- One mutating qB/RT workflow at a time
- `~noHL` is advisory only; never mutate on it alone
- Always run `make client-drift-audit ANCHOR_SCAN=200000` (not default 0) for actionable evidence
- **No live rehome operations until slice 5 test gate is complete and signed off**
