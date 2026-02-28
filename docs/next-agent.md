# Next Agent Prompt (Living)

Date context: 2026-02-28

## Mission

Drive stoppedDL count down using the bucket/drain/apply loop with high-precision matching and minimal repeat verification.

## Non-Negotiables

- User runs mutating commands locally and shares outputs.
- Agent does not run mutating qB commands without explicit user approval.
- One mutating qB workflow at a time.
- Treat `/data/media` and `/stash/media` as equivalent aliases.
- Keep payload roots unique per hash when rebuilding.
- Never allow repaired hashes to remain in active download states.

## Current State

- Active tooling:
  - `bin/qb-stoppeddl-bucket.py` (`0.1.2`)
  - `bin/qb-stoppeddl-drain.py` (`0.1.10`)
  - `bin/qb-stoppeddl-apply.py` (`0.2.3`)
  - `bin/qb-stoppeddl-apply-watch.sh` (`0.1.2`)
  - `bin/qb-stoppeddl-roundloop.sh` (`0.1.3`)
  - `bin/qb-libtorrent-verify.py`
- qB API helper includes torrent export (`src/hashall/qbittorrent.py`).
- Drain logic now narrows weak global DB candidates and stops candidate testing after first class `a`.
- Apply writes completion marker used by wrappers: `reports/apply-last-completion.json`.

## Standard Flow

1. Refresh bucket (`stoppedDL` + torrent exports).
2. Drain once (grade hashes `a/b/c/d/e`).
3. Apply only `a/b/c` for active hashes.
4. Wait for checking queue to clear.
5. Repeat until stoppedDL converges.

## Primary Commands (Next Run)

```bash
bin/qb-stoppeddl-roundloop.sh \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --max-candidates 1 \
  --verify-timeout 2400 \
  --ops-mode auto
```

```bash
bin/qb-stoppeddl-apply-watch.sh \
  --bucket-dir /tmp/qb-stoppeddl-bucket-live \
  --poll 20 \
  -- --ops-mode auto --no-wait-recheck
```

## Validation Checklist

1. No repaired hashes transition into sustained downloading states.
2. `setLocation`/fastresume values align with selected content roots.
3. Apply completion markers are fresh for each applied drain report.
4. Drain reports show decreasing `remaining` and no repeated verify of already-scored candidates.

## Fastresume Note

Default apply behavior is automatic:
- if any selected hash needs fastresume changes, perform one offline batch patch/restart pass;
- otherwise use API no-wait flow (`setLocation` + recheck dispatch).
