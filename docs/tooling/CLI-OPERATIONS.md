# Hashall CLI Operations (Canonical)

Last updated: 2026-03-25
Status: canonical

## Purpose

Single command reference for day-to-day CLI usage by operators and agents.

## Core Commands

### Scan and Catalog

```bash
hashall scan /pool
hashall scan /pool --hash-mode fast --drift-policy metadata
hashall scan /pool --hash-mode fast --drift-policy quick
hashall scan /pool --hash-mode full --drift-policy full
hashall scan /stash
hashall stats
hashall devices list
hashall devices show pool
```

Guidance:

- `--hash-mode fast` is cheapest and stores only quick hashes.
- `--hash-mode full` recomputes full SHA1/SHA256 for scanned files.
- `--hash-mode upgrade` preserves normal incremental behavior but backfills missing full hashes.
- `--drift-policy metadata` trusts unchanged size+mtime and skips rehashing.
- `--drift-policy quick` rechecks the quick hash even when metadata is unchanged and escalates to full hashing if drift is detected.
- `--drift-policy full` fully rehashes unchanged files in the scan scope.

### Link Deduplication

```bash
hashall link analyze --device /pool
hashall link plan "Monthly dedupe" --device /pool
hashall link show-plan 1
hashall link execute 1 --dry-run
hashall link execute 1
```

### Payload Identity

```bash
hashall payload sync
hashall payload show <torrent_hash>
hashall payload siblings <torrent_hash>
```

Important scope note:

- `payload` commands describe qB/torrent-root content only.
- Scanning non-qB trees improves the `files_*` inventory and hash coverage, but does not by itself
  create non-qB `payloads` under the current model.
- Broader duplicate folder-tree / donor discovery for non-qB roots is a separate inventory feature
  requirement, not a side effect of `payload sync`.

Current read-only CLI in this area:

- `hashall content inventory`
- `hashall content duplicates`
- `hashall content donors --torrent <hash>`
- `hashall content reclaim-report`

Current status:

- These commands read existing `files_*`, `payloads`, and `torrent_instances` metadata only.
- They do not yet materialize a durable non-qB `content_roots` table.
- Current root discovery now prefers payload-like leaf content roots:
  - recurse through broad container dirs
  - treat loose files as single-file roots where appropriate
  - keep real leaf directories grouped
- This is good enough for first donor/duplicate reporting, but still needs durable inventory writes
  and stronger filtering/ranking.
- Current operator-friendly filters include:
  - `hashall content inventory --kind orphan --path-contains movies --sort bytes --limit 20`
  - `hashall content inventory --status complete --min-bytes 1000000000`
  - `hashall content duplicates --path-contains west.wing --limit 10`
  - `hashall content duplicates --sort count`
  - `hashall content reclaim-report --root /pool/data/seeds --root /pool/media/torrents/seeding --min-bytes 1000000000`

Reclaim-report guidance:

- `hashall content reclaim-report` is read-only and exact-match-only.
- It ranks duplicate non-qB roots into:
  - one preferred `keep` path
  - one or more `purge` candidates
- It now protects live qB payload roots by default:
  - if a duplicate root overlaps a live qB payload root, that root becomes the `keep` target
  - fully protected duplicate groups are hidden by default
  - use `--include-fully-protected` to audit those groups explicitly
- Current path preference is conservative:
  - prefer `/pool/media/...`
  - then `_rehome-unique`
  - then `/pool/data/cross-seed-link`
  - then `/pool/data/cross-seed`
  - then `/pool/data/seeds`
  - then `/pool/data/orphaned_data`
  - then `/pool/data/RecycleBin`
- Use it to feed a separate review/apply script; do not treat it as a blind deletion command.

### Maintenance

```bash
hashall refresh --verbose --scan-hash-mode fast --drift-policy quick
hashall refresh --verbose --scan-hash-mode full --drift-policy full
hashall refresh-status
hashall refresh-dashboard
hashall sha256-backfill --device pool --dry-run
hashall sha256-backfill --device pool
hashall sha256-verify --device pool
```

Guidance:

- `hashall refresh-status` is the fast operator check for:
  - current `refresh.lock` metadata
  - whether the lock PID is still live
  - any other live refresh holder processes detected from `/proc`
  - the latest refresh log path
- `hashall refresh-dashboard` renders the phase/task view for the latest refresh log by default.
- `hashall payload sync --upgrade-missing` now writes per-scope resume checkpoints under:
  - `~/.hashall/payload-sync-upgrade-state/`
- Those checkpoint files are:
  - reused automatically on the next matching upgrade scope
  - ignored when the checkpoint is stale relative to current DB state
  - removed automatically when the upgrade stage completes cleanly

### qB Cache / Compatibility

```bash
bin/qb-cache-agent.py --status
bin/qb-checking-watch.sh --dashboard
bin/qb-start-seeding-gradual.sh --daemon --apply --min-batch 1
```

Guidance:

- `hashall` now owns a local qB shared-cache implementation in `src/hashall/qb_cache.py`.
- The local cache uses the shared Python qB client in `src/hashall/qbittorrent.py`, so qB app/API version detection and state alias normalization happen in one place.
- The shared Python qB client now falls back to cached server-profile and per-hash torrent data when qB is temporarily slow or authentication is timing out.
- The shared Python qB client now falls back to `.torrent` files in qB `BT_backup` when an older qB build does not implement `/api/v2/torrents/export`.
- The local cache lives under `~/.cache/hashall-qb/`.
- `bin/qb-checking-watch.sh` now defaults to cached reads; use `--no-cache` only for direct-mode debugging.
- `bin/qb-start-seeding-gradual.sh` now defaults to cached `torrents/info` reads; use `--no-cache` only when debugging cache behavior.
- Read-heavy list/status tooling should prefer cached reads; write/mutation endpoints can remain direct when immediate freshness matters.

## Standard Operator Loop

1. Run scans for active roots.
2. Run payload sync when qB state changed.
3. Generate plans (link/rehome) from current truth.
4. Dry-run, then apply.
5. Verify state and clean up follow-up tags.

## Script Entry Points

Canonical script locations:

- `bin/scan/hashall-smart-scan`
- `bin/scan/hashall-auto-scan`
- `bin/scan/hashall-plan-scan`
- `bin/scan/hashall-tune-presets`
- `bin/tools/iowatch`

Root names remain as compatibility wrappers.

## Troubleshooting Rules

- If state is stale, rescan and resync first.
- If content drift is suspected, do not trust metadata-only scans; rerun scan/refresh with `--drift-policy quick` or `--drift-policy full`.
- If plan conflicts with live qB state, rebuild the plan.
- If a command appears hung, check process and DB lock status.
- For refresh-specific triage, run `hashall refresh-status` before deleting `~/.hashall/refresh.lock`.

## Related Canonical Docs

- `docs/tooling/REHOME-RUNBOOK.md`
- `docs/operations/RUN-STATE.md`
- `docs/REQUIREMENTS.md`
