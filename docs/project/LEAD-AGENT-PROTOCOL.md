# Lead–Agent Injection Protocol

**Version:** 0.3.1
**Status:** Active — evolving through session hashall-20260530-000517-claude  
**Last updated:** 2026-09-06
**Scope:** Defines the full contract between the Web Lead and CLI Agent for task
briefs, PR-native launch, reporting, and job lifecycle management.

---

## 1. Role Model

| Role | Who | Responsibilities |
|---|---|---|
| **User** | Operator | Sets goals, approves direction, owns final acceptance |
| **Lead** | Web UI agent (this doc's author) | Writes briefs, posts PR-native handoffs, reads logs, drives decisions, issues one task at a time |
| **Agent** | CLI agent (OpenCode / Claude Code) | Hydrates the PR-native handoff, executes the bounded task, writes logs, never broadens scope |

The Lead writes **one brief at a time**. The Agent executes and returns **one log**.
The Lead reads the log, decides, writes the next brief.

---

## 2. Task ID Format

All task IDs use zero-padded job-scoped format:

```
J<NN>-T<NN>
```

| Component | Format | Example |
|---|---|---|
| Job | `J` + 2-digit zero-padded | `J01`, `J02`, `J03` |
| Task | `T` + 2-digit zero-padded | `T01`, `T02`, `T15` |
| Combined | `J<NN>-T<NN>` | `J02-T03`, `J03-T01` |

**Rules:**
- Always zero-padded (`T01` not `T1`)
- Always job-scoped (`J02-T01` not `T01`)
- Never dots (`T2.1` — deprecated), unpadded (`T1`), or flat (`T03` alone)
- Lead assigns IDs; Agent uses them verbatim

---

## 3. Directory Structure

### Canonical task path (local)
```
<worktree>/jobs/<N>-<job-slug>/tasks/<JNN>-<TNN>--<task-slug>/
  TASK-BRIEF.md     ← Lead writes before launch
  TASK-LOG.md       ← Agent writes after completion
```

### GDrive mirror path
```
/mnt/gdrive/chatrap/repos/<repo>/jobs/<N>-<job-slug>/tasks/<JNN>-<TNN>--<task-slug>/
  TASK-BRIEF.md
  TASK-LOG.md
```

### Naming conventions
- Job dir: `<N>-<job-slug>` — number is not zero-padded at directory level (e.g., `2-operational-verification`)
- Task dir: `<JNN>-<TNN>--<task-slug>` — double-dash between ID and slug

### Examples
```
jobs/2-operational-verification/tasks/J02-T01--catalog-refresh/TASK-BRIEF.md
jobs/3-pending-repairs/tasks/J03-T01--repoint-drift-high/TASK-BRIEF.md
/mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T01--repoint-drift-high/TASK-LOG.md
```

---

## 4. Color Convention

| Color | Emoji | Used for |
|---|---|---|
| Blue | 🟦 | Lead → Agent: task-brief wrapper |
| Magenta | 🟪 | Agent → Lead: task-log wrapper |
| Green/Yellow/Red | 🟩🟨🟥 | Lead boundary `ok-to-clear` status blocks |

Wrappers must appear **inside fenced code blocks** (paste-ready copy boxes).

---

## 5. TASK-BRIEF.md Format

### File structure
```markdown
---
id: J<NN>-T<NN>
job: <N>-<job-slug>
slug: <task-slug>
task_type: discovery|implementation|verification|closeout
status: staged
brief_revision_id: <N>
created_by: lead
created_at: <YYYY-MM-DD>
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# <ID> — <Title>

## Context
<prior task findings relevant to this task>

## Bootstrap Context
<session/worktree/branch/head block>

## Brief
<fenced code block containing the 🟦 task-brief= block>

## Expected Agent Report Format
<fenced code block containing the 🟪 task-log= template>

## After completing this task
<write TASK-LOG.md, mirror, and PR-report instructions>
```

### 🟦 task-brief= block fields (required)
```
🟦 task-brief=J<NN>-T<NN>_<slug> 🟦

id=J<NN>-T<NN>
role=agent
task_type=discovery|implementation|verification|closeout
goal=<one sentence>

repo=<slug>
worktree=<absolute path>

expected_branch=<branch>
expected_head=<full sha>

allowed_mutation=none|files-only|files+commits|unrestricted

allowed_commands=
- ...

forbidden_commands=
- ...

required_artifacts=
- ...

success_criteria=
- ...

stop_if=
- ...

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J<NN>-T<NN>_<slug> 🟦
```

### Lead rules when writing briefs
- One task per brief — never combine claim + send, send + verify, cleanup + live action
- Do not reference future task IDs or names — use `"future TBD by lead after current task log"`
- Include prior task findings in Context section so agent has necessary data
- Provide all Lead-known data values directly — do not make agent re-run commands for data already gathered
- `expected_head` must be current at time of dispatch — verify before writing

---

## 6. TASK-LOG.md Format

Agent writes this to disk after completing work.

```
🟪 task-log=J<NN>-T<NN>_<slug> 🟪

status="done|blocked"
task_id="J<NN>-T<NN>"
task_type="discovery|implementation|verification|closeout"
branch="<branch>"
head="<sha of HEAD at task completion>"
changed="<files changed or none>"
mutations="<description or none>"
validation="<one-line summary of what passed>"
artifacts="<description of artifacts>"
worktree_mirror_status="synced|blocked|not_configured"
worktree_mirror_path="path_or_none"
worktree_mirror_head="sha_or_none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

<extracted key=value fields specific to this task>

<full terminal output>

🟪 task-log=J<NN>-T<NN>_<slug> 🟪
```

### Agent rules when writing logs
- `next=` must always be `"future TBD by lead after current task log"` — no context pollution
- Write to local task dir AND mirror to GDrive — both required
- Include full terminal output, not just summaries
- Head reported must be the actual HEAD at completion — may differ from expected_head if commits happened

---

## 7. Agent Closeout Sequence (after every task)

Required steps in order:

```bash
# 1. Write TASK-LOG.md locally
# (agent writes file content)

# 2. Mirror to GDrive
cp <worktree>/jobs/<N>-<slug>/tasks/<JNN-TNN>--<slug>/TASK-LOG.md \
   /mnt/gdrive/chatrap/repos/<repo>/jobs/<N>-<slug>/tasks/<JNN-TNN>--<slug>/TASK-LOG.md

# 3. Post the required report to the bound PR
# The PR report is durable coordination; the local log remains the Hashall
# task artifact and must still be mirrored when configured.
```

---

## 8. Lead Launch Sequence

Steps in order for each task:

```bash
# 1. Write TASK-BRIEF.md
# (Lead writes file)

# 2. Mirror to GDrive
cp <worktree>/jobs/.../TASK-BRIEF.md /mnt/gdrive/.../TASK-BRIEF.md

# 3. Publish a reset-safe handoff to the task's bound Hashall PR
#    It includes the brief's bounded content and current PR head as Based-On.

# 4. Launch the selected native client through Airo. Do not inject a local
#    brief path into an interactive TUI.
set -o pipefail
pr-agent <client> worker slyckmb/hashall <PR> \
  --model <model> --cwd <worktree> |& tee <launcher-transcript.log>
```

The launcher transcript is diagnostic foreground output; it is not the worker-authored
`TASK-LOG.md`. The runner's default prompt is `work slyckmb/hashall PR #<PR>`; the worker
recovers the handoff from the PR. Do not supply the local brief as a launcher
argument or override that prompt merely to inject it.

---

## 9. Job Lifecycle

### Starting a job (from CR worktree)
```bash
cd <cr-worktree>
chatrap job job-start <N> --name <slug>
# Creates: branch cr/<chat_id>__j<NN>, worktree …__j<NN>
# Note: worktree dir uses unpadded jN (e.g., __j3) even though branch is __j03
# Fix: git worktree move …__j3 …__j03
```

### Closing a job (from job worktree)
```bash
cd <job-worktree>
chatrap job done
# Merges to CR branch, tags job<NN>/<slug>, deletes branch + worktree
```

### Recovering from deleted-worktree shell state
When the shell `$PWD` is a deleted worktree, all commands fail:
```bash
# Shell reports: "current working directory was deleted"
# Fix: cd to any valid path first
cd /home/michael/dev/work/hashall/.agent/worktrees/<new-worktree>
```

---

## 10. Airo Launch Lifecycle

### Task transition pattern
```bash
# Each task is a new PR-native invocation after its handoff is posted.
command -v pr-agent >/dev/null || exit 127
pr-agent <client> worker slyckmb/hashall <PR> \
  --model <model> --cwd <worktree>
```

### Key findings
- Airo runs the selected native client in the foreground and preserves its
  truthful exit code; use `tee` only when retaining a local task log.
- Airo selects no hidden fallback model. The lead supplies the selected client
  and model for each invocation.
- `worker` is a PR-work role/provenance label. For OpenCode it does not select
  a native agent preset or change permissions.
- A launcher availability, client-version, or feature-gate failure is blocked;
  do not replace it with an interactive TUI, direct native client command, or
  an approval/sandbox bypass.

---

## 11. S05 Commit Trailers

Every commit from an agent must include:

```bash
GIT_AUTHOR_NAME="claude" GIT_AUTHOR_EMAIL="claude@chatrap.local" \
GIT_COMMITTER_NAME="claude" GIT_COMMITTER_EMAIL="claude@chatrap.local" \
git commit -m "<summary>" \
  -m "Agent-Client: claude" \
  -m "Agent-Model: claude-sonnet-4-6" \
  -m "Agent-Model-Slug: claude-sonnet-4-6" \
  -m "Job: J<NN>" \
  -m "Task: J<NN>-T<NN>"
```

Verify after every commit:
```bash
GIT_AUTHOR_NAME="claude" GIT_AUTHOR_EMAIL="claude@chatrap.local" chatrap ack commit HEAD
# Must return: s05_verdict="PASS"
```

---

## 12. Known Issues / Open Items

| Issue | Status | Fix |
|---|---|---|
| PR-native handoff and report | Required | Post the bounded handoff before launch; retain the task log as the local artifact |
| Airo foreground launch | Required | Use `pr-agent`; preserve its native output and exit status |
| Worktree dir unpadded vs branch padded | ⚠️ Active | `git worktree move …__jN …__j0N` after job-start |
| Agent writes raw terminal output | ⚠️ Active | Brief requires "full output" — agent sometimes substitutes summaries |
| TASK-LOG.md not written to disk by default | ✅ Fixed | Added explicit write+mirror instructions to brief After section |

---

## 13. Quick Reference

### Lead issues a task
1. Write `TASK-BRIEF.md` → mirror to GDrive → post its bounded contents as a reset-safe PR handoff → launch `pr-agent`

### Agent executes a task
1. Recover PR handoff → verify context → execute → write `TASK-LOG.md` → mirror → post PR report

### Lead evaluates a log
1. `Read TASK-LOG.md from disk` → assess format + content → accept or reject → write next brief

### PR-native worker launch
```bash
pr-agent <client> worker slyckmb/hashall <PR> \
  --model <model> --cwd <worktree>
```
