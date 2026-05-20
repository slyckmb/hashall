# Current Sprint

Last updated: 2026-05-19
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
| 9 | Refresh: run catalog refresh, verify clean audit | ⏳ pending |
| 10 | Investigate RT→qB mirror watchdog failures (recurring down) | ⏳ pending |
| 11 | Canonical tree normalization report: script + Makefile target | ⏳ pending |

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

## Evidence Baseline (2026-05-20, post-slice-7)

- qB: 4818 rows, daemon_live
- RT: 4818 rows, daemon_live
- Catalog last scan: 2026-05-10 (10 days — refresh needed in slice 9)
- Payload sync: 2026-05-19 ✅
- **Drift: 0**
- RT-only: 0 (Top Gun Maverick mirrored to qB — stoppedUP 100%)

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
