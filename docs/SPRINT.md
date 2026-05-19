# Current Sprint

Last updated: 2026-05-19
Status: active

## Active Goal

Keep qBittorrent and rTorrent in sync for all seeded datasets; reduce same-hash
qB/RT save-path drift to zero; preserve placement policy.

## Current Queue (3 drift cases remaining after slice 0 housekeeping)

**Next up — HIGH priority, clear fix:**
1. `4f454ed3bdf830f0` **Alien Resurrection** — repoint qB to RT stash path
   - `make client-drift-qb-to-rt-dry HASH=4f454ed3bdf830f0` → inspect → apply

**LOW — stash/stash path disagreement:**
2. `c7845e03fe21e7fa` **Twin Peaks S01** — both on stash, different tracker dirs
   - `make client-drift-selected HASH=c7845e03fe21e7fa ANCHOR_SCAN=200000`
   - pick canonical cross-seed tracker path, repoint the other client

**LOW — needs pool rehome before client fix:**
3. `2fb25fdf2ef20ae5` **Novitiate** — both on stash but desired=pool (noHL, no ARR)
   - `make client-drift-selected HASH=2fb25fdf2ef20ae5 ANCHOR_SCAN=200000`
   - needs rehome plan to pool first, then client repoint

**RT-only — policy decision needed:**
4. `f3d70ba48ecbc51b` **Top Gun Maverick IMAX** — RT stalledUP, not in qB
   - options: add to qB, leave RT-only, or remove from RT
   - operator must decide policy before any action

## Slice Progress

| Slice | Goal | Status |
|---|---|---|
| 0 | Housekeeping: clear lock, payload sync, fresh audit | ✅ done |
| 1 | Alien Resurrection: dry-run + apply qB repoint | next |
| 2 | Twin Peaks: evidence + repoint | pending |
| 3 | Top Gun Maverick: policy decision + action | pending |
| 4 | Novitiate: rehome plan + repoint | pending |
| 5 | Code fixes: db-lock on concurrent sync, orphan GC limit | pending |
| 6 | Refresh: run catalog refresh, verify clean audit | pending |

## Evidence Baseline (2026-05-19, post-slice-0)

- qB: 4817 rows, daemon_live
- RT: 4818 rows, daemon_live
- Catalog last scan: 2026-05-10 (9 days — refresh needed in slice 6)
- Payload sync: 2026-05-19 ✅ (was 2026-03-21 — 59-day gap now closed)
- Drift: 3 (was 11 on May 8)
- RT-only: 1 (was 7 on May 8)

## Done This Sprint

- Slice 0: cleared dead refresh.lock, ran payload sync (4818 torrents), fresh audit
- All prior hardening (v0.8.50, 36ea583): xmlrpc, RT check-hash, Case B guard, verify-layout-scan
- Cinderella pilot `97343f6005da2ed8` succeeded (drift 12→11)
- Alias-aware client drift tooling, hitchhiker split fail-closed

## Safety Rules (active every session)

- `/data/media` and `/stash/media` are the same filesystem — always canonicalize
- Dry-run → tiny pilot → post-check before widening any batch
- One mutating qB/RT workflow at a time
- `~noHL` is advisory only; never mutate on it alone
- Always run `make client-drift-audit ANCHOR_SCAN=200000` (not default 0) for actionable evidence
