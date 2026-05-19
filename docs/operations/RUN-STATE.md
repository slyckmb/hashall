# Operational Run State

Last updated: 2026-05-08

## 2026-05-08 Repair Project Handoff Snapshot

This is the current continuation point for the repair lane. The separate
fast-refresh optimization project was completed by another branch and is no
longer the active work lane here.

Primary goal:

- keep qBittorrent and rTorrent in sync for seeded datasets
- clean up same-hash qB/RT save-path drift
- preserve the policy that data belongs on `/pool/media` when it is not
  hardlinked into ARR media libraries, and on `/data/media` / `/stash/media`
  when it is hardlinked into ARR libraries
- reduce manual/error items while avoiding destructive decisions without
  direct filesystem proof

Critical context:

- `/data/media` and `/stash/media` are equivalent mount aliases for the same
  `stash/media` filesystem. They must be canonicalized/deduped before path,
  placement, copy-count, anchor, or cleanup decisions.
- qB `~noHL` tags from qbit_manage are advisory evidence only. They are useful
  for ranking, but never enough for destructive repair decisions by themselves.
- Always confirm actual filesystem state before live mutation:
  - path exists
  - device/inode/nlink
  - ARR samefile/hardlink anchor if placement depends on ARR ownership
  - sibling payloads
  - qB and RT current runtime/cache state
  - rollback target
- Treat broad old notes about `cross-seed-link`, `orphaned_data`, `/pool/data`,
  or zero-capacity blockers as historical unless a new live read contradicts
  this May 8 baseline.

Recent fast-refresh branch reviewed:

- branch: `cr/hashall-20260508-043305-claude`
- useful commits/options:
  - `db-refresh-fast`
  - `db-refresh-fast-gated`
  - `db-refresh-fast-parallel`
  - `db-refresh-fast-gated-parallel`
  - changed-scope scan result tracking
  - optional dedup gating
  - optional parallel root scanning
  - observability metrics
- recommended future refresh command for repair evidence, after merging that
  branch or running from it:

  ```bash
  make db-refresh-fast-gated-parallel
  ```

- caveat: the optimized refresh is sufficient for current qB/RT/cache/catalog
  freshness, but it does not remove the need for selected per-hash repair
  evidence before mutation.

Freshness/evidence baseline observed on 2026-05-08:

- qB cache:
  - file: `~/.cache/silo-qb/torrents-info.json`
  - meta: `~/.cache/silo-qb/torrents-info.meta.json`
  - fetched: `2026-05-08T23:07:42Z`
  - rows: `5203`
  - source: `daemon_live`
  - consecutive failures: `0`
- RT cache:
  - file: `~/.cache/silo-rt/torrents.json`
  - meta: `~/.cache/silo-rt/torrents.meta.json`
  - fetched: `2026-05-08T23:07:30Z`
  - rows: `5210`
  - source: `daemon_live`
  - consecutive failures: `0`
- catalog:
  - path: `~/.hashall/catalog.db` -> `.state/catalog.db`
  - target DB mtime: `2026-05-08 18:23:08 -0400`
  - recent completed scan sessions around `2026-05-08 18:14`
  - recent roots include `/stash/media`, `/pool/media`, `/pool/data`,
    `/pool/media/torrents/seeding`, and `/mnt/hotspare6tb`
  - recent scan sessions reported `0` added, `0` updated, and `0` deleted rows
    for the visible root sessions
- stale-looking lock note:
  - `~/.hashall/refresh.lock` was written by the Claude fast-refresh worktree at
    `2026-05-08T18:14:28-04:00`
  - recorded pid `1541349` was not running when checked
  - do not delete/clear locks casually; recheck process state first

Current read-only repair audit from fresh evidence:

```bash
make client-drift-audit LIMIT=0
```

Result:

- qB rows: `5203`
- RT rows: `5210`
- common hashes: `5203`
- qB-only: `0`
- RT-only: `7`
- same-hash qB/RT path drift: `11`
- action counts: `manual_review=18`

Current ranked same-hash path-drift queue:

Easy:

- `5c86280a99d10071`
  `Spider-Man.Into.the.Spider-Verse.2018.Alternate.Universe.Cut...`
  - desired placement: `stash`
  - ARR status: linked to ARR
  - qB has `~noHL` advisory tag
  - qB path:
    `/data/media/torrents/seeding/_qb-repair-v2/5c86280a99d1007104452b2f72d0d686e092e2f8`
  - RT path:
    `/data/media/torrents/seeding/cross-seed/Aither (API)`
  - reason it is easy: both clients are already on the required storage class;
    this is a canonical path choice problem, not a pool/stash migration problem
  - current blocker: selected audit still needs hardlink-anchor evidence before
    mutation

Medium:

- `20555f704e0ae477` Bottle Shock
- `e2a7eab3a5be76f7` Here
- `1a06655541134463` Top Gun
- `4052607092357bfe` Twisters
- `2a4e075ecf0962ba` V for Vendetta

Interpretation:

- mostly both-client-on-stash rows where qB and RT disagree on the exact tree
- several have sibling payload roots
- next step is canonical tree/shape choice, not blind repoint

Hard:

