# hashall: qB Cache Path Rename Follow-up

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

Recommended remedy:

1. Decide whether hashall should continue owning a separate cache or consume silo's cache path.
2. If consuming silo, change defaults from `~/.cache/hashall-qb` to `~/.cache/silo-qb`.
3. Keep `--qb-cache-file` overrides intact.
4. If backwards compatibility is needed, read `~/.cache/hashall-qb` only when `~/.cache/silo-qb` is absent.
5. Update docs that describe hashall as the canonical qB cache owner.
6. Verify `bin/qb-cache-agent.py --status`, CLI commands with `--qb-cache-file`, and tests around `DEFAULT_QB_CACHE_FILE`.
