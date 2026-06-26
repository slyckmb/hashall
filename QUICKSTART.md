# QUICKSTART - hashall-20260530-000517-claude

Updated: 2026-06-26 12:18:49
Model tier: small
Agent: claude

## Session Identity

- chat_id: `hashall-20260530-000517-claude`
- branch: `cr/hashall-20260530-000517-claude`
- worktree: `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude`
- current CR head at refresh: `0ce996e`

## Current Goal

Post-12b repair: T1 operator review, then T2a-T2e path repairs toward zero mismatches

## Current Step

j29 merged: OP-37 (rt_check_and_conditionally_start final-read fix) + OP-31 (8 callers check_before_start=True); 6 tests pass; next: j30 remove-leeching-started (Coursera, Domestika x2, Priscilla)

## Recent Commits (last 5)

```
eae0556 merge(cr/hashall-20260530-000517-claude__j29)
f8293ed fix(rtorrent): OP-37 final-read after poll timeout + OP-31 check_before_start on 8 callers
4efdb62 docs(ops): close OP-33 — Snowfall S05 pool copy repaired by j28 batch, now seeding
d490b67 docs(ops): full RCCA for all 20 remaining stopped items — add OP-38..41, update OP-29/34/35/36
f46d796 docs(ops): add OP-37 — rt_check_and_conditionally_start leaves stoppedUL on hash-check timeout
```

## Next Work

(see JOB-QUEUE.md)

See JOB-QUEUE.md for full task breakdown.

## Open OPs (summary)

(none)

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
