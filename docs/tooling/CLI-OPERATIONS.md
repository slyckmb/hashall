# Hashall CLI Operations (Canonical)

Last updated: 2026-02-28
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

### Maintenance

```bash
hashall refresh --verbose --scan-hash-mode fast --drift-policy quick
hashall refresh --verbose --scan-hash-mode full --drift-policy full
hashall sha256-backfill --device pool --dry-run
hashall sha256-backfill --device pool
hashall sha256-verify --device pool
```

### qB Cache / Compatibility

```bash
bin/qb-cache-agent.py --status
bin/qb-checking-watch.sh --dashboard
bin/qb-start-seeding-gradual.sh --daemon --apply --min-batch 1
```

Guidance:

- `hashall` now owns a local qB shared-cache implementation in `src/hashall/qb_cache.py`.
- The local cache uses the shared Python qB client in `src/hashall/qbittorrent.py`, so qB app/API version detection and state alias normalization happen in one place.
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

## Related Canonical Docs

- `docs/tooling/REHOME-RUNBOOK.md`
- `docs/operations/RUN-STATE.md`
- `docs/REQUIREMENTS.md`
