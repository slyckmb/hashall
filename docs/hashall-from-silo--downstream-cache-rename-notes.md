# hashall: qB Cache Path Rename Follow-up

Status as of 2026-05-06:

- Silo-owned `~/.cache/silo-qb` is the live fresh cache path.
- The old `~/.cache/hashall-qb` cache is stale fallback state only.
- Hashall now consumes the silo cache path by default while preserving explicit
  `--qb-cache-file` overrides and legacy fallback reads.
- Observed hygiene issue: `~/.cache/silo-qb/daemon.pid` can point at the live
  daemon while `torrents-info.meta.json` still carries an older non-running
  `daemon_pid`. The cache payload can still be fresh; fix this in the
  silo/cache hygiene lane rather than restarting an actively leased daemon.

Silo now owns the qB cache path and writes to:

```text
~/.cache/silo-qb/torrents-info.json
~/.cache/silo-qb/torrents-info.meta.json
```

The old path remains a silo read fallback only:

```text
~/.cache/hashall-qb/torrents-info.json
```

Impacted hashall references found under `/home/michael/dev/work/hashall`:

- `src/hashall/qb_cache.py`
- `src/hashall/qbittorrent.py`
- `src/hashall/cli.py`
- `Makefile`
- `bin/lib/qb-cache.sh`
- docs under `docs/operations`, `docs/tooling`, `docs/handoff*`, `docs/NEXT-AGENT-PROMPT.md`, `docs/REQUIREMENTS.md`

Implemented in hashall:

1. `src/hashall/qbittorrent.py` defaults to `~/.cache/silo-qb`.
2. `get_torrents_from_cache()` falls back to `~/.cache/hashall-qb` only for default reads when the silo cache is absent or stale.
3. Explicit cache paths remain exact and do not fall back.
4. `scripts/pause_mirror_seeders.py` now uses the shared cache helper instead of a hardcoded old path.
5. Tests cover default reads, legacy fallback, and explicit-path behavior.

Remaining follow-up:

1. Decide when hashall's local qB cache daemon entry points should be removed or demoted now that silo owns daemon lifecycle.
2. Fix the silo daemon metadata hygiene issue where `torrents-info.meta.json` can retain an older non-running `daemon_pid`.
