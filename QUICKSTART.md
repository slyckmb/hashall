# QUICKSTART — hashall-20260530-000517-claude

_Read this first after /clear. Everything you need to resume in under 2 minutes._

---

## 1. Session Identity

| Field | Value |
|-------|-------|
| Chat ID | `hashall-20260530-000517-claude` |
| CR branch | `cr/hashall-20260530-000517-claude` |
| CR worktree | `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude` |
| Lead pane | `%324` |
| Agent pane | `%463` (OpenCode / DeepSeek V4 Flash, Go tier) |

---

## 2. Current Goal

Zero-drift, zero non-canonical paths — build and validate a unified path resolver
tool based on `docs/CANONICAL-PATH-SPEC.md`, then use it to make one correct move
per item (combining rehome + path fix) rather than chaining broken piecemeal tools.

---

## 3. Session Summary — What Has Been Done

| Job | Delivered |
|-----|-----------|
| j09 | Cold-read audit of 5 mutation tools, 47 findings, OPS.md created |
| j10 | 3 critical bug fixes: `_resolve_full_hash`, `set_location` pause guard, `repoint_both_to_pool` order |
| j11 | Gate 1+2 cert for drift fix; Gate 3 pilot blocked by cross-device guard (correct); Class 4 root cause (84 items) |
| j12 | Cross-device guard bypass (`_files_exist_at_target`); both HIGH drift items cleared; drift high=0 |
| j13 | `CANONICAL-PATH-SPEC.md` v1.0.0-draft — unified 5-step decision tree covering all 4898 items |

**Current drift baseline (2026-06-17):** 3 items (high=0, low=2, medium=1)

---

## 4. Migration Moratorium (CRITICAL)

**No mutations** from `rehome`, `save_path_inference`, or `save-path-repair --execute`
until the unified path resolver (OP-18) is implemented and 4-gate validated.

Both tools have caused mass displacement at scale. The spec replaces them.
Dry-run and audit commands remain permitted.

---

## 5. The Canonical Path Spec

**`docs/CANONICAL-PATH-SPEC.md`** is the authoritative reference for all path decisions.
Read it before writing any path-related code. Key points:

- 5-step tree: pre-screen → classify (qB category + tags) → WHERE (stash/pool) → WHAT PATH → assemble → diff both clients
- Neither RT nor qB is assumed correct — the tree is the arbiter
- 2393 items have missing `cross-seed/` prefix (OP-17) — HOLD, awaiting migration strategy
- `~noHL` is advisory only — never authoritative, requires `--full-scan` verification before any pool move
- Single-file torrents: no subdirectory unless torrent internally defines one

---

## 6. Next Actions

1. **Brief j14** — implement the unified path resolver tool per `CANONICAL-PATH-SPEC.md`
   - Read-only audit output first (dry-run report per item: actual vs canonical)
   - 4-gate validation before any execute path is written
   - OP-16 fix (`save_path_inference.py` line 223) likely part of this job

2. **Decide migration strategy** for the 2393 HOLD items before any execution

3. **Context threshold hit** (`context_steps=20`) — run `/clear` before briefing j14

---

## 7. Key Commands

```bash
# Confirm worktree context
git branch --show-current  # must show cr/hashall-20260530-000517-claude

# Check agent pane
tmux capture-pane -t %463 -p | tail -20

# Send brief to agent
tmux send-keys -t %463 "[chatrap-lead] <TASK_ID> brief: read <PATH> — ack to %324" Enter

# Drift audit (always ANCHOR_SCAN=200000)
make -C /home/michael/dev/work/hashall client-drift-audit ANCHOR_SCAN=200000

# Create next job
chatrap job --name <slug>   # from CR worktree

# Close job
cd <job-worktree> && chatrap job done
```

---

## 8. Key Files

| File | Purpose |
|------|---------|
| `docs/CANONICAL-PATH-SPEC.md` | Authoritative path resolution spec — read before any path work |
| `docs/AGENT-MASTERY.md` | Full repo context, invariants, moratorium, policy rules |
| `docs/OPS.md` | 19 open items — OP-16 (code fix), OP-17 (2393 migration HOLD), OP-18 (unified tool) |
| `docs/REQUIREMENTS.md` | System requirements and §4.4 canonical path formula |
| `SESSION.md` | Live session goal + step |
