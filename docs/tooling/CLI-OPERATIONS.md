# Hashall CLI Operations (Canonical)

Last updated: 2026-02-28
Status: canonical

## Purpose

Single command reference for day-to-day CLI usage by operators and agents.

## Core Commands

### Scan and Catalog

```bash
hashall scan /pool
hashall scan /stash
hashall stats
hashall devices list
hashall devices show pool
```

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
hashall sha256-backfill --device pool --dry-run
hashall sha256-backfill --device pool
hashall sha256-verify --device pool
```

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
- If plan conflicts with live qB state, rebuild the plan.
- If a command appears hung, check process and DB lock status.

## Related Canonical Docs

- `docs/tooling/REHOME-RUNBOOK.md`
- `docs/operations/RUN-STATE.md`
- `docs/REQUIREMENTS.md`
