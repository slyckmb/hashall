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
| 4 | **Code vs doc**: cross-check all code against docs; plan fixes | 🔄 in progress |
| 5 | **Test gate**: multi-phase walkthrough + dry-runs; pilot all tools; fix errors | ⏳ pending |
| 6 | Novitiate: pool rehome + client repoint | ⏳ pending |
| 7 | Top Gun Maverick IMAX: policy decision + action (RT-only) | ⏳ pending |
| 8 | Code fixes: db-lock on concurrent sync, orphan GC limit | ⏳ pending |
| 9 | Refresh: run catalog refresh, verify clean audit | ⏳ pending |

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

## Slice 4 — Code vs Doc Cross-Check (in progress)

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

**Gate criteria:** Every identified code gap has a spec reference and a proposed fix. List
reviewed and prioritised by operator before slice 5.

## Slice 5 — Test Gate (pending)

**Scope:** All hashall and rehome CLI tools that will be used in slices 6–9.
Three phases, loop each until clean:

**Phase 1 — In-memory code walkthrough:**
- Trace control flow for each planned operation (client-drift dry-run, payload sync,
  catalog refresh, both-to-pool apply)
- Identify logic errors, missing guards, wrong path construction
- Fix any errors found; loop until walkthrough produces no new issues

**Phase 2 — Dry-run battery:**
- Run every make target relevant to slices 6–9 in dry-run mode
- Capture and review all output; flag unexpected warnings, wrong paths, or blocked actions
- Fix errors found; loop until all dry-runs produce expected output

**Phase 3 — Pilot validation:**
- For each tool class, run a constrained live pilot on the lowest-risk candidate
- Verify output, catalog state, and client state after each pilot
- Fix errors found; loop until pilot passes; do not widen scope until gate is clean

**Gate criteria:** All three phases complete with no outstanding errors. Any fixes from
phases 1–2 committed before phase 3 begins. Operator sign-off before proceeding to slice 6.

## Remaining Queue (slices 6–7)

**Slice 6 — Novitiate (`2fb25fdf2ef20ae5`):** both clients on stash, desired=pool, noHL, no ARR.
- rsync stash→pool canonical path (26 GB), payload sync, both-to-pool apply, verify

**Slice 7 — Top Gun Maverick IMAX (`f3d70ba48ecbc51b`):** RT-only stalledUP, not in qB.
- Run evidence scan; decide: mirror to qB / leave RT-only / remove from RT

## Evidence Baseline (2026-05-19, post-slice-0)

- qB: 4817 rows, daemon_live
- RT: 4818 rows, daemon_live
- Catalog last scan: 2026-05-10 (9 days — refresh needed in slice 9)
- Payload sync: 2026-05-19 ✅ (was 2026-03-21 — 59-day gap now closed)
- Drift: 1 (was 11 on May 8; slices 1–2 resolved 2 cases)
- RT-only: 1 (unchanged — Top Gun Maverick, slice 7)

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
