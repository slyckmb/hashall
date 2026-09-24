# qB/RT Mirror Drift — Investigation Findings & Repair Plan

**Status:** planning / design-only. No code changes in this PR.
**Date:** 2026-09-24
**Correction (2026-09-24, appended, does not rewrite the original text below):**
see [Correction: cross-seed→qB injection question is already resolved](#correction-cross-seedqb-injection-question-is-already-resolved-2026-09-24)
at the end of this document. It supersedes the "open question" framing in
Non-goals and Phase 3 regarding whether cross-seed should inject into qB.

## Objective

qBittorrent is supposed to be a passive, non-seeding mirror of rTorrent (RT is the
path/seeding authority; qB never downloads). Two problems were observed:

1. A handful of qB torrents sit `stoppedDL` at (or near) 0% progress.
2. qB's item count (5076) drifts from RT's (5048) by 28 net items, and existing
   tooling does not make that gap self-explanatory.

This PR documents the read-only investigation into both, and proposes a bounded
repair/automation plan. **No mutation was performed against qB, RT, or the repo's
tooling as part of this investigation** — all findings below come from live
read-only queries (qB Web API, RT XML-RPC, filesystem `ls`/`find`) plus repo/doc
inspection.

## Findings

### 1. Root cause of the paused/0% items

At investigation time, qB reported 12 `stoppedDL` torrents; 8 were at true 0%
progress (the other 4 are 99.9%+ complete, missing only a few MB — see
"Pre-existing stale items" below, a separate and already-partially-documented
issue).

Tracing each of the 8:

- 7 of 8 exist on **both** RT and qB, same hash, same path. RT reports
  `complete=1`, actively seeding (`active=1`). The data is genuinely present on
  disk at the qB `save_path` — file sizes match the torrent size exactly.
- None of the 8 carry hashall's mirror-tool fingerprints: no
  `hashall-rt-qb-mirror` / `hashall-client-drift` qB tags, no `~rt-mirrored` /
  `QB_MIRROR_TAG` in RT's `custom2`, and none appear in
  `~/.cache/hashall/rt-qb-mirror/apply.jsonl` (last written in June). They were
  **not** added by hashall's `rt-qb-mirror` pipeline.
- All 8 are `category=cross-seed`, added within a ~25 minute window on
  2026-09-08 (`added_on` 19:21 and 19:46). They were injected directly into
  **both** RT and qB by **cross-seed itself** (its own dual-client injection
  feature), bypassing hashall's RT→qB pipeline entirely.
- Cross-seed adds them to qB stopped, without a hash check. qB has no
  independent way to know the data is complete, so it reports 0% and never
  re-verifies on its own.

This exact failure mode was previously documented at much larger scale in
`docs/GATE0-STOPPDL-AUDIT.md` (2026-06-18, 115 `stoppedDL` items, mostly
cross-seed-injected). That audit found recheck alone often insufficient — 4/5
sampled `HEALTHY` items stayed `stoppedDL` after a plain recheck — and
suspected `set_location` (to refresh qB's cached path/metadata) was needed
first. **That hypothesis was never implemented or tested; the audit's own
recommendations were never actioned.**

**Risk:** these torrents are currently *stopped*, so there is no active harm
today. But if any is ever resumed (manual mistake, a qBittorrent scheduler
rule, share-limit automation, a qbit_manage category action), qB will actually
start downloading the full multi-GB file on top of already-complete hardlinked
data — a direct violation of the "qB never downloads" invariant this project
already treats as load-bearing (see repo memory: rogue-code cross-seed path
breaks).

### 2. Pre-existing stale items (not new, but adjacent)

The 4 near-100% `stoppedDL` items (Dexter S02, Dexter S07, River Monsters,
Transformers — missing 1–16 MB each) are the **same hashes** listed in
GATE0-STOPPDL-AUDIT.md's `RT_INCOMPLETE` table from June, still unresolved
3+ months later. They were explicitly deferred ("investigate separately") and
never followed up on.

### 3. The 5076 vs 5048 item-count diff

`client-drift audit --policy-mode rt-authoritative-mirror` (read-only) reports:

```
QBit: 5076  RTorrent: 5048  Common: 5037
QB-only: 39  RT-only: 11
Path drift: 15  high=0  medium=0  low=15
```

- **RT-only (11):** expected/normal — new RT items not yet mirrored into qB.
  This is exactly the candidate set `rt-qb-mirror sync` / `make
  rt-qb-mirror-apply` exists to consume.
- **QB-only (39):** splits into 13 flagged `remove from qb` (high confidence,
  safe orphaned mirrors) and 26 `manual review / low confidence` (mostly
  `rt_authoritative_mode_does_not_import_from_qb_by_default` — qB-side items
  under the ARR mirror root that policy deliberately won't auto-import into RT
  without a human look).

The net 39 − 11 = 28 matches the observed count gap. The gap itself is not a
bug — it is the accumulated backlog of legitimate `manual review` and
un-synced `RT-only` rows, because nothing currently runs the sync/audit on a
schedule (see Finding 5).

### 4. Blind spot in `client-drift audit`

`client-drift audit` only classifies by **presence**/**path** drift
(`rt_only`, `qb_only`, `path_drift`). A torrent present on **both** sides at
the correct path but stuck at 0%/unverified in qB is invisible to it — none
of the 7 both-sides-present broken items from Finding 1 appeared anywhere in
the audit's output. This is the primary reason the 0% items went unnoticed:
the tool that's supposed to keep qB aligned with RT has no health check for
qB-side torrent *state*, only membership/path.

### 5. No automation anywhere in the RT→qB pipeline

- `rt-qb-mirror enqueue` documents an `rt-finished-hook` source, but the live
  `.rtorrent.rc` (`/dump/docker/gluetun_qbit/rtorrent_vpn/rtorrent/.rtorrent.rc`
  — an untracked runtime config directory, not a git repo) has no such hook
  wired up. The queue/enqueue code path exists but has never been connected.
- There is no cron/systemd timer running `rt-qb-mirror sync` or `client-drift
  audit` (checked `systemctl --user list-timers`; only an unrelated
  `hashall-payload-orphan-snapshot.timer` exists).
- Everything in this pipeline (`make rt-qb-mirror-apply`, `make
  client-drift-audit`) is fully manual. Drift and unverified mirror torrents
  accumulate silently between whenever an operator happens to run them.

### 6. Two independent, uncoordinated RT→qB injection paths

For `category=cross-seed` items specifically, both hashall's mirror tool
*and* cross-seed's own native dual-client injection can add the same content
to qB. hashall has no visibility into cross-seed's injections (no tags set,
no journal entry, no verification step run), so it can neither track nor
verify what cross-seed put there. This is the direct cause of Finding 1.

### 7. `_apply_client_drift_mirror_rows` / `_warn_stopped_dl` narrowness

- `_warn_stopped_dl` only scans the current run's `events` for `status ==
  "ok"` (freshly-added) torrents that ended up `stoppedDL`. It does not check
  `already_present` rows, so a previously-added-but-still-unverified mirror
  torrent produces no warning on subsequent runs.
- `recheck_after_add` defaults to `False` and `verify_timeout` defaults to
  `0` (`0.0` in `client-drift-apply` too). Items added via hashall's own
  mirror tool can therefore sit unverified indefinitely unless an operator
  explicitly passes `--recheck-after-add --verify-timeout N --wait-for-check`
  on every invocation. There is no "eventually reconcile / catch up on
  unverified rows" pass.

## Cross-repo / infra context (read-only, no changes anticipated here)

- **`slyckmb/silo`** (`/home/michael/dev/tools/silo/`) owns the shared qB/RT
  polling cache daemons (`silo-cache-daemon.py`, `silo-rt-cache-daemon.py`)
  that `client-drift audit` and `rt-qb-mirror` read by default
  (`~/.cache/silo-qb/torrents-info.json`,
  `~/.cache/silo-rt/torrents.json`, per `docs/CROSS-REPO-QB-HELPER-INSTRUCTIONS.md`).
  All findings above were cross-checked against **live** qB/RT API calls, not
  just the cache, so cache staleness is not the cause of what's documented
  here. `silo/DAEMON_ISSUES.md` has no existing entry for this failure mode —
  confirmed no duplicate/owned tracking exists there.
- The `.rtorrent.rc` hook target for Finding 5 lives in an **untracked**
  runtime deployment directory (`/dump/docker/gluetun_qbit/...`), not a git
  repository — wiring a hook there is a local config edit, not a
  cross-repo PR.
- No `slyckmb/projects` Mission or issue references this work (checked via
  `gh issue list --search hashall`) — this is bounded, single-repo
  (`hashall`) work with no cross-owner coordination requirement. If Phase 3
  (below) later decides the periodic scan is better owned by silo (e.g.
  daemon-side state-change detection instead of a hashall-side poll), that
  would be scoped as a separate silo-repo follow-up, not folded into this
  plan.
- `docs/chatrap-dispatch-replacement-intake.md` confirms `chatrap dispatch` is
  deprecated in this repo in favor of Airo's `pr-agent`; not applicable here
  since this PR's implementation work is direct manager execution, no
  delegated dispatch.

## Non-goals

- This PR does not touch `cli.py`, `client_drift.py`, or any runtime
  behavior. It is documentation only.
- Deciding whether to disable cross-seed's native dual-client injection
  (vs. teaching hashall to detect/adopt it) is an open question for Phase 3,
  not resolved here.
- No qB/RT/filesystem mutation of the specific 8 stuck torrents is performed
  by this PR; that is Phase 2 below, a separate follow-up PR.

## Proposed plan (follow-up PRs, in order)

**Phase 1 — close the `client-drift audit` blind spot** (Finding 4; highest
leverage, moderate effort)
- Add a qB-torrent-health dimension to `client-drift audit` for `Common`
  (both-sides-present) rows: flag any qB torrent not in a healthy
  `stoppedUP`/complete state while RT reports `complete=1` (new verdict class,
  e.g. `qb_unverified_mirror`). This alone would have surfaced the Finding 1
  items without a special one-off investigation.

**Phase 2 — remediate the current 8 stuck items + the 4 stale June leftovers**
(Findings 1–2; low risk, low effort, needs live qB/RT mutation — separate PR)
- Confirm data integrity per item (piece-level, not just size).
- Test the June audit's untested `set_location`-before-recheck hypothesis;
  re-pause immediately after recheck completes; do not leave them resumable
  while unverified.
- Close out the 4 stale near-100% items from GATE0-STOPPDL-AUDIT.md's
  `RT_INCOMPLETE` table.

**Phase 3 — close the automation gap** (Findings 5–6; moderate effort,
biggest long-term payoff)
- Wire the existing but unused `rt-finished-hook` → `rt-qb-mirror enqueue` →
  `process-queue` pipeline into the live `.rtorrent.rc`, or add a systemd
  timer running `client-drift audit` + `rt-qb-mirror sync --apply
  --recheck-after-add --wait-for-check` on a schedule (e.g. every 15–30 min).
- Explicitly decide hashall's relationship to cross-seed's direct-to-qB
  injection: detect/adopt+verify cross-seed's own additions into the same
  tracked/tagged state, or disable cross-seed's dual injection in favor of
  hashall being the sole RT→qB path.

**Phase 4 — UX/efficiency** (Finding 7; small, incremental)
- `rt-qb-mirror sync`/`process-queue` should warn on `already_present` rows
  whose live qB state isn't healthy, not just newly-`ok`-added ones.
- Default `--wait-for-check` on for interactive apply commands, or make its
  absence loud, since "added and never verified" is the actual failure mode
  observed twice now (June and September).
- Surface the qb_only safe/manual-review split directly in `client-drift
  audit`'s summary line instead of requiring a full per-row grep to derive it.

## Acceptance criteria for this PR

- [ ] Findings above accurately reflect live-queried evidence (independent
      reviewer re-derives at least the Finding 1 root cause and the Finding 3
      count breakdown from the cited commands/tools).
- [ ] No code/runtime changes included — doc-only diff.
- [ ] Plan is durable enough that a fresh session, days later, could pick up
      Phase 1 without rehydrating this investigation from chat history.

## References

- `docs/GATE0-STOPPDL-AUDIT.md` — prior (2026-06-18) audit of the same failure
  mode at scale; recommendations never actioned.
- `docs/CROSS-REPO-QB-HELPER-INSTRUCTIONS.md` — silo shared-cache contract.
- `src/hashall/cli.py` — `client-drift` and `rt-qb-mirror` command groups
  (`_load_client_drift_report`, `_select_client_drift_mirror_rows`,
  `_apply_client_drift_mirror_rows`, `_warn_stopped_dl`).
- `src/hashall/client_drift.py` — drift classification logic.

## Correction: cross-seed→qB injection question is already resolved (2026-09-24)

The original Non-goals section deferred "should cross-seed inject into qB at
all" as an open Phase 3 decision. That framing was wrong — the question was
never actually investigated against cross-seed's own configuration before
this plan was written. It has now been checked, and the answer already
exists in a sibling repo this plan failed to hydrate on.

**Cross-seed is v7, config is DB-backed (no `config.js` file — it's driven
entirely by cross-seed's own webui now), and qBittorrent is already
configured `readonly` there.** Live query of
`/dump/docker/cross-seed/cross-seed.db` (`settings.settings_json`):

```
torrentClients = ['qbittorrent:readonly:http://...@gluetun:9003', 'rtorrent:http://gluetun:8000/RPC2']
```

A `readonly` client is a search-match source for cross-seed, never an
injection target. This was independently corroborated in
**`slyckmb/docker` issue #18** ("cross-seed: resolve v7 health warnings and
injection/client errors") — **issue is still OPEN as of this writing**, kept
open for unrelated operator/external gates (MyAnonamouse credential refresh,
DocsPedia cookie refresh, tracker-timeout retests), not for anything
qB/cross-seed-injection related. Its 2026-09-22 investigation comment
verbatim records: *"qBittorrent: healthy; cross-seed login succeeds,
configured read-only,"* and the same comment's history shows the last real
cross-seed→qB injection batch was **2026-09-08 — "Injected 28/34
torrents"** — the exact date and batch that produced the 8 stuck 0% items in
Finding 1. The `readonly` finding itself is solid; only its remaining open
status (not "closed") is corrected here.

**Revised understanding:**

- The 8 stuck items are **one-time historical residue** from the last batch
  that landed *before* `readonly` was set (2026-09-08, two weeks before
  `readonly` was confirmed healthy on 2026-09-22) — not evidence of an
  ongoing leak. Phase 2 remediation is a one-time cleanup, not a recurring
  pattern to design around.
- Phase 3's "explicitly decide hashall's relationship to cross-seed's
  direct-to-qB injection" is **no longer an open design decision** — the
  infra-level fix (readonly) is already in place and independently verified
  healthy as of 2026-09-22. Phase 3 should instead be: confirm `readonly`
  continues to hold (a cheap periodic check, e.g. as part of Phase 1's health
  scan or a `slyckmb/docker`-owned check — not a hashall redesign), and drop
  the "disable cross-seed's dual injection" branch of the original decision
  entirely. The "teach hashall to detect/adopt cross-seed's own injections"
  branch is now lower priority, since new dual-injections into qB should not
  be occurring going forward.
- This correction does not change Findings 1–7, Phase 1, Phase 2, or Phase 4
  above — only the Non-goals framing and the second bullet of Phase 3.

**Process note:** this is exactly the kind of cross-repo context the original
plan's "no Mission/cross-repo coordination needed" conclusion should have
prompted a check against — a sibling-repo issue directly answered an "open
question" this plan deferred. No Mission is needed retroactively (the
question is resolved, not still requiring cross-owner coordination), but
future planning docs in this repo touching cross-seed behavior should check
`slyckmb/docker` issues first.
