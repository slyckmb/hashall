# Current Sprint

Last updated: 2026-05-19
Status: active

## Active Goal

Keep qBittorrent and rTorrent in sync for all seeded datasets; reduce same-hash
qB/RT save-path drift; preserve placement policy.

## This Sprint — Ordered Focus

1. **qB/RT drift repair** (primary lane)
   - Work the ranked drift queue from `NEXT-AGENT-PROMPT.md` / `RUN-STATE.md`
   - Easy: `5c86280a99d10071` Spider-Man Into the Spider-Verse
   - Medium: `20555f704e0ae477`, `e2a7eab3a5be76f7`, `1a06655541134463`,
     `4052607092357bfe`, `2a4e075ecf0962ba`
   - Hard: `4f454ed3bdf830f0`, `2fb25fdf2ef20ae5`, `29e2b889867a8fbb`,
     `a5a2b78798009b38`, `c7845e03fe21e7fa`

2. **Placement policy enforcement**
   - ARR-hardlinked → `/data/media` / `/stash/media`
   - Non-ARR-hardlinked seeded payloads → `/pool/media`
   - `~noHL` tags are advisory; always confirm filesystem state first

3. **Client-drift hardening** (ongoing)
   - Verify layout scan, Case B guard, RT check-hash post-apply — landed (36ea583)
   - Keep post-apply verification gates active in all apply flows

## Current Evidence Baseline (2026-05-08)

- qB cache: 5203 rows, daemon_live, fetched 2026-05-08T23:07:42Z
- RT cache: 5210 rows, daemon_live, fetched 2026-05-08T23:07:30Z
- Catalog DB mtime: 2026-05-08 18:23:08 -0400
- Latest audit: qB-only `0`, RT-only `7`, same-hash path drift `11`
- Fast-refresh branch complete (separate); this lane = repair only

## Done This Sprint

- Alias-aware client drift tooling landed
- Hitchhiker split tooling selected-safe and fail-closed
- Live Cinderella pilot `97343f6005da2ed8` succeeded (drift 12→11)
- All four hardening fixes (v0.8.50, 36ea583): xmlrpc int parsing,
  RT d.check_hash after repair apply, RT Case B verify_layout guard,
  verify-layout-scan command

## Safety Rules (active every session)

- `/data/media` and `/stash/media` are the same filesystem — always canonicalize
- Dry-run → tiny pilot → post-check before widening any batch
- One mutating qB/RT workflow at a time
- `~noHL` is advisory only; never mutate on it alone
