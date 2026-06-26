# QUICKSTART - hashall-20260530-000517-claude

Updated: 2026-06-26 13:34:24
Model tier: small
Agent: claude

## Session Identity

- chat_id: `hashall-20260530-000517-claude`
- branch: `cr/hashall-20260530-000517-claude`
- worktree: `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude`
- current CR head at refresh: `1e8494c`

## Current Goal

Code bug fixes + RCCA + cross-seed repair + docs toward CR→main merge (j37–j45)

## Current Step

j38 merged: RCCA path audit added, RT repoint target-exists guard implemented, version 0.8.69. OP-19/24/47 follow-ups moved to j39. Next dispatch: j40-t01 docs-batch audit/plan.

## Recent Commits (last 5)

```
1e8494c chore: regen QUICKSTART + REPO-MASTERY (after-job j38)
986cc36 lead: after-job post-merge j38 — OP closure + JOB-QUEUE replan + INIT advance
9652d01 lead: advance closeout to j40 docs batch
7037f25 merge(cr/hashall-20260530-000517-claude__j38)
6324c06 fix(j38-t02): validate RT repoint targets before writes
```

## Next Work

(see JOB-QUEUE.md)

See JOB-QUEUE.md for full task breakdown.

## Open OPs (summary)

31 open OPs; all are slotted in JOB-QUEUE.md. j40 is next per run order.

## Current State

See JOB-QUEUE.md for authoritative job status.

## Lead Operating Pattern

Use file-backed opencode runs with task briefs in `comms/briefs/` and tee logs under `.agent/logs/`.

## Closeout Rules

- Run `chatrap job done` from the job worktree when closing a job.
- If conflict: resolve, `git commit --no-edit`, clean up worktree manually (OP-130).
- Run `GIT_AUTHOR_NAME=codex GIT_AUTHOR_EMAIL=codex@chatrap.local chatrap ack commit HEAD`.
- After merging prompt changes: run `./bin/chatrap regen-shared`.

## Validation Reminders

- Run focused tests for the touched subsystem.
- For docs-only refreshes, run `git diff --check`.
