# RT Cache Alignment - 2026-04-02

## Purpose

Record the `hashall` side of the cross-repo RT cache coordination that was
requested from:

- `docs/agent-prompts/silo-rt-cache-hardening-prompt-2026-04-02.md`
- `docs/agent-prompts/hashall-rt-cache-alignment-prompt-2026-04-02.md`

This note is intended for other repo agents working the Docker, silo, or
`hashall` side of the same incident.

## Outcome

`hashall` no longer uses live RT XMLRPC by default for its ordinary RT state
reporting path.

The command:

- `hashall rt state-audit`

is now:

- shared-cache-backed by default
- fail-closed with respect to live RT polling
- explicit-live only when the operator passes `--live`

## Static Audit Classification

### Cache / session-backed read paths

These paths do not need live RT XMLRPC in their default read mode:

- `hashall content reclaim-report`
  - protects live RT-owned roots via `.torrent.rtorrent` session data
- `hashall rehome drift-audit`
  - compares plan state to RT session roots via `.torrent.rtorrent`
- `hashall rt session-audit`
  - session-file only
- `hashall rt repair-report`
  - session-file only
- `hashall rt state-audit`
  - shared cache by default as of this change

### Direct RT mutation paths

These still use live RT XMLRPC intentionally:

- `hashall rt repoint`
- `hashall rt recheck`
- `hashall rt session-reset`
- `hashall rt repair-apply`

### Explicit direct diagnostics

These remain acceptable as opt-in live diagnostics:

- `hashall rt state-audit --live`

## Runtime Validation

### Cache-backed execution

Command run:

```bash
python -m hashall.cli rt state-audit --bad-only --limit 5 --json-output
```

Observed summary highlights:

- `read_mode = shared_cache`
- `freshness = stale_error`
- `cache_source = daemon_error`
- `last_error = rTorrent returned empty result from http://localhost:18000/RPC2`

This confirms `hashall` is surfacing degraded cache state rather than silently
falling back to direct RT polling.

### Socket-level proof

Command run:

```bash
strace -f -e trace=connect -o /tmp/hashall-rt-state-audit.strace \
  python -m hashall.cli rt state-audit --bad-only --limit 1 --json-output
```

Observed result:

- no connects to `:18000`
- no connects to `:8000`

So the default read-mode execution no longer opens RT sockets.

## Files Changed In This Step

- `src/hashall/rt_cache.py`
- `src/hashall/cli.py`
- `tests/test_cli_content.py`

## Direction For Other Repo Agents

### Silo agent

Still required:

- harden the RT cache daemon transport
- prefer healthy container-local RT transport when host transport is broken
- keep cache-mode dashboards fail-closed and read-only

`hashall` now assumes the shared cache is the contract for RT monitoring reads.

### Docker agent

The Docker repo should continue treating:

- shared RT cache as the normal monitoring contract
- direct RT polling as an overload risk unless explicitly requested

No additional `hashall` changes are required in Docker for this read-path fix.

### Future hashall agent

Do not reintroduce silent live RT fallback for read-only/reporting paths.

If a new RT reader is added, classify it explicitly as one of:

- cache/session-backed read
- direct mutation
- explicit live diagnostic

If the new command is read-only, default it to shared cache or RT session files,
not XMLRPC.
