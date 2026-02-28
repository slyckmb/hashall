# Hashall Ops Log (Living)

Last updated: 2026-02-28

## Execution Model

- User runs mutating qB commands locally for live safety control.
- Agent ships tooling, validates reports, and tunes matching/scoring.
- One mutating workflow at a time.
- Treat `/data/media` and `/stash/media` as equivalent aliases.

## Current Snapshot

- Active workflow is the standalone stoppedDL toolchain:
  - `bin/qb-stoppeddl-bucket.py` (`0.1.2`)
  - `bin/qb-stoppeddl-drain.py` (`0.1.10`)
  - `bin/qb-stoppeddl-apply.py` (`0.2.3`)
  - `bin/qb-stoppeddl-apply-watch.sh` (`0.1.2`)
  - `bin/qb-stoppeddl-roundloop.sh` (`0.1.3`)
  - `bin/qb-libtorrent-verify.py`
- Supporting qB API change:
  - `src/hashall/qbittorrent.py` now includes `export_torrent_file(...)`.
- Download-protection watchdog change:
  - `bin/qbit-start-seeding-gradual.sh` now `1.3.2` and no longer halts on `checkingDL` flips.

## Behavior Notes

- Drain now persists candidate outcomes while running and avoids re-verifying known bad/tried candidates.
- Drain skips extra candidates for a hash after first class `a` hit (`stop_on_a`).
- Drain can skip stale hashes if qB already shows seeding/checking-safe live states.
- Apply now writes a completion marker (`apply-last-completion.json`) for wrappers.
- Roundloop now uses completion freshness checks and can clear stale stop files at startup.
- Global DB candidate narrowing was tightened to reduce weak/noisy name matches before expensive verify.

## Operational Commands (Current)

- Refresh bucket:
  - `python3 bin/qb-stoppeddl-bucket.py --bucket-dir /tmp/qb-stoppeddl-bucket-live --states stoppedDL --refresh-torrents --prune-absent`
- Single drain pass:
  - `python3 bin/qb-stoppeddl-drain.py --bucket-dir /tmp/qb-stoppeddl-bucket-live --limit 0 --verify-timeout 2400 --max-candidates 1`
- Apply latest eligible drain:
  - `bin/qb-stoppeddl-apply-watch.sh --bucket-dir /tmp/qb-stoppeddl-bucket-live --once -- --ops-mode auto --no-wait-recheck`
- Unattended loop:
  - `bin/qb-stoppeddl-roundloop.sh --bucket-dir /tmp/qb-stoppeddl-bucket-live --max-candidates 1 --verify-timeout 2400 --ops-mode auto`

## Guardrails

- Preferred mutation order: `setLocation -> recheck -> verify seeding-safe state`.
- If any selected hash requires fastresume patching, apply defaults to a single offline batch patch/restart cycle.
- Never allow repaired hashes to remain in active download states.
- Keep payload roots unique per torrent hash; do not reuse one payload root across hashes.

## Log Locations

- qB triage logs: `~/.logs/hashall/reports/qbit-triage/`
- stoppedDL reports: `/tmp/qb-stoppeddl-bucket-live/reports/`
- hashall runtime log: `~/.logs/hashall/hashall.log`
