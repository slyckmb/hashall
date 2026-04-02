# Refresh Recovery - 2026-04-02

## Incident

The overnight full upgrade scan completed all 4 scan roots and then failed in
the final payload-sync stage:

```text
python -m hashall.cli payload sync --upgrade-missing
```

Failure observed:

- `ConnectionResetError(104, 'Connection reset by peer')`
- raised through qB auth / `test_connection()`
- final user-facing error:
  - `RuntimeError: Failed to authenticate with qBittorrent`

## What this means

- The scan run itself did **not** crash during the scan phases.
- Rescanning `/stash/media`, `/pool/data`, `/pool/media`, and `/mnt/hotspare6tb`
  is not the right first recovery action.
- The correct recovery is:
  1. recover the `gluetun_qbit` client stack if degraded
  2. rerun only payload sync

## Related client health evidence

At analysis time:

- qB container was running and healthy
- rtorrent container was running and healthy
- but RT shared cache metadata still showed daemon failure:
  - `source = daemon_error`
  - `last_error = rTorrent returned empty result from http://localhost:18000/RPC2`

This is enough to treat the stack as degraded for refresh finalization.

## New helper behavior

`bin/run-hashall-upgrade-scans.sh` now:

1. probes qB readiness
2. probes RT cache health
3. if either side is degraded, restarts the full stack:
   - `gluetun`
   - `qbittorrent_vpn`
   - `rtorrent_vpn`
4. waits for the stack to become ready
5. runs `payload sync --upgrade-missing`
6. if payload sync still fails, restarts once and retries once

## New resume command

To finish this exact failure class without rerunning the 4 scans:

```bash
bin/run-hashall-upgrade-scans.sh --payload-sync-only
```

## Recovery execution result

This recovery path was executed successfully on `2026-04-02`.

Observed outcome:

- qB preflight initially reproduced the auth-reset failure
- the helper restarted the full `gluetun_qbit` stack
- payload sync then completed successfully without rerunning the 4 scans

Final payload-sync summary:

- `processed: 5269`
- `complete payloads: 5251`
- `incomplete payloads: 18`
- `missing in catalog: 18`
- `root path source: content_path=5269, files_api_fallback=0`
- `orphan gc candidates: 55 (new=52, aged=3)`
- `orphan payloads pruned: 3`

Helper summary for the successful recovery run:

- `scans_ok=0`
- `scans_failed=0`
- `payload_sync=ok`
- `stack_restarts=1`

So the overnight refresh is now effectively recovered and finalized. The scans
did not need to be rerun.

## Remaining follow-up

- The helper should remain the standard recovery path for future
  scan-complete / payload-sync-failed incidents.
- If this failure shape recurs, use `--payload-sync-only` first.
- Only rerun the full 4-root scan if an actual scan step failed or the catalog
  changed materially after the last completed scan.

## Guidance

- Use `--payload-sync-only` after a scan-complete / payload-sync-failed run.
- Do **not** rerun the full 4-root scan unless one of the scans actually failed
  or the catalog has changed materially since the completed scan finished.
