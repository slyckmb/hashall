# Next Agent Prompt (Living)

Date context: 2026-02-27

## Mission

Finish phase-2 repair for unresolved qB torrents using the standalone v2 flow (no legacy script dependency).

## Non-Negotiables

- User runs mutating commands locally and shares outputs.
- Agent does not run mutating qB commands without explicit user approval.
- One mutating qB workflow at a time.
- Treat `/data/media` and `/stash/media` as equivalent aliases.
- Keep payload roots unique per hash when rebuilding.

## Current State

- Standalone tools now available:
  - `bin/qb-repair-v2.py`
  - `bin/qb-repair-fresh.py`
  - `bin/qb-fastresume-retarget.py`
- Pilot repairs completed with prepare + fastresume patch + recheck flow.
- Operator requested pause while qB checking backlog drains (`checking ~= 103`).

## Standard Flow

1. `plan`
2. `prepare --apply`
3. `patch-fastresume --apply`
4. `recheck --apply`
5. verify no download flips and update unresolved counts

## Primary Commands (Next Run)

```bash
bin/qb-repair-v2.py plan --report-json /tmp/qb-repair-v2-plan.json
```

```bash
bin/qb-repair-v2.py prepare --plan /tmp/qb-repair-v2-plan.json --apply --report-json /tmp/qb-repair-v2-prepare.json
```

```bash
bin/qb-repair-v2.py patch-fastresume --report /tmp/qb-repair-v2-prepare.json --allow-status prepared --apply
```

```bash
bin/qb-repair-v2.py recheck --report /tmp/qb-repair-v2-prepare.json --allow-status prepared --apply --monitor-seconds 300 --poll 5
```

## Validation Checklist

1. No repaired hashes transition into active downloading states.
2. `save_path` / `content_path` align with rebuilt unique roots.
3. Recheck progresses to seeding-safe terminal states.
4. Remaining failures are recategorized for next wave.

## Fastresume Note

If qB retains internal download-location values in fastresume, `setLocation` can be ignored on restart. Always patch fastresume for prepared hashes before starting recheck wave.
