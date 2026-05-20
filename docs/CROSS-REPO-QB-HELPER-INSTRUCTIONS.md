# Cross-Repo Shared Cache Instructions

Paste or adapt this instruction set when another CLI agent needs to interact with
qBittorrent or rTorrent on this machine through the shared cache layer.

## Silo — Shared Cache Owner

**silo** (`/home/michael/dev/tools/silo/`) owns and operates two cache daemons:

| Cache | Daemon | Cache File | Live Stats |
|---|---|---|---|
| **qB** | `silo-cache-daemon.py` | `~/.cache/silo-qb/torrents-info.json` | ~4806 items, 30s interval, qB v5.2.0 |
| **RT** | `silo-rt-cache-daemon.py` | `~/.cache/silo-rt/torrents.json` | ~4806 items, 30s interval, RT 0.16.5 |

hashall reads both caches by default — no manual config needed. Python constants:
- `from hashall.qbittorrent import DEFAULT_QB_CACHE_FILE` → `~/.cache/silo-qb/torrents-info.json`
- `from hashall.rt_cache import DEFAULT_RT_SHARED_CACHE_FILE` → `~/.cache/silo-rt/torrents.json`

## Goal

Do not build or maintain ad hoc Web API clients in your repo. Use the shared
cache layer:

- qB version / Web API differences are normalized in one place
- read-heavy polling goes through the shared cache (not qB/RT directly)
- multiple consumers do not stampede the daemons

## Required Rules

1. Do not poll `qB torrente/info` or RT XMLRPC directly unless debugging cache behavior.
2. Do not add another cache daemon or another set of qB compatibility fallbacks.
3. For Python access, use the shared helpers in `hashall`.
4. For shell reads, use the shared cache files directly.
5. If cache reads fail, fail visibly. Do not silently fall back to direct polling.

## Use These Hashall Entry Points

### Python — qB

```python
from hashall.qbittorrent import get_qbittorrent_client

qb = get_qbittorrent_client()
profile = qb.get_server_profile()
torrents = qb.get_torrents()
```

For direct cache reads (no live API):

```python
from hashall.qbittorrent import get_torrents_from_cache, DEFAULT_QB_CACHE_FILE

torrents = get_torrents_from_cache(max_age_s=60, cache_path=DEFAULT_QB_CACHE_FILE)
```

### Python — RT

```python
from hashall.rt_cache import load_rt_cache_snapshot

snapshot = load_rt_cache_snapshot()
rows = snapshot.get("rows", [])
```

## Daemon Health Check

Check daemon status from any directory:

```bash
# qB cache daemon
cat ~/.cache/silo-qb/torrents-info.meta.json | python3 -m json.tool

# RT cache daemon
cat ~/.cache/silo-rt/torrents.meta.json | python3 -m json.tool
```

Key fields: `source` (should be `daemon_live`), `daemon_pid`, `items`, `active_leases`,
`fetched_at_iso`, `last_error`. If `source` is `daemon_error` or `stale`, the daemon
needs restart.

## Lease-Aware Cache Reads

The silo daemons use a lease system. To request a lease (keeps daemon alive
while you need it):

```bash
# Acquire lease (prevents daemon idle-exit)
python3 ~/dev/tools/silo/bin/silo-cache-agent.py --max-age 60 \
  --cache-file ~/.cache/silo-qb/torrents-info.json \
  --requested-interval 30 --lease-ttl 120

# Release lease
python3 ~/dev/tools/silo/bin/silo-cache-agent.py --release
```

hashall reads use `get_torrents_from_cache()` which checks cache freshness
and falls back to the metadata file. It does NOT automatically acquire leases.
Long-running tools should acquire a lease explicitly.

## Explicit Non-Goals

- Do not copy the old `qbitui` cache implementation into your repo.
  `qbitui` is the former name of the external repo now called `silo`.
- Do not create another raw `curl "$QBIT_URL/api/v2/torrents/info"` polling loop.
- Do not invent a second qB compatibility layer.

## If You Think Hashall Is Missing Something

Add the missing capability to `hashall`, then consume it from your repo.
Do not patch around it locally in a second helper.
