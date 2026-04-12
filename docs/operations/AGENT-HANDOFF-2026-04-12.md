# Agent Handoff

Last updated: 2026-04-12

## Sitrep

- Branch: `cr/hashall-20260408-171803-codex`
- Last committed fix: `be67694` `fix(payload-sync): refresh final counts after upgrade`
- Current uncommitted files:
  - `src/hashall/cli.py`
  - `tests/test_cli_payload_sync.py`
- New uncommitted feature:
  - `hashall rt repair-assistant`
  - read-only only
  - outputs only:
    - `broken_now`
    - `current_client_path`
    - `best_candidate_path`
    - `confidence`
    - `why`
    - `safe_to_mutate`
- Focused verification passed:
  - `python -m py_compile src/hashall/cli.py tests/test_cli_payload_sync.py`
  - `PYTHONPATH=src pytest tests/test_cli_payload_sync.py -q`
  - `34 passed`

## Critical Context

- Hashall is useful as a read-only evidence engine.
- Hashall should not drive live qB/RT mutations by itself.
- Earlier live repair wave was too aggressive.
- Specific bad mutation:
  - `a203d6a201414382ea1a46c8170131d3017beac2`
  - was moved incorrectly
  - later restored to:
    - qB: `/data/media/torrents/seeding/_qb-finish/a203d6a201414382ea1a46c8170131d3017beac2`
    - RT: `/data/media/torrents/seeding/_qb-finish/a203d6a201414382ea1a46c8170131d3017beac2`
- Existing `rt repoint` and `rt recheck` end with `d.start`; they do not preserve prior stopped/seed-only state.
- Safe model:
  - hashall: evidence only
  - docker/client agent: mutation layer
  - mutate only if:
    - item is still broken now
    - there is one clearly best candidate
    - state handling is explicit

## Next Work

1. Review uncommitted `rt repair-assistant` implementation.
2. Decide whether to commit it as-is or tighten the proof gate further.
3. Do not run more live qB/RT repair waves from hashall until state-preserving client-side helpers exist.
4. If using the new mode, use it only for read-only decisions.

## Ready Prompt

```text
Read:
- docs/operations/AGENT-HANDOFF-2026-04-12.md
- docs/operations/RT-QB-REPAIR-HANDOFF-2026-04-09.md

Work only in:
- /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260408-171803-codex
- branch cr/hashall-20260408-171803-codex

Current uncommitted files:
- src/hashall/cli.py
- tests/test_cli_payload_sync.py

Task:
- inspect the new `hashall rt repair-assistant` mode
- confirm it stays read-only
- confirm it only outputs:
  - broken_now
  - current_client_path
  - best_candidate_path
  - confidence
  - why
  - safe_to_mutate
- tighten proof rules if needed so ambiguous cases always yield `safe_to_mutate=no`
- do not perform any live qB/RT mutations
```
