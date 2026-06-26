# RCCA: CR Branch Accidentally Merged into Main Twice

**Date:** 2026-06-25  
**Session:** hashall-20260530-000517-claude (j28 lead phase)  
**Symptom:** `main` advanced to `235426a`, two unexpected merge commits present  
**Immediate action:** `git -C /home/michael/dev/work/hashall reset --hard 1879b35` — main restored

---

## What Happened

During j28 setup, two `git merge cr/hashall-20260530-000517-claude` operations ran against
`main` instead of the intended j28 worktree branch:

| Commit | When | Cause |
|--------|------|-------|
| `36157df` | Earlier in session (pre-context-compaction) | Lead ran merge from flat j28 path |
| `235426a` | 2026-06-25 | Lead ran merge from flat j28 path again to "update j28 worktree" |

Both were caused by the same mistake: running `git -C <flat-j28-path> merge ...` where
`<flat-j28-path>` is not a registered git worktree.

---

## Root Cause

### The flat j28 path is not a registered worktree

The j28 "worktree" was created by a previous session as a directory for holding gitignored
`comms/` files only — not as a proper `git worktree add` registered worktree:

```
/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j28/
  comms/
    briefs/
      TASK-BRIEF-j28-t01.md
      TASK-BRIEF-j28-t02.md
```

This path sits **inside** the main repo's working tree
(`/home/michael/dev/work/hashall/`). When `git -C` is run from any path under
`/home/michael/dev/work/hashall/` that isn't a registered worktree, git walks up
and finds the main repo at `/home/michael/dev/work/hashall/.git`. All git operations
then execute against `main`.

### The actual j28 worktree (registered) is nested inside the CR worktree

```
/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude/.agent/worktrees/hashall-20260530-000517-claude__j28
  [branch: cr/hashall-20260530-000517-claude__j28, HEAD: ba714f1]
```

This is the path that `git worktree list` returns. It is nested inside the CR worktree,
not at the flat path. The INIT.md notes reference a "j22 lesson" about using absolute paths
to avoid nesting — but the flat path was created anyway, creating a second directory that
looks like the j28 worktree but isn't one.

### The check that should have caught this

Before running any `git merge`, the lead should have verified:

```bash
git -C <path> branch --show-current
```

This would have returned `main`, which is an immediate STOP condition per worktree compliance
rules. The lead did not run this check before merging.

---

## Timeline

| Time | Event |
|------|-------|
| Earlier in session (pre-compaction) | Lead ran `git -C <flat-j28> merge cr/...` → commit `36157df` on main |
| 2026-06-25 | Lead ran same command again to "bring j28 up to date" → commit `235426a` on main |
| 2026-06-25 | Lead noticed main was at `235426a`, identified root cause |
| 2026-06-25 | User authorized `git reset --hard 1879b35` → main restored |

---

## Fix / Prevention

### Immediate: verify branch before any git mutation

Before any `git merge`, `git reset`, `git commit`, or `git checkout` on a worktree path:

```bash
BRANCH=$(git -C "$PATH" branch --show-current)
echo "Branch: $BRANCH"
# STOP if BRANCH == main or master
```

### Structural: never use the flat `__jNN` path for git operations

The flat path `<CR_WORKTREE>/../<chat_id>__<job>` (sibling of the CR worktree, inside
main repo) is a comms-only directory. It is not a git worktree and must never receive
git commands.

The registered j28 worktree path is nested inside the CR worktree:
```
<CR_WORKTREE>/.agent/worktrees/<chat_id>__<job>
```

Use `git worktree list` to find the canonical path before dispatching any agent or running
any git command against a job worktree.

### Lead SOP addition

Add to the lead dispatch checklist:

1. Run `git worktree list` to confirm job worktree path
2. Verify `git -C <job_worktree_path> branch --show-current` returns the job branch (not `main`)
3. Only then copy briefs and dispatch

---

## Lessons

1. **`git -C <path>` silently falls through to an enclosing repo** if `<path>` is not a
   registered worktree. There is no error — it just operates on the wrong repo.

2. **Two directories with similar names exist**: the flat sibling path and the nested
   registered worktree path. They are different. The flat one is not git-aware.

3. **Branch verification is the single most important check** before any git operation
   in a chatrap session. Cost: one command. Benefit: prevents contamination of `main`.
