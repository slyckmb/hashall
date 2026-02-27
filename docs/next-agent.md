# Next Agent Prompt (Living)

Date context: 2026-02-27

## Mission

Continue phase-2 qB repair while preserving seeding safety and minimizing qB polling contention.

## Non-Negotiables

- User runs mutating CLI locally and shares output/log path for analysis.
- Agent does not run mutating CLI without explicit approval.
- One mutating command at a time (avoid qB restart and sqlite lock conflicts).
- Treat `/data/media` and `/stash/media` as equivalent mount aliases.

## Current State

- Shared qB cache mode is implemented:
  - `bin/qbit-cache-daemon.py`
  - `bin/qbit-cache-agent.py`
  - Client support in:
    - `bin/qbit-start-seeding-gradual.sh --cache --cache-max-age`
    - `bin/rehome-99_qb-checking-watch.sh --cache --cache-max-age`
- `qbit-start-seeding-gradual.sh` now:
  - avoids argv overflow on large state payloads
  - uses flip-only HALT logic for downloading-like transitions
  - logs pre-existing downloading-like scope and ignores it for halt decisions

## Primary Commands (Next Run)

```bash
bin/qbit-start-seeding-gradual.sh --daemon --apply --min-batch 1 --poll 15 --cache --cache-max-age 15
```

```bash
bin/rehome-99_qb-checking-watch.sh --enforce-paused-dl --cache --cache-max-age 5 --interval 15
```

## Validation Checklist

1. Confirm cache daemon health:
   - `python3 bin/qbit-cache-agent.py --status`
2. Confirm `qbit-start-seeding-gradual` logs include:
   - baseline downloading-like count
   - `downloading_new` and `downloading_preexisting`
3. If HALT happens, capture:
   - run log path
   - `daemon.log` tail
   - hashes reported in `detail=...`

## Post-Run Checklist

1. Recount unresolved pool:
   - `stoppedDL`
   - `missingFiles`
2. Capture new error mix and group by:
   - no-live-candidate
   - multiple sibling roots
   - path mismatch / post-move mismatch
3. Prioritize low-risk relinks first; keep any bulk remap behind explicit operator approval.

## Open TODOs

- `--resume` behavior in `qbit-start-seeding-gradual.sh` is still effectively a no-op.
- Phase-2 full objective remains: relink unresolved `stoppedDL` and `missingFiles` items.
