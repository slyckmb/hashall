# Hashall Runbook (Canonical)

Last updated: 2026-05-26
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

## Canonical Path Repair Protocol

Non-canonical save paths fall into 5 classes. Check counts with `make canonical-tree-report`.
Safe repair order: Class 4 → 2 → 1 → 3 → 5.

| Class | Pattern | Repair action |
|---|---|---|
| 1 | `cross-seed/<40-hex-hash>/` | Identify tracker via RT XMLRPC → rename dir → repoint RT + qB |
| 2 | `cross-seed/other/` | Same as Class 1 |
| 3 | `cross-seed/_<name>/` | Same as Class 1 (0 items as of 2026-05-26) |
| 4 | `_rehome-unique/<hash>/` | Use `save-path-repair` tool (see below) |
| 5 | `_qb-finish/`, `_qb-unique-repair/`, `_qb-repair-v2/` | Investigate per-item state, then repoint |

### Class 1 / 2 / 3 — tracker-name repairs

```bash
# 1. Get hashes and current paths
make canonical-tree-report

# 2. Look up tracker for a hash via RT XMLRPC
python3 -c "
import xmlrpc.client
s = xmlrpc.client.ServerProxy('http://127.0.0.1:18000/')
print(s.d.tracker.url('<hash>'))
"

# 3. Rename dir on filesystem (data/stash are same fs — plain mv)
mv <seeding-root>/cross-seed/<old-name>/<content> <seeding-root>/cross-seed/<tracker-name>/<content>

# 4. RT repoint
hashall rt repoint --hash <hash> --target <seeding-root>/cross-seed/<tracker-name> --apply

# 5. qB set_location (parent dir only — NOT the content dir)
# via hashall client-drift or direct qB API call

# 6. Verify
make client-drift-audit ANCHOR_SCAN=200000  # expect drift=0
```

Stop conditions: any `drift > 0` after a repoint; any RT recheck failure.

### Class 4 — `_rehome-unique/<hash>/` repairs

**Always dry-run before execute. This tool caused the 2026-05-20 incident when run without review.**

Before running: categorize each item:
- **Group A** — data physically exists in `_rehome-unique/<hash16>/` → tool moves it + repoints
- **Group B** — `_rehome-unique/<hash16>/` dir is empty → safe to delete; just repoint clients
- **Group C** — nested under `cross-seed/<tracker>/_rehome-unique/` → not found by scanner; handle manually

```bash
# Dry-run — review every line before proceeding
make save-path-repair-dry LIMIT=0

# Pilot (first 2 only)
make save-path-repair-apply LIMIT=2
make client-drift-audit ANCHOR_SCAN=200000   # must show drift=0 before continuing

# Batch remainder
make save-path-repair-apply LIMIT=0
```

Recovery if something goes wrong: `.bak-repair` files are written alongside each patched fastresume.
```bash
# Restore a single fastresume from backup
cp /dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/<hash>.fastresume.bak-repair \
   /dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup/<hash>.fastresume
```

### Class 5 — staging dir repairs

Items in `_qb-finish/`, `_qb-unique-repair/`, `_qb-repair-v2/` are qB repair staging paths that were
never promoted to canonical locations. Assess each before touching:

```bash
# Get the list
make canonical-tree-report

# Check qB + RT state for each hash
make client-drift-audit ANCHOR_SCAN=200000

# For items showing stoppedUP 100% in both clients — safe to repoint
# For items showing stoppedDL or missingFiles — investigate data completeness first
```

Process in sub-batches of 10. Pilot `_qb-finish/` items first (lowest risk).

---

## save-path-repair Reference

`hashall payload save-path-repair` repairs Class 4 (`_rehome-unique/<hash>/`) items only.
It does **not** handle Classes 1, 2, 3, or 5.

```bash
make save-path-repair-dry              # dry-run all candidates
make save-path-repair-dry LIMIT=5      # dry-run first N
make save-path-repair-apply LIMIT=2    # execute first N (pilot)
make save-path-repair-apply LIMIT=0    # execute all
```

What it does per item:
1. Computes canonical target path from tracker label + content name
2. Moves files from `_rehome-unique/<hash16>/` to canonical path (if data present)
3. Patches qB `.fastresume` to new path (writes `.bak-repair` backup first)
4. Repoints RT via `d.directory.set`
5. Triggers RT recheck

Guard: skips fastresume patch if `files_moved == 0` and qB `save_path` does not contain
`_rehome-unique` — prevents patching a torrent whose data is already in the right place.

---

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