- `4f454ed3bdf830f0` Alien Resurrection
- `2fb25fdf2ef20ae5` Novitiate
- `29e2b889867a8fbb` Vigen Guroian
- `a5a2b78798009b38` Wilding
- `c7845e03fe21e7fa` Twin Peaks S01

Interpretation:

- Alien is a pool/stash and N->1 hitchhiker issue, not a simple save-path
  repoint.
- Novitiate, Vigen, and Wilding are desired-pool rows where both clients are
  currently on stash, so they need rehome/donor planning before client repoint.
- Twin Peaks has multi-file/N->1 payload complexity.

Current RT-only rows:

- `15a56906462ad267` Ignorance is Strength.epub
- `395b3ff95d860eb7` Saturday Night 2024 REPACK under `YUSCENE (API)`
- `5fbb9f5cfe372cbf` War is Peace.epub
- `89465b82fca588cf` Saturday Night 2024 REPACK under `OnlyEncodes (API)`
- `daa0978ebef4cd67` Lao Tzu - Ursula K. Le Guin.epub
- `e4132f64e2e13839` Outlander S08E09
- `f0d2a999fb7e9daa` Freedom is Slavery.epub

Policy status for RT-only rows:

- all are `manual_review`
- blocker is `no_policy_says_rt_only_should_be_mirrored_or_removed`
- do not mirror/remove them until the operator chooses a policy for RT-only
  rows

Completed repair phases / DONE:

1. Critical alias drift was identified and corrected in code.
2. `/data/media` and `/stash/media` alias handling was hardened in
   `client-drift` logic and tests.
3. Selected bounded filesystem anchor fallback was added.
4. Same-hash path-drift audit and ranking tooling now exists:
   - `make client-drift-audit`
   - `make client-drift-path-drift`
   - `make client-drift-rank`
   - `make client-drift-selected HASH=<hash>`
5. qB/RT selected repair wrappers now exist for supported directions:
   - `make client-drift-rt-to-qb-dry HASH=<hash>`
   - `make client-drift-rt-to-qb-apply HASH=<hash>`
   - `make client-drift-qb-to-rt-dry HASH=<hash>`
   - `make client-drift-qb-to-rt-apply HASH=<hash>`
6. Hitchhiker split tooling was hardened to fail closed:
   - selected `--hash` / `--payload-id` options
   - execute requires selection
   - blocked selected groups are reported instead of silently omitted
   - blocked execute exits nonzero
7. Live pilot already completed:
   - hash: `97343f6005da2ed8` Cinderella
   - action: RT repointed from stash path to qB pool path
   - live RT eventually confirmed target path despite an XMLRPC timeout
   - selected drift dropped to `0`
   - full drift count dropped from `12` to `11`

Open TODOs:

1. Do the next selected repair pilot on the easy Spider-Man row, but dry-run and
   inspect first.
2. Build or use a selected canonical-tree evidence table for the medium
   stash/stash rows.
3. Keep Alien out of simple repoint automation until a selected hitchhiker /
   unique-view plan chooses the correct stash ARR-anchored source and target.
4. For desired-pool hard rows, create rehome-before-repoint plans rather than
   direct client path changes.
5. Decide RT-only policy for the 7 rows: mirror to qB, intentionally leave
   RT-only, repair, or remove.

Recommended next phase strategy:

### Phase R1: Selected Spider-Man Evidence And Dry-Run

Goal:

- prove one low-risk same-storage-class path alignment row end to end without
  guessing.

Commands to start:

```bash
make client-drift-selected HASH=5c86280a99d10071 JSON=1
make client-drift-rank HASH=5c86280a99d10071
```

Then collect direct filesystem evidence:

- `stat` qB content path and RT content path
- check whether they are samefile or distinct hardlink families
- scan ARR library roots for samefile anchor
- confirm qB tags and RT/qB states from fresh caches
- identify exact rollback path

Human gate:

- operator reviews the selected evidence and approves which side should be
  canonical before any apply.

### Phase R2: One-Hash Apply Pilot

Goal:

- apply exactly one selected path alignment only after R1 evidence is complete.

Rules:

- one hash only
- dry-run immediately before apply
- no broad repair
- no deletion
- postcheck qB path/state, RT path/state, content existence, and drift count
- rollback target must be known before apply

### Phase R3: Medium Stash/Stash Canonical Table

Goal:

- prepare the 5 medium rows for safe human choice.

Output per hash:

- qB save/content path
- RT save/content path
- device/inode/nlink
- file count and size
- ARR samefile anchor paths
- sibling payload roots
- qB tags including `~noHL`
- recommended canonical tree or `manual`

### Phase R4: Hard Rows

Goal:

- handle rehome/hitchhiker cases separately from simple qB/RT repoints.

Rules:

- Alien requires selected hitchhiker planning first.
- Novitiate, Vigen, and Wilding require pool unique-view/rehome planning first.
- Twin Peaks needs multi-file/N->1 payload review before mutation.

### Phase R5: RT-Only Policy Lane

Goal:

- decide what to do with the 7 RT-only rows.

Do not mutate until policy is explicit.

---

## Historical Sections

Pre-May-8 operational notes archived at:
`docs/archive/2026-doc-reduction-may/RUN-STATE-full.md`
