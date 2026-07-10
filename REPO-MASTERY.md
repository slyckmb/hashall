# Chatrap - Repo Mastery Reference

Session: `hashall-20260626-151456`
Updated: 2026-07-05

## What This Repo Is

hashall manages torrent payload/path state across rTorrent, qBittorrent,
filesystem catalogs, hardlink/orphan analysis, and Chatrap job orchestration.

## Core Components

- `src/hashall/` - hashall library and CLI implementation.
- `bin/` - operational tools and wrappers.
- `scripts/` - focused maintenance scripts.
- `docs/` - canonical operating policy and RCCA records.
- `comms/docs/` - current operating SOPs and job-local planning docs.
- `prompts/system/` - injected session and job rules.
- `JOB-QUEUE.md` - authoritative job plan.
- `OPS.md` - open/closed operations ledger.
- `tests/` - focused regression coverage.

## Current Architecture Rules

- Active CR worktree: `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456`
- Active branch: `cr/hashall-20260626-151456`
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

j57 `rt-qb-state-guard` is the next blocker before further live RT/qB repair
mutation. j51 read-only qB stoppedDL refresh/bucket/drain work may continue, but
j51 live apply and j39 RT repairs must wait for j57 guard/enforcement.

## Open OPs

See OPS.md and JOB-QUEUE.md. OP-69 is slotted to j57 and blocks informal live
RT/qB repair paths.

## High-Risk Areas

- `bin/chatrap-job.sh` - destructive lifecycle operations.
- `lib/chatrap-common.sh` - shared resolution and tmux helpers.
- `bin/chatrap-session.sh` / `lib/chatrap-session.sh` - session state.
- `prompts/system/*.md` - injected operator rules.
- `hooks/pre-commit.chatrap` - commit guardrails.
- RT/qB client state and filesystem mutation tools - operationally high risk.

## Safety Rules

- Never commit to main or master
- Never write repo files outside the active worktree without explicit approval
- Run GIT_AUTHOR_NAME=codex GIT_AUTHOR_EMAIL=codex@chatrap.local chatrap ack commit HEAD before reporting any commit done
- After merging prompt changes: run ./bin/chatrap regen-shared (worktree binary)
- Any live RT/qB state mutation must use the full 4-Gate protocol or the
  surgical mini-gate. Direct helper/API/XMLRPC mutation is forbidden except
  hash-scoped qB stop-only containment.
- qB is passive. Active qB upload/download states are containment incidents.
- RT surgical repair must verify every torrent metadata file, hash-check, and
  start only when RT reports complete.

## Key Process Protocols

- [4-Gate Mutation Protocol](docs/4-GATE-MUTATION-PROTOCOL.md) — required before live RT/qB mutation
- [RT/qB State Policy](docs/RT-QB-STATE-POLICY.md) — authoritative desired client states
- [RT/qB Surgical Repair Runbook](docs/RT-QB-SURGICAL-REPAIR-RUNBOOK.md) — explicit-hash repair path
- [RT/qB 99 Percent Content-Variant Repair Runbook](docs/RT-QB-99PCT-CONTENT-VARIANT-REPAIR.md) — sibling hardlink repair process for 99.* content-variant failures
- [StoppedDL SOP](comms/docs/STOPPEDDL-SOP.md) — qB stoppedDL recovery pipeline

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
6. When do you use full 4-Gate vs surgical mini-gate?
7. What is the only live RT/qB mutation allowed outside a gate?
8. What qB states are forbidden for the passive mirror?
9. When may an RT repair start a torrent?
10. Which artifacts prove a surgical repair passed?

## Recent Changes

```
d836a67 lead: record rt-qb state regression tracking
af6168d lead: split j51 into smaller recovery slices
9fa8d20 lead: close resolved j50 friction op
6a850db lead: after-job post-merge j50 — OP closure + JOB-QUEUE replan + INIT advance
c518db9 merge(cr/hashall-20260626-151456__j50)
```
