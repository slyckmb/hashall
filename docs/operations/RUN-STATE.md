# Run State (Canonical)

Last updated: 2026-03-07
Status: canonical living state

## Purpose

Single living document for current operational state, handoff context, and next-agent execution guidance.

## Current Mission

1. Finish `pool-data -> pool-media`.
2. Keep qB out of the payload-move path.
3. Preserve stable catalog identity and healthy refresh runs.
4. Resume `~noHL` only after the pool migration path is solid.

## Canonical CLI

`hashall` is now the sole operator entrypoint.

Use:

- `hashall refresh --verbose`
- `hashall rehome auto --from pool-data --to pool-media --limit N`
- `hashall rehome auto --from pool-data --to pool-media --limit N --apply`
- `hashall rehome config ...`
- `hashall rehome seed-root-state show`

The standalone `rehome` console script has been removed from packaging.

## Critical Architecture Decision

Migration must be split into:

1. donor acquisition
2. shared attach/repoint

Meaning:

- `REUSE`:
  - donor already exists at target
- `MOVE`:
  - donor is transferred externally first

After donor exists and verifies, both lanes must use the same constructor:

- build/verify target payload
- patch fastresume offline
- restart qB if needed
- recheck
- verify seed-ready
- sync catalog
- record cleanup state

qB must not be used as the byte mover.
qB `setLocation` is not acceptable as the mainline migration primitive on this host.

## Current `REUSE` State

`REUSE` now defaults to offline fastresume repointing.

Important fixes already landed:

- queued recheck guard no longer fails immediately on temporary `stoppeddl 0%`
- `REUSE` no longer reports false freed bytes
- `REUSE` reports `cleanup pending` correctly
- single-file nested-path fallback save-path derivation is fixed
- latest successful pilot:
  - log: `~/.logs/hashall/rehome/auto/20260307-164026.log`
  - result:
    - `apply ... cleanup pending OK`
    - `verify ... stoppedup×9 ... catalog OK ... cleanup pending OK`
    - `freed 0 B from sources`

Operational conclusion:

- `REUSE` is safe enough to continue in small batches
- do not jump straight to a large batch

## Current `MOVE` Risk

Current `MOVE` is not safe yet.

Reason:

- after external copy, executor still uses qB relocation semantics
- that can recreate the qB move/oom/orphaned-transfer behavior seen earlier

Operational guidance:

- do not run current `MOVE` apply at scale
- interim safe model is `copy-then-REUSE`
- next code task is to make `MOVE` use the same offline attach constructor as `REUSE`

## Refresh / Identity State

`stash` fs_uuid repair was applied live:

- old: `dev-44`
- new: `zfs-4624186565346049802`

Verification:

- `hashall doctor preflight --db /home/michael/.hashall/catalog.db` -> clean
- refresh log:
  - `~/.logs/hashall/rehome/refresh/20260307-160508.log`
  - status: `refresh OK`
  - processed: `5147`
  - complete payloads: `5140`
  - incomplete payloads: `7`
  - missing in catalog: `0`

## qB Guard / Repair State

`qb-start-seeding-gradual.sh` now:

- resumes `stoppedUP` gradually
- halts only on newly flipped downloading-like torrents
- does not halt on preexisting downloading-like states

Current script version:

- `bin/qb-start-seeding-gradual.sh` -> `v1.3.11`

## Known Remaining Gaps

1. cleanup-source path/provenance can still point at legacy `/pool/data/seeds/...`
2. `MOVE` still needs the shared offline attach constructor
3. known migration changes should update catalog state immediately where possible, not wait for later full refresh

## Primary Logs

- `~/.logs/hashall/hashall.log`
- `~/.logs/hashall/rehome/refresh/`
- `~/.logs/hashall/rehome/auto/`
- `~/.logs/hashall/reports/qbit-triage/`

For shared runtime log tailing, prefer:

```bash
tail -n0 -F ~/.logs/hashall/hashall.log
```

## Next-Agent Checklist

1. Keep finishing remaining `REUSE` groups in small batches.
2. Fix cleanup-source path selection/provenance.
3. Refactor `MOVE` to:
   - acquire donor externally
   - attach via shared offline fastresume path
   - avoid `setLocation`
4. Pilot `MOVE` only after that refactor.
5. Then plan `~noHL`.
