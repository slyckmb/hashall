# Cross-Repo qB Helper Instructions

Paste or adapt this instruction set when another CLI agent in another repo needs to interact with qBittorrent on this machine.

## Goal

Do not build or maintain another ad hoc qB Web API client in your repo.

Use the qB helper and cache tooling that already exists in `hashall` so:

- qB version and Web API differences are normalized in one place
- read-heavy status/list polling goes through the shared cache
- multiple dashboards or watchers do not stampede qB with direct `torrents/info` polling

## Required Rules

1. Do not poll qB `torrents/info` directly from your repo unless you are explicitly debugging cache behavior.
2. Do not add another cache daemon or another set of qB compatibility fallbacks in your repo.
3. For Python qB access, use the shared helper in `hashall`.
4. For shell list/status reads, use the shared cache helper in `hashall`.
5. If cache reads fail, fail visibly or show a stale-cache warning. Do not silently fall back to direct qB polling in a watch loop or TUI.

## Use These Hashall Entry Points

Python helper:

- `/home/michael/dev/work/hashall/src/hashall/qbittorrent.py`
- entrypoint:
  - `from hashall.qbittorrent import get_qbittorrent_client`

What it gives you:

- qB server profile detection
- app version / Web API version awareness
- normalized pause-state aliases:
  - `pausedDL` / `stoppedDL` -> `stoppedDL`
  - `pausedUP` / `stoppedUP` -> `stoppedUP`

Shared cache:

- `/home/michael/dev/work/hashall/bin/qb-cache-agent.py`
- `/home/michael/dev/work/hashall/bin/qb-cache-daemon.py`
- cache root:
  - `~/.cache/hashall-qb/`

Shell helper for cached list reads:

- `/home/michael/dev/work/hashall/bin/lib/qb-cache.sh`
- function:
  - `qb_cache_fetch_torrents_info`

## Recommended Integration Patterns

### Python

Use the shared helper for direct qB mutations and focused reads:

```python
from hashall.qbittorrent import get_qbittorrent_client

qb = get_qbittorrent_client()
profile = qb.get_server_profile()
torrents = qb.get_torrents()
```

Use this for:

- start/stop/pause/resume
- setLocation
- recheck
- targeted per-hash inspection

### Shell

Use the shared cache helper for list/status reads:

```bash
source /home/michael/dev/work/hashall/bin/lib/qb-cache.sh
qb_cache_fetch_torrents_info /tmp/all_torrents.json 15 5 15
```

Use this for:

- dashboards
- watch loops
- triage summaries
- any repeated `torrents/info` polling

## Explicit Non-Goals

- Do not copy the old qbitui cache implementation into your repo.
- Do not create another raw `curl "$QBIT_URL/api/v2/torrents/info"` polling loop.
- Do not invent a second qB compatibility layer.

## If You Think Hashall Is Missing Something

Add the missing qB capability to `hashall`, then consume it from your repo.

Do not patch around it locally in a second helper.

## Current Limitation

`qbitui` external dashboard alignment is still separate follow-up work.

If you are working in `qbitui`, the right direction is to align it to the `hashall` helper/cache contract, not to fork the contract again.
