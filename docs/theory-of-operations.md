# Hashall Theory of Operations (Operator View)

## What this system does
Hashall keeps a trustworthy map of where media files live, which torrents point to them, and what actions are safe to take. It is built around a cautious loop: discover reality, build a plan, dry-run it, execute only safe actions, then verify and clean up.

## Core ideas in plain language
- **Catalog truth**: a database snapshot of files on disk (paths, sizes, hashes, devices).
- **Payload identity**: one logical content unit, even when many torrents point to it.
- **Torrent instance**: one qB torrent reference to a payload, including save path, root name, category, and tags.
- **Plan before change**: operations are expressed as plan files first, then reviewed and applied.
- **Follow-up tags**: post-apply markers track what still needs verification or cleanup.

## Operational lanes

### 1) Scan lane (filesystem truth)
Purpose: discover files and hashes so later decisions use facts, not guesses.

What it answers:
- What files exist now?
- Are hashes present and current?
- Which paths belong to which storage device?

When to use:
- Before major planning cycles.
- After large file moves outside tooling.

### 2) Payload sync lane (qB + DB alignment)
Purpose: reconcile qB torrent state with catalog payload state.

What it answers:
- Which torrents map to which payloads?
- Which payloads are incomplete because hashes are missing?
- Which roots in qB are active and where are they now?

When to use:
- Before normalize or rehome planning.
- After stale-plan failures (for example, torrent hash present in old plan but gone in qB now).

### 3) Rehome lane (stash -> pool)
Purpose: move eligible seeding content from stash to pool with guardrails.

What it does:
- Builds demotion plans for safe items.
- Relocates torrent views so seeding continues.
- Applies cleanup only when post-move safety checks pass.

Expected outcome:
- qB continues seeding from pool locations.
- source-side leftovers are either removed automatically or flagged for follow-up.

### 4) Normalize lane (pool reorganization)
Purpose: reorganize pool paths into consistent structure under `/pool/data/seeds/`.

What it does:
- Detects misplaced payload roots.
- Chooses **REUSE** when content can be represented correctly without risky data movement.
- Uses **MOVE** only when required and safe.
- Handles cross-seed style placement using tracker/category signals when available.

Expected outcome:
- Paths become consistent and predictable.
- duplicate source aliases are cleaned once torrent access is verified.

### 5) Recovery lane (non-seeding recovered data)
Purpose: classify recovered content and remove exact duplicates safely.

What it does:
- Audits recovered units into exact-duplicate / supporting / unique categories.
- Applies prune only to exact duplicates.

Expected outcome:
- recovered area shrinks without deleting unique data.

## Numbered scripts as operator "buttons"

### Rehome scripts
- **05 pilot batch**: first safe preview cycle (plan + dry-run).
- **10 guarded apply**: execute a vetted small batch with checks.
- **15 regenerate and run**: refresh candidate ordering and continue batch work.
- **20 normalize plan/dry/apply with logs**: full normalize cycle with captured logs.
- **21 normalize refresh plan**: rebuild normalize plan from current state.
- **22 recover skipped and replan**: re-sync skipped items from prior plan, then rebuild.
- **23 scan/sync/replan**: deeper recovery pass (scan roots, sync, replan).
- **24 live-prefix hash-sync/replan**: derive active prefixes from live torrent mappings, hash-upgrade those roots, then replan.

### Recovery scripts
- **05 audit recovered content**: classify recovered tree without deleting.
- **10 show latest report summary**: quick readout of last audit.
- **15 apply exact-duplicate prune**: delete only confirmed exact duplicates.
- **20 re-audit after apply**: verify post-prune state.
- **25 list files by unit**: inspect files inside a selected recovery unit.

## How to think about failures
- **"404 on torrent files"**: the plan references a torrent hash that is no longer valid in qB; refresh sync and rebuild plan.
- **`[Errno 17] File exists`**: destination view/link already exists; often an idempotency/path-collision condition that needs explicit reuse/collision handling.
- **`no_pool_torrents` in plan**: payload exists in DB, but no active pool-side torrent mapping was found for that source during planning.
- **`missing_source` during cleanup**: cleanup path is already gone; usually safe and informational.

## Why "manual action required" appears
This means the tool intentionally paused automatic deletion until seeding health is confirmed. The system usually tags affected torrents for verification follow-up so cleanup can be retried safely later.

## Practical success criteria
- Plans show mostly REUSE and minimal fallback MOVE.
- Apply completes without qB lookup errors.
- Follow-up clears verify-pending and cleanup-required tags.
- Re-planning after apply trends toward fewer candidates and fewer skips.
- Pool paths converge under consistent category/tracker-aware structure.

