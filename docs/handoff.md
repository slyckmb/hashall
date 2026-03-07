# Handoff Entry (Compact-Safe)

Canonical living state:
- `docs/operations/RUN-STATE.md`
- `docs/project/PLAN.md`

Current branch/worktree:
- `chatrap/codex-hashall-20260305-181919`
- `/home/michael/dev/work/hashall/.agent/worktrees/codex-hashall-20260305-181919`

Current versions:
- `hashall 0.4.145`
- `rehome 0.6.11`

Newest committed fixes to preserve:
- `f1d3208` `fix(rehome-refresh): accept zero-upgrade payload sync summaries`
- `e6d6feb` `feat(qb-repair): derive stoppedDL root policy from seed-root-state`

Current operational facts:
- `~/.hashall/seed-root-state.json` is the canonical machine-readable seed-root contract.
- `hashall` is the sole writer; external tools are read-only consumers.
- `qb-stoppeddl-drain.py` and `qb-stoppeddl-apply.py` now default their allowed roots from that contract, but only admit pool-backed roots by default.
- The refresh failure where payload sync ended `PARTIAL` on zero upgrade work is fixed for future runs.
- The earlier hidden confirmation prompt and `Plan #59` `ActionInfo` crash are also fixed.

Still open:
- improve long-running refresh heartbeat/progress visibility
- continue qB migration/rehome audit beyond stoppedDL drain/apply
- produce the pilot-safe dataset migration lane for `/pool/data/media/torrents/seeding -> /pool/media/torrents/seeding`
- reduce status docs further if more non-canonical variants remain

Historical snapshot:
- `docs/archive/2026-doc-reduction/snapshot/docs/handoff.md`
