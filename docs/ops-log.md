# Hashall Ops Log (Living)

Last updated: 2026-02-27

## Execution Model

- User runs mutating qB repair commands locally for live safety control.
- Agent prepares scripts/plans, analyzes outputs, and patches tooling.
- Run one mutating qB workflow at a time.
- Treat `/data/media` and `/stash/media` as equivalent aliases.

## Current Snapshot

- New standalone repair tooling is in repo (not based on prior rehome automation):
  - `bin/qb-repair-v2.py` (plan/prepare/patch-fastresume/recheck pipeline)
  - `bin/qb-repair-fresh.py` (fresh strict-manifest standalone repair helper)
  - `bin/qb-fastresume-retarget.py` (report-driven fastresume retargeter)
- `qb-repair-v2` has been validated on a pilot batch:
  - planned candidates using strict match tiers (`exact`, `size_name`, `size_only`)
  - prepared unique hardlinked roots for selected hashes
  - patched fastresume (`save_path`, `qBt-savePath`, clear `qBt-downloadPath`)
  - submitted `setLocation` + `recheck` for prepared hashes
- Active operator directive: do not interfere while qB checking queue drains (`checking ~= 103`).

## Operational Commands (v2)

- Build plan:
  - `bin/qb-repair-v2.py plan --report-json /tmp/qb-repair-v2-plan.json`
- Build unique hardlinked payload roots from plan:
  - `bin/qb-repair-v2.py prepare --plan /tmp/qb-repair-v2-plan.json --apply --report-json /tmp/qb-repair-v2-prepare.json`
- Patch fastresume before qB startup/recheck phase:
  - `bin/qb-repair-v2.py patch-fastresume --report /tmp/qb-repair-v2-prepare.json --allow-status prepared --apply`
- Submit location+recheck with download-protection monitoring:
  - `bin/qb-repair-v2.py recheck --report /tmp/qb-repair-v2-prepare.json --allow-status prepared --apply --monitor-seconds 300 --poll 5`

## Guardrails

- Preferred mutation order: `setLocation -> recheck -> verify seeding-safe state`.
- Fastresume must be aligned when qB contains conflicting download/save path fields.
- Never let repaired hashes flip into active downloading states.
- Keep payload roots unique per torrent hash; avoid cross-linking one payload root to multiple hashes.

## Log Locations

- qB triage logs: `~/.logs/hashall/reports/qbit-triage/`
- nohl pipeline logs: `~/.logs/hashall/reports/rehome-normalize/`
- db-refresh logs: `~/.logs/hashall/reports/db-refresh/`
- hashall runtime log: `~/.logs/hashall/hashall.log`
