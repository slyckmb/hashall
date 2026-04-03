# RT Cache Agent Comms - 2026-04-02

This is the `hashall` coordination note for other repo agents working the same
RT cache / RT load incident.

## Status

- `hashall` now treats shared silo RT cache as the default read contract for RT
  monitoring state.
- `hashall rt state-audit` is cache-backed by default and does not silently
  fall back to RT XMLRPC.
- Explicit direct RT access remains allowed only for:
  - mutations
  - repairs
  - explicit `--live` diagnostics

## Inputs used

- `/mnt/config/docker/.agent/worktrees/cr-docker-20260329-175737-codex/docs/agent-prompts/silo-rt-cache-hardening-prompt-2026-04-02.md`
- `/mnt/config/docker/.agent/worktrees/cr-docker-20260329-175737-codex/docs/agent-prompts/hashall-rt-cache-alignment-prompt-2026-04-02.md`
- `/mnt/config/docker/.agent/worktrees/cr-docker-20260329-175737-codex/docs/rt-arr-qb-path-handoff-2026-04-01.md`

## What changed in hashall

- Added:
  - `src/hashall/rt_cache.py`
- Updated:
  - `src/hashall/cli.py`
  - `tests/test_cli_content.py`
- Canonical repo note:
  - `docs/operations/RT-CACHE-ALIGNMENT-2026-04-02.md`

## Expectations for other repo agents

### Docker repo agent

- Treat shared RT cache as the normal monitoring interface.
- Do not assume `hashall` still needs direct RT reads for dashboards or bad-state summaries.
- Keep mutation and repair flows separate from cache-backed monitoring.

### Silo / cache-hardening agent

- `hashall` now depends on the cache contract and cache metadata being explicit
  when degraded.
- Preserve fields like:
  - `source`
  - `last_error`
  - `fetched_at`
  - `xmlrpc_url`
  - `consecutive_failures`
- Avoid changing cache row semantics casually; `hashall` now normalizes against
  the current shared JSON shape.

### Future hashall agent

- Do not reintroduce silent live fallback for read-only RT commands.
- If adding a new RT read path, default to:
  - shared cache, or
  - RT session files
- Only use direct RT XMLRPC by default for commands that mutate state.

## Open questions / follow-up

- If the Docker/silo side changes cache row keys beyond `save_path`, `state`,
  `hash`, `name`, `message`, `tracker`, `peers`, `dlspeed`, `upspeed`, update
  `src/hashall/rt_cache.py` in lockstep.
- If a future shared cache adds richer RT fields, prefer consuming them there
  instead of adding new direct RT reads in `hashall`.
