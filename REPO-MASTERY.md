# Chatrap - Repo Mastery Reference

Session: `hashall-20260530-000517-claude`
Updated: 2026-06-25 12:46:02

## What Chatrap Is

Chatrap is a Bash/tmux/git-worktree orchestration layer for AI coding sessions.

## Core Components

- `bin/chatrap` - main dispatcher.
- `bin/chatrap-job.sh` - job lifecycle.
- `bin/chatrap-session.sh` - session state and lifecycle.
- `lib/chatrap-common.sh` - shared helpers.
- `prompts/system/` - injected session and job rules.
- `JOB-QUEUE.md` - authoritative job plan.
- `tests/` - focused regression coverage.

## Current Architecture Rules

- Active CR worktree: `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude`
- Active branch: `cr/hashall-20260530-000517-claude`
- Job branches use `cr/<chat_id>__jNN`.
- Job and task identifiers are lowercase: `jNN`, `tNN`, `jNN-tNN`.
- Prefer the worktree `./bin/chatrap` for validation.
- `comms/` is ignored and reserved for task briefs and coordination files.

## Lead Responsibilities

- Maintain repo mastery before dispatching work.
- Translate user intent into OPs, job plans, and task briefs.
- Review task logs, commits, and validation before acceptance.
- Update session artifacts when operating doctrine changes.
- Run S05 checks on every commit before reporting done.

## Agent Execution Pattern

Use `opencode run` with a brief file under `comms/briefs/` and tee output to a log file.

## Completed Work This Session

See JOB-QUEUE.md for the authoritative completed-job list.

## Next Work

(see JOB-QUEUE.md)

## Open OPs

(none)

## High-Risk Areas

- `bin/chatrap-job.sh` - destructive lifecycle operations.
- `lib/chatrap-common.sh` - shared resolution and tmux helpers.
- `bin/chatrap-session.sh` / `lib/chatrap-session.sh` - session state.
- `prompts/system/*.md` - injected operator rules.
- `hooks/pre-commit.chatrap` - commit guardrails.

## Safety Rules

- Never commit to main or master
- Never write repo files outside the active worktree without explicit approval
- Run GIT_AUTHOR_NAME=codex GIT_AUTHOR_EMAIL=codex@chatrap.local chatrap ack commit HEAD before reporting any commit done
- After merging prompt changes: run ./bin/chatrap regen-shared (worktree binary)

## Useful Commands

  chatrap lead status          — role + location + next job + first action (step 0 post-clear)
  chatrap session read         — goal and current step from SESSION.md
  chatrap ack lead --repo-root . — mastery gate check
  git log --oneline -8
  git status --short
  GIT_AUTHOR_NAME=codex GIT_AUTHOR_EMAIL=codex@chatrap.local chatrap ack commit HEAD

## Mastery Self-Check

Before operating as lead after /clear, answer these without more browsing:

1. What is the active CR branch and worktree?
2. Which files are the authoritative OP and job-plan ledgers?
3. Which job is next?
4. What command closes a job, and what must happen if it fails non-zero?
5. What spelling convention is required for jobs and tasks?

## Recent Changes

```
eae0556 merge(cr/hashall-20260530-000517-claude__j29)
f8293ed fix(rtorrent): OP-37 final-read after poll timeout + OP-31 check_before_start on 8 callers
M	src/hashall/__init__.py
M	src/hashall/cli.py
M	src/hashall/hitchhiker_split.py
M	src/hashall/nested_folder_repair.py
M	src/hashall/rtorrent.py
M	src/hashall/save_path_recovery.py
M	src/hashall/save_path_repair.py
M	tests/test_rtorrent_safe_start.py
4efdb62 docs(ops): close OP-33 — Snowfall S05 pool copy repaired by j28 batch, now seeding
M	docs/OPS.md
d490b67 docs(ops): full RCCA for all 20 remaining stopped items — add OP-38..41, update OP-29/34/35/36
M	docs/OPS.md
f46d796 docs(ops): add OP-37 — rt_check_and_conditionally_start leaves stoppedUL on hash-check timeout
M	docs/OPS.md
```
