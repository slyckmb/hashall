# Recovery Entry (Compact-Safe)

Use this when context is lost or a new agent is starting cold.

## Quick Orient

1. Read `docs/SPRINT.md` — what we are doing right now
2. Read `docs/operations/RUN-STATE.md` — live evidence baseline
3. Read `SESSION.md` — last step saved by the previous agent

## Invariants (never forget)

- `/data/media` and `/stash/media` are the same mounted `stash/media` filesystem — aliases, never independent copies
- ARR-hardlinked items → stash (`/data/media` / `/stash/media`)
- Non-ARR-hardlinked seeded payloads → pool (`/pool/media`)
- `~noHL` tags are advisory only; confirm real filesystem state before any mutation
- One mutating qB/RT workflow at a time
- Dry-run → tiny pilot → post-check before widening

## Current Repair Queue (as of 2026-05-08)

- easy: `5c86280a99d10071` Spider-Man Into the Spider-Verse
- medium: `20555f704e0ae477`, `e2a7eab3a5be76f7`, `1a06655541134463`,
  `4052607092357bfe`, `2a4e075ecf0962ba`
- hard: `4f454ed3bdf830f0`, `2fb25fdf2ef20ae5`, `29e2b889867a8fbb`,
  `a5a2b78798009b38`, `c7845e03fe21e7fa`

## Last Evidence Snapshot (2026-05-08)

- qB: 5203 rows, daemon_live, fetched 2026-05-08T23:07:42Z
- RT: 5210 rows, daemon_live, fetched 2026-05-08T23:07:30Z
- Catalog DB mtime: 2026-05-08 18:23:08 -0400
- Drift: qB-only `0`, RT-only `7`, same-hash path drift `11`

## Recommended Refresh Command

```bash
make db-refresh-fast-gated-parallel
```

## Worktree Context

Active repair lane: `cr/hashall-20260508-043305-claude`
(fast-refresh work landed separately; this branch is repair-only)

## Big-Picture Cleanup TODO

1. Finish `cross-seed-link → cross-seed` (most done; last exceptions need repair)
2. Finish `orphaned_data → orphans` (canonical orphan folder naming)
3. Clean remaining broken live torrents (DocsPedia leftovers, stoppedDL items, Dexter pair)
4. Drain torrent payloads out of `/pool/data` (temporary residue, not a final home)
5. Keep stash-vs-pool placement consistent (hardlink-anchored = stash; otherwise = pool)
6. Remove stash/pool duplicates in steady state
7. Fix hitchhikers (multiple hashes sharing one payload tree → split with hardlinks)
8. Keep qB and RT aligned after every live change
9. Clean stale residue and empty legacy paths after moves
10. Update code/scripts/docs still referencing `cross-seed-link` or `orphaned_data`
11. Finish repair/verification contract (stronger handling for degraded controller states)
12. End in intended steady state: canonical `stash/pool` layout, no `cross-seed-link`, no
    `orphaned_data`, no torrent payloads on `/pool/data`
