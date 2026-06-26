# Operational Run State

Last updated: 2026-06-12

## 2026-06-12 J02 Operational Verification Snapshot

All J02 verification tasks complete. System is healthy with known pending items.

### Catalog Refresh (J02-T01)

- Scan roots: 5, roots with changes: 3, elapsed: 10m38s
- Processed: 4882, complete payloads: 4154, incomplete: 728, missing: 9
- Orphan GC candidates: 4543 (new=2062, aged=2481), pruned: 0 (blocked >1000)
- Dedup: skipped (freshness profile)
- Parallel scans: enabled (max=4)

### Drift Audit (J02-T02)

- qB rows: 4889, RT rows: 4889, parity: perfect
- QB-only: 0, RT-only: 0
- Path drift: 12 — high=8, medium=0, low=4
- 7 × repoint_qb_to_rt_path (actionable batch)
- 3 × manual_review (blocked: no_client_on_required_pool_placement)
- 2 × manual_review (unhealthy client state)
- Notable: a6d3ae00 (The Rookie) qB still in _qb-unique-repair/ staging

### Canonical Tree + Payload Sync (J02-T03)

- Payload sync: 4889 processed, 4154 complete, 735 incomplete, 16 missing
- Incomplete cause: SHA256 backfill gap (fast profile skips SHA256), not path issue
- Class 1 (_cross-seed/<hash>/): 3 items
- Class 2 (cross-seed/other/): 0
- Class 3 (cross-seed-link/): 0
- Class 4 (_rehome-unique/): 64 items
- Class 5 (_qb-unique-repair/ etc): 15 items
- Total non-canonical: 82
- qB missingFiles: 5 (Slice 12b rechecks mostly resolved)
- Orphan GC blocked: 2481 aged > 1000 limit

### Hitchhiker Audit (J02-T04)

- Total groups: 137 (was 162 in May, -25 / -15%)
- Type A: 54 (unchanged — catalog collisions, need de-hitchhike)
- Safe-to-split: 54 (was 60, -6)
- Blocked: 24 (was 47, -23 — significant improvement)
- Busy: 5 (was 1, +4 in-flight)

### Known Pending Items

- OP-1: Slice 12b — 31 stale entries (no source file) need manual disposition
- OP-2: Slice 12c — 3 remaining Class 1 items (down from 10)
- OP-3: RT container restart needed to activate hash_done hook; healthchecks.io
  monitor for rt-qb-mirror-sync-apply not yet created; sys/docker unstaged commit
- Orphan GC limit: needs raising from 1000 to clear 2481 aged candidates
- SHA256 backfill: 735 incomplete payloads need full (non-fast) refresh
- Type A de-hitchhike: 54 groups pending
