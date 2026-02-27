# Hashall Ops Log (Living)

Last updated: 2026-02-27

## Execution Model

- User runs mutating CLI locally to monitor qB behavior in real time.
- Agent may run read-only verification and approved smoke checks.
- Run one mutating pipeline command at a time to avoid qB/API/db contention.
- Prefer shared cache mode for repeated `torrents/info` reads.

## Current Snapshot

- qB shared cache infrastructure is now implemented:
  - `bin/qbit-cache-daemon.py`: lease-based cache daemon for full `torrents/info` snapshot.
  - `bin/qbit-cache-agent.py`: client helper (`--ensure-daemon`, `--status`, lease renewals).
  - `bin/rehome-99_qb-checking-watch.sh`: opt-in `--cache --cache-max-age`.
  - `bin/qbit-start-seeding-gradual.sh`: opt-in `--cache --cache-max-age`.
- `qbit-start-seeding-gradual` safety flow was hardened:
  - Fixed `Argument list too long` crash by moving state payload parsing from argv to temp files.
  - Safety gate is now flip-only: halts on newly flipped downloading-like hashes, not pre-existing ones.
  - Pre-existing downloading-like hashes are logged as informational.
- Latest dry-run sample on patched script:
  - Protected watch scope: `5130`
  - Baseline downloading-like in scope: `169`
  - `stoppedUP` candidates: `1` (dynamic)

## Operational Commands

- Start/continue gradual seeding daemon with cache:
  - `bin/qbit-start-seeding-gradual.sh --daemon --apply --min-batch 1 --poll 15 --cache --cache-max-age 15`
- Watchdog with cache:
  - `bin/rehome-99_qb-checking-watch.sh --once --cache --cache-max-age 5`
- Cache daemon status:
  - `python3 bin/qbit-cache-agent.py --status`
- Manual cache daemon stop (if needed):
  - `[[ -f ~/.cache/hashall/qbit/daemon.pid ]] && kill "$(cat ~/.cache/hashall/qbit/daemon.pid)"`

## Known Issues / TODO

- `--resume` is currently parsed but does not change candidate selection in `qbit-start-seeding-gradual.sh`.
- Remaining queue objective still targets relinking all unresolved qB items:
  - `stoppedDL=168`
  - `missingFiles=10`
- Continue avoiding broad, route-unsafe remaps; keep ownership constraints strict.

## Log Locations

- qbit triage logs: `~/.logs/hashall/reports/qbit-triage/`
- nohl pipeline logs: `~/.logs/hashall/reports/rehome-normalize/`
- db-refresh logs: `~/.logs/hashall/reports/db-refresh/`
- hashall runtime log: `~/.logs/hashall/hashall.log`
