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
| 3 | **Doc review**: full repo doc audit — gaps, conflicts, consolidation | 🔄 in progress |
| 4 | **Code vs doc**: cross-check all code against docs; plan fixes | ⏳ pending |
| 5 | **Test gate**: multi-phase walkthrough + dry-runs; pilot all tools; fix errors | ⏳ pending |
| 6 | Novitiate: pool rehome + client repoint | ⏳ pending |
| 7 | Top Gun Maverick IMAX: policy decision + action (RT-only) | ⏳ pending |
| 8 | Code fixes: db-lock on concurrent sync, orphan GC limit | ⏳ pending |
| 9 | Refresh: run catalog refresh, verify clean audit | ⏳ pending |

## Slice 3 — Doc Review (in progress)

**Scope:** All files under `docs/`, `AGENTS.md`, `CLAUDE.md`, `BACKLOG.md`, `SPRINT.md`.
Check for: internal contradictions, stale content, missing coverage, duplicate sections,
consolidation opportunities.

**Completed this session:**
- REQUIREMENTS.md v1.4: RT-authoritative tiebreaker; §4.4 canonical path spec (commit b21da72)
- REQUIREMENTS.md v1.5: rehome mechanics — §5.1.1 cross-filesystem copy rule, §5.1.2 primary
  mover selection spec, §4.2.1 exact-hash vs inode-sharing clarification, §4.4.2 seeding root
  selection + path preservation (commit 1047217)
- REQUIREMENTS.md v1.6: Prowlarr display names canonical; §6.3 Type A/B hitchhiker taxonomy;
  BACKLOG Canonical Tree Normalization full taxonomy classes 1–5 (commit c2f0d1d)
- BACKLOG.md: Code Review Gate for stale `config.py default_dest_root`

**Remaining doc review work:**
- Full pass of all remaining docs (RUNBOOK.md, ARCHITECTURE.md, AGENTS.md, any others)
  for gaps not yet addressed
- Identify consolidation/simplification opportunities
- Propose and execute any further fixes; commit

**Gate criteria:** No known conflicts or gaps in docs. Consolidation options presented and
decided. All doc commits landed.

## Slice 4 — Code vs Doc Cross-Check (pending)

**Scope:** All modules under `src/hashall/` and `src/rehome/`. Compare implementation
against REQUIREMENTS.md. Focus areas:
- `src/rehome/config.py`: stale `default_dest_root` (documented in BACKLOG Code Review Gate)
- `src/rehome/planner.py`: basename-only fallback when `stash_seeding_root` is None (violates
  canonical path formula §4.4.2)
- `src/rehome/executor.py`: rsync flags, source cleanup sequencing, cross-filesystem guard
- `src/hashall/client_drift.py`: pool sibling selection, RT-authoritative tiebreaker, alias handling
- `src/hashall/hitchhiker.py`: Type A detection gap (currently detects Type B only)
- `src/rehome/seed_state.py`: `/pool/data/seeds` in fallback known-roots list

**Output:** Ordered list of code issues with severity (blocking/non-blocking), reference to
spec section violated, proposed fix for each. No code changes in this slice — issues logged
only.

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
