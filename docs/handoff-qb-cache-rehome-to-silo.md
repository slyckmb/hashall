# Handoff: Migrate qB Cache Tooling from hashall → silo

**Date:** 2026-04-21  
**Author:** hashall-20260420-175812-claude  
**Target repo:** `/home/michael/dev/tools/silo`  
**Priority:** Medium — no urgency, but the coupling is backwards and causes friction

---

## Why This Should Move

The qB cache daemon and agent live in hashall (`src/hashall/qb_cache.py`,
`bin/qb-cache-agent.py`, `bin/qb-cache-daemon.py`). Silo consumes them via a
delegation shim (`silo-cache-agent.py` → `silo_hashall_shared.exec_hashall_script`)
that locates hashall's `bin/` at runtime.

This is backwards. Silo is the TUI/dashboard layer that drives both qB and RT
polling. The RT cache daemon already lives in silo. Having qB cache in hashall
means:

- silo depends on hashall being present at a known path
- The worktree resolver in `silo_hashall_shared.resolve_hashall_root()` is
  required just to find the agent scripts
- Bugs in the agent (e.g., the zombie fix in `b6c3f8d`) have to go through
  the hashall branch/merge cycle before silo picks them up
- hashall callers access the cache by importing `from hashall.qbittorrent
  import get_torrents_from_cache` — a thin wrapper that reads the JSON file
  the daemon writes; that coupling can stay or be replaced with a direct file
  read, it doesn't require the daemon to live in hashall

---

## What Needs to Move

### Files to copy from hashall → silo

| Source (hashall) | Destination (silo/bin/) |
|---|---|
| `bin/qb-cache-agent.py` | `bin/qb-cache-agent.py` (rename `silo-cache-agent.py` shim to point here) |
| `bin/qb-cache-daemon.py` | `bin/qb-cache-daemon.py` (rename `silo-cache-daemon.py` shim to point here) |
| `src/hashall/qb_cache.py` | `bin/qb_cache.py` (or `silo/qb_cache.py` in the package) |

The agent and daemon scripts are thin `argparse` entry points that import
from `qb_cache.py`. All three should move together.

### Current content of qb_cache.py (public surface)

Functions used outside the module:

- `build_agent_parser()` / `agent_main()` — entry point for `qb-cache-agent.py`
- `build_daemon_parser()` / `daemon_main()` — entry point for `qb-cache-daemon.py`

Everything else is private (`_` prefix). No other hashall module imports
from `qb_cache.py` directly — they go through `qbittorrent.py` helpers.

### Key constants (paths)

```python
# Default cache directory — shared between hashall and silo via filesystem
base_dir = Path.home() / ".cache" / "hashall-qb"
# Files under it:
#   torrents-info.json        — the cache payload
#   torrents-info.meta.json   — daemon metadata (fetched_at, interval, etc.)
#   daemon.pid                — daemon PID file
#   daemon.lock               — daemon lock file
#   daemon.log                — daemon log
#   leases/                   — per-client lease files
```

The cache dir name `hashall-qb` can stay as-is — it's a shared filesystem
location that both repos read. Renaming it is optional and would require
updating `DEFAULT_QB_CACHE_DIR` in `src/hashall/qbittorrent.py` too.

---

## What hashall Keeps

hashall does NOT need to own the daemon, but it does read the cache file.
Keep in hashall:

- `src/hashall/qbittorrent.py` — `get_torrents_from_cache()`,
  `DEFAULT_QB_CACHE_FILE`, `DEFAULT_QB_CACHE_META_FILE`. These read the JSON
  file the daemon writes. No daemon logic required.
- `src/hashall/qb_cache.py` — can be **deleted** from hashall once the
  daemon lives in silo. The file has no callers in hashall other than its
  own `bin/` entry points.

hashall modules that consume the cache (`hitchhiker.py`, `hitchhiker_split.py`,
`orphan_sweep.py`, `cli.py`) all import from `qbittorrent.py`, not from
`qb_cache.py`. They will be unaffected.

---

## Migration Steps

1. **Copy** `src/hashall/qb_cache.py` into silo (suggested: `bin/qb_cache_lib.py`
   or inline into the agent/daemon scripts if you prefer no separate file).

2. **Update** `bin/qb-cache-agent.py` in silo to import from the local copy
   rather than relying on `sys.path` including hashall's `src/`.

3. **Update** `bin/qb-cache-daemon.py` in silo similarly.

4. **Replace** `bin/silo-cache-agent.py` (currently a thin shim to hashall)
   with the real implementation.

5. **Replace** `bin/silo-cache-daemon.py` (currently a thin shim to hashall)
   with the real implementation.

6. **Remove** `silo_hashall_shared.resolve_hashall_root()` worktree-search
   logic — no longer needed for the qB cache path. Keep the rest of
   `silo_hashall_shared.py` if other scripts still need it.

7. **Delete** from hashall (after silo version is live):
   - `src/hashall/qb_cache.py`
   - `bin/qb-cache-agent.py`
   - `bin/qb-cache-daemon.py`

8. **Update** `src/hashall/qbittorrent.py`: the constants
   `DEFAULT_QB_CACHE_DIR`, `DEFAULT_QB_CACHE_FILE`, `DEFAULT_QB_CACHE_META_FILE`
   remain. Optionally add a comment noting the daemon now lives in silo.

---

## Recent Fix to Carry Over

**Commit `b6c3f8d`** (2026-04-21, `cr/hashall-20260420-175812-claude`):

```python
# In agent_main(), after the ensure_daemon block:
# max_age <= 0 means "ensure daemon only" — caller doesn't want data, just daemon health.
# Exit immediately rather than spinning in a wait loop that can never be satisfied.
if args.max_age <= 0:
    return 0
```

This fixes the zombie accumulation bug where `silo-dashboard.py::ping_daemon_nonblocking()`
passed `--max-age 0` and each agent spun for 5 seconds in a wait loop
(`age <= 0.0` is never True). With this fix, `--ensure-daemon --max-age 0`
exits in ~170ms.

**This fix must be present in the silo-owned copy** before the hashall version
is deleted. It is committed in hashall's worktree branch but not yet on main.
Check that the silo copy includes the guard at line ~327 of `qb_cache.py`:

```python
if args.max_age <= 0:
    return 0
```

---

## Secondary Fix (silo-dashboard.py, optional)

`ping_daemon_nonblocking()` uses `subprocess.Popen()` without ever calling
`.wait()`. With the `max_age <= 0` fix in place, exited agents become
`<defunct>` only briefly (one per running silo instance) until the parent
exits. It is harmless but can be fully cleaned up:

```python
# In ping_daemon_nonblocking():
proc = subprocess.Popen([...])
threading.Thread(target=proc.wait, daemon=True).start()
```

Low priority — the zombie accumulation is already fixed by the agent fix.

---

## Silo RT Cache for Reference

The RT cache daemon already lives natively in silo:
- `bin/silo-rt-cache-daemon.py` — the real implementation
- `silo_client_rt.py` — RT XMLRPC client

The qB cache migration would bring qB to the same pattern: both caches owned
and operated by silo, with hashall as a read-only consumer of the JSON files.
