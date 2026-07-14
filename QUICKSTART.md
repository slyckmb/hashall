# QUICKSTART - hashall-20260626-151456

Updated: 2026-07-13 22:06:34
Model tier: small
Agent: codex

## Session Identity

- chat_id: `hashall-20260626-151456`
- branch: `cr/hashall-20260626-151456__j59`
- worktree: `/home/michael/dev/work/hashall/.chatrap/worktrees/hashall-20260626-151456__j59`
- current CR head at refresh: see `git rev-parse HEAD`

## Current Goal

Harden RT/qB state mutation enforcement before further live repair.

## Current Step

j57 is next. OP-69 showed the safety process was bypassable during recurring
RT/qB state repairs. Finish j57 before j51 live qB stoppedDL apply or j39 RT PD
repair. j51 read-only refresh/bucket/drain planning may continue.

## Recent Commits (last 5)

```
1e8494c chore: regen QUICKSTART + REPO-MASTERY (after-job j38)
986cc36 lead: after-job post-merge j38 — OP closure + JOB-QUEUE replan + INIT advance
9652d01 lead: advance closeout to j40 docs batch
7037f25 merge(cr/hashall-20260530-000517-claude__j38)
6324c06 fix(j38-t02): validate RT repoint targets before writes
```

## Next Work

(no jobs.json found)

See `chatrap lead status` for current job state.

## Open OPs (summary)

Open OPs are tracked in OPS.md and slotted in JOB-QUEUE.md. OP-69 is the current
hardening blocker.

## Current State

See JOB-QUEUE.md for authoritative job status.

## Lead Operating Pattern

Source mutations require a task brief and `chatrap dispatch`. Task logs go under `.chatrap/task-logs/<chat_id>/<job>/<task>/`. Direct dispatch (`--direct=`) for 1-3 line fixes.

Live RT/qB mutation must use the full 4-Gate protocol or the surgical mini-gate.
Direct helper/API/XMLRPC mutation is forbidden except hash-scoped qB stop-only
containment. Use `docs/RT-QB-SURGICAL-REPAIR-RUNBOOK.md` for explicit repairs.

## Closeout Rules

- Run `chatrap job done` from the job worktree when closing a job.
- If conflict: resolve, `git commit --no-edit`, clean up worktree manually (OP-130).
- Run `GIT_AUTHOR_NAME=codex GIT_AUTHOR_EMAIL=codex@chatrap.local chatrap ack commit HEAD`.
- After merging prompt changes: run `./bin/chatrap regen-shared`.

## Validation Reminders

- Run focused tests for the touched subsystem.
- For docs-only refreshes, run `git diff --check`.
