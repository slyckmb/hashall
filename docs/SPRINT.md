# Current Sprint

Last updated: 2026-06-16
Status: active

## Active Goal

Keep qBittorrent and rTorrent in sync for all seeded datasets; reduce same-hash
qB/RT save-path drift to zero; preserve placement policy.

## Slice Progress

| Slice | Goal | Status |
|---|---|---|
| 0–11 | Housekeeping, pilots, doc review, code fixes, refresh, watchdog, canonical report | ✅ done |
| 12a | Class 4 repairs: `_rehome-unique/<hash>/` — 376 dirs cleared | ✅ done |
| 12b | `cross-seed/<tracker>/` legacy prefix removal — ~2125 items: rename dir + repoint both clients | ⏳ pending |
| 12c | Class 1 repairs: `cross-seed/<hash>/` — resolve tracker → rename → repoint (10 items) | ⏳ pending |
| 12d | Class 3 repairs: `cross-seed/_<name>/` | ✅ done (0 items) |
| 12e | Class 5 repairs: `_qb-unique-repair/`, `_qb-finish/` — 38 repaired, 7 blocked | ✅ done |
| 13a | trk_warns: 19 Kitsune season pack upgrades (Outlander/Frontline/Gold Rush) | ✅ done |
| 13b | trk_warns: SNL S51 Prowlarr check + execute | ✅ done |
| 13c | Implement + execute: `candidate_replace_individual` with escalating search | ✅ done |
| 13d | Verify: SNL eps hashed in RT → hook fired → qB mirror synced | ✅ done |
| 14 | sys/docker commit: rt-mirror hash_done hook + sync-apply timer | ✅ done |
| 15 | Fix post-13a/13b drift: qB v5 login bug + 18 orphaned eps + 9 RT-only sync | ✅ done |
| 16 | RT execute-recovery: repair 90 RT items damaged by save-path-repair --execute | ✅ done |

See `docs/archive/SPRINT-history.md` for done-slice details.

## Open Slice Detail

### Slice 12b — `cross-seed/<tracker>/` legacy prefix removal (~2125 items)

Each item: rename dir on filesystem → RT repoint → qB set_location.
Prereqs: fresh canonical-tree-report counts, RUNBOOK execution protocol (OP-02).
**Blocking issue:** OP-05 and OP-06 (save-path-repair bugs) must be fixed first.

### Slice 12c — Class 1 repairs: `cross-seed/<hash>/` (10 items)

Each item: resolve tracker from hash via RT XMLRPC → rename dir → RT repoint → qB set_location.
Depends on 12b being complete (shared tooling).

## Evidence Baseline (2026-05-20, post-slice-9 — stale, refresh pending)

- qB: 4818 rows, daemon_live
- RT: 4818 rows, daemon_live
- Catalog last scan: 2026-05-20 ✅ (db-refresh-fast-gated-parallel, 5m26s)
- Payload sync: 4762 complete, 56 incomplete, 1 missing-in-catalog
- Orphan GC candidates: 2480 (2477 aged, 2 new) — blocked (>1000 limit)
- **Drift: 0** (path drift: 0 high/medium/low)
- RT-only: 0
- Hitchhiker audit: 162 groups — 54 Type A, 60 safe-to-split, 47 blocked, 1 busy

_Update this section after each `make db-refresh-fast-gated-parallel` + audit run._

## Canonical Path Class Table (2026-05-20 counts — refresh pending)

| Class | Count | Pattern | Status |
|---|---|---|---|
| 1 | 10 | `cross-seed/<40-hex-hash>/` | ⏳ slice 12c |
| 2 | 6 | `cross-seed/other/` | ⏳ slice 12b |
| 3 | 30 | `cross-seed/_movie/`, `cross-seed/_<name>/` | ⏳ slice 12b |
| 4 | 10 | `_rehome-unique/<hash>/` | ✅ cleared (slice 12a) |
| 5 | 49 | `_qb-unique-repair/`, `_qb-repair-v2/`, `_qb-finish/` | ✅ cleared (slice 12e) |

Repair sequence: Class 2 → 1 → 3 → Type A de-hitchhike (last).

## Safety Rules (active every session)

- `/data/media` and `/stash/media` are the same filesystem — always canonicalize
- Dry-run → tiny pilot → post-check before widening any batch
- One mutating qB/RT workflow at a time
- `~noHL` is advisory only; never mutate on it alone
- Always run `make client-drift-audit ANCHOR_SCAN=200000` (not default 0) for actionable evidence
- **OP-05 and OP-06 must be fixed before running `save-path-repair --execute` again**
