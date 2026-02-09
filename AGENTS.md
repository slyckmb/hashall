# AGENTS — Repo Entry Point

**Global defaults**: `~/.agent/AGENTS_GLOBAL.md`

This repo doc is intentionally thin and points to the global guide, which defines:
- Environment detection (glider vs surfer)
- Path conventions
- Command routing (heavy ops on glider)
- `mkvenv` usage
- Safety rules and baseline protocol

## Baseline Protocol

- If `.agent/baseline.md` exists, read it first — objective facts about repo state.
- Do not ask the user whether things were dirty before; use the baseline.
- Do not commit, delete files, or modify `.gitignore` without explicit approval.

## Repo-Specific Context

- `docs/NEXT-REMOTE-AGENT-PROMPT.md`
- `docs/REMOTE-PREAMBLE.md`
