# Hashall Runbook (Canonical)

Last updated: 2026-05-19
Status: canonical — consolidates CLI-OPERATIONS.md and REHOME-RUNBOOK.md

---

## Core CLI Reference

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

- `--hash-mode fast`: cheap, stores only quick hashes
- `--hash-mode full`: recomputes full SHA1/SHA256
- `--hash-mode upgrade`: incremental but backfills missing full hashes
- `--drift-policy metadata`: trusts unchanged size+mtime, skips rehashing
- `--drift-policy quick`: rechecks quick hash even if metadata unchanged
- `--drift-policy full`: fully rehashes unchanged files

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
hashall payload sync --source rt --upgrade-missing
hashall payload show <torrent_hash>
hashall payload siblings <torrent_hash>
```

`payload` commands describe qB/torrent-root content only. Scanning non-qB trees
improves hash coverage but does not create non-qB payloads.

### Content Inventory (read-only)

```bash
hashall content inventory --kind orphan --path-contains movies --sort bytes --limit 20
hashall content inventory --status complete --min-bytes 1000000000
hashall content duplicates --path-contains west.wing --limit 10
hashall content duplicates --sort count
hashall content reclaim-report --root /pool/data/seeds --root /pool/media/torrents/seeding --min-bytes 1000000000
```

`reclaim-report` is read-only and exact-match. It protects live qB payload roots
and live RT session roots by default. Use `--include-fully-protected` to audit
fully protected groups.

### Maintenance

```bash
hashall refresh --verbose --scan-hash-mode fast --drift-policy quick
hashall refresh --verbose --scan-hash-mode full --drift-policy full
hashall refresh --payload-source rt --verbose --scan-hash-mode upgrade --drift-policy quick
hashall refresh-status
hashall refresh-dashboard
hashall sha256-backfill --device pool --dry-run
hashall sha256-backfill --device pool
hashall sha256-verify --device pool
bin/run-hashall-upgrade-scans.sh
make db-refresh-fast-gated-parallel     # recommended after fast-refresh branch merged
```

- `hashall refresh` carries nested dataset scanning and dedupes covered roots.
- `hashall refresh-status`: check lock status, live PID, and latest log path.
- `hashall refresh-dashboard`: phase/task view for latest refresh log.
- Checkpoint files for upgrade sync: `~/.hashall/payload-sync-upgrade-state/`

### RT Audit

```bash
hashall rt session-audit [--session-dir] [--missing-only] [--path-contains] [--limit] [--json-output]
hashall rt state-audit [--cache-file] [--meta-file] [--cache-max-age] [--live] [--state] [--bad-only]
hashall rt repair-report --report <json> [--action-bucket] [--ready-only] [--unresolved-only] [--markdown-output]
```

- `rt state-audit` is shared-cache-backed by default (`~/.cache/silo-rt/`); use `--live` only for explicit diagnostics.
- `rt repair-report --unresolved-only --markdown-output`: regenerate operator checklist.

### qB Cache

```bash
bin/qb-cache-agent.py --status
bin/qb-checking-watch.sh --dashboard
bin/qb-start-seeding-gradual.sh --daemon --apply --min-batch 1
```

Local qB cache: `~/.cache/silo-qb/`. Read-heavy tooling prefers cached reads.
Write/mutation endpoints stay direct for freshness.

---

## Standard Operator Loop

1. Run scans for active roots.
2. Run payload sync when qB/RT state changed.
3. Generate plans (link/rehome) from current truth.
4. Dry-run, then apply.
5. Verify state and clean up follow-up tags.

---

## Rehome Safety Gates (required every apply)

- No active-download regressions on repaired/rehomed hashes.
- Source cleanup only after relocated content is validated.
- Manual-action tags remain until follow-up completes.

### RT Path Authority Tiebreaker

When qB and RT report different paths for the same hash and both clients are on the correct placement tier, RT's path is canonical — repoint qB to match RT (offline fastresume patch). Exception: if RT's path is provably non-canonical (wrong category, missing, structurally wrong), escalate for human review. See §8.4 of REQUIREMENTS.md.

### Preferred Mutation Order

`copy/verify → qB stop → offline fastresume patch → qB start → observe`

Do not use `qB setLocation` as the primary mover for dataset migration.

## Baseline Rehome Workflow

1. `hashall refresh --verbose`
2. `hashall payload sync`
3. Build rehome plan
4. Review plan outputs and blockers
5. `hashall rehome apply ... --dryrun`
6. `hashall rehome apply ... --force` (only after review)
7. Verify qB + filesystem state
8. `hashall rehome followup --cleanup` (only after verification gates pass)

## Pilot Commands

```bash
hashall rehome auto --from pool-data --to pool-media --limit 1

# Explicit root-to-root planner:
hashall rehome relocate-plan \
  --source-device pool-data \
  --source-root /pool/data/media/torrents/seeding \
  --target-device pool-media \
  --target-root /pool/media/torrents/seeding \
  -o out/rehome-plan-pool-data-to-media.json

# Audit for legacy missingFiles cohort:
hashall rehome qb-missing-audit \
  --source-root /pool/data/media/torrents/seeding \
  --target-root /pool/media/torrents/seeding
```

Plans land under `~/.logs/hashall/reports/rehome-runs/plans/`.

## Known Failure Modes

| Failure | Root Cause | Mitigation |
|---|---|---|
| Refresh appears hung | Child command waited on stdin | Always use `--yes` for non-interactive refresh |
| `ActionInfo` crash after refresh-created plan | Local import shadowed module-level type | Keep type/import at module scope |
| Mixed-root dedup during migration | Dedup operates inside both `pool/data/media` and legacy `pool/data/seeds` | Treat dedup as inode cleanup only, not convergence proof |
| qB repair selects wrong donor/root | Donor drift across roots/filesystems | Fail closed on cross-filesystem donor; require explicit allowed-root policy |
| Legacy stale-root `missingFiles` after REUSE success | `.fastresume` still pointed at old root | Audit with `qb-missing-audit`; remediate in guarded batches |

---

## Troubleshooting

- State stale → rescan and resync first.
- Content drift suspected → use `--drift-policy quick` or `full`.
- Plan conflicts with live qB → rebuild the plan.
- Command hung → `hashall refresh-status` before deleting `~/.hashall/refresh.lock`.
- Concurrent workflows → never; verify no other mutating process before starting.

---

## Script Entry Points

```
bin/scan/hashall-smart-scan
bin/scan/hashall-auto-scan
bin/scan/hashall-plan-scan
bin/scan/hashall-tune-presets
bin/tools/iowatch
```
