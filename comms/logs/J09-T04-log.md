# J09-T04: Audit payload CLI mutations

**Status:** done
**Task type:** discovery
**Branch:** cr/hashall-20260530-000517-claude__j09
**Head:** a573a3ac9eb82dcb9a7a064402f09e7ea7cb6f0f

## Files audited

- `src/hashall/payload.py` — full read (1563+ lines): prune_orphan_payloads, compute_payload_hash, GC limits, upsert logic, build_payload, upgrade_payload_missing_sha256
- `src/hashall/cli.py` — full read (4873+ lines): payload_sync, save_path_repair, rt_repoint, client_drift apply path, GC sequencing, lock acquisition
- `tests/test_cli_payload_sync.py` (1832 lines) — existing test coverage patterns
- `tests/test_payload.py` (671 lines)

## Findings summary

| # | Severity | File | Brief |
|---|----------|------|-------|
| F1 | **Medium** | cli.py:1469-1481 | Orphan GC runs inside fcntl lock but has race window with concurrent scan/rt changes |
| F2 | **Medium** | cli.py:932-944 | Payload sync fcntl lock is advisory — only protects against concurrent sync processes, not scan or external catalog writes |
| F3 | **Low** | cli.py:1416-1421 | Upgrade state file records root as complete before upsert commits — crash between upsert(commit=False) and batch commit leaves stale state entry |
| F4 | **Medium** | cli.py:2462-2504 | save-path-repair continues on individual errors but exceptions propagate; partial failures leave partial moves |
| F5 | **Low-Medium** | payload.py:597-819 | prune_orphan_payloads commits to DB without verifying filesystem state (relies on catalog freshness) |
| F6 | **Low** | payload.py:676 | Unnecessary COUNT(*) overhead query for every GC call even when zero candidates |
| F7 | **Low** | cli.py:1469 | Orphan GC skipped entirely when --limit > 0 — partial syncs never GC |
| F8 | **Low** | payload.py:1086 | Inode key collision risk: (inode, size) pair may collide across different filesystems on same device_id |

## Answers to specific questions

1. **Can orphan GC delete a payload that is still actively seeding (race between scan and GC)?** Yes — the race window is small but real. GC checks `torrent_instances` refs, then files_{device_id} active count, then deletes. A concurrent scan could delete files between the check and DELETE, or a concurrent sync could add a ref between the ref-check and the delete. In practice the fcntl lock serializes sync processes, but doesn't protect against fast external events.

2. **Does the payload sync lock protect against all concurrent access patterns?** No. It protects against concurrent `payload sync` runs only. A concurrent `scan` or external SQLite write during the GC window could cause inconsistencies.

3. **If payload sync crashes mid-loop, is the DB left in a consistent state?** Mostly yes. Batch commits at 400 ops bound partial writes. Each batch is atomic (payload + torrent_instance for same hash). The upgrade state file provides resume capability. Minor issue: if crash occurs between `upsert_payload(commit=False)` and the batch commit at cli.py:1419-1420, the upgrade state records complete but the DB doesn't have the new hash.

4. **Does save-path-repair stop on first error or continue? What's left behind?** The loop collects all results without early stopping on individual errors. However, unhandled exceptions from `execute_repair` propagate and crash the loop. On partial failure, files may have been moved for preceding hashes but subsequent hashes are untouched. The report includes per-item status so operators can see what succeeded/failed.

5. **Are there operations that commit to DB before verifying filesystem state?** Yes — `upsert_payload` and `prune_orphan_payloads` both commit based on catalog state (files_{device_id} table) without live filesystem verification. The `build_payload` function reads catalog data, not live disk. This is by design but creates a stale-data risk if catalog scan is not recent.

## Artifacts produced

- `docs/review/R4-payload-cli-findings.md` (committed)
