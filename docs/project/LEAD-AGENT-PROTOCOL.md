# Lead–Agent Injection Protocol

**Version:** 0.3.0  
**Status:** Active — evolving through session hashall-20260530-000517-claude  
**Last updated:** 2026-06-12  
**Scope:** Defines the full contract between the Web Lead and CLI Agent for task
dispatch, reporting, tmux injection, and job lifecycle management.

---

## 1. Role Model

| Role | Who | Responsibilities |
|---|---|---|
| **User** | Operator | Sets goals, approves direction, owns final acceptance |
| **Lead** | Web UI agent (this doc's author) | Writes briefs, reads logs, drives decisions, issues one task at a time |
| **Agent** | CLI agent (OpenCode / Claude Code) | Executes briefs, writes logs, notifies Lead, never broadens scope |

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
  TASK-BRIEF.md     ← Lead writes before dispatch
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
<write TASK-LOG.md and mirror instructions>
<tmux notify instructions>
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

# 3. Notify Lead tmux pane (two-send pattern)
tmux send-keys -t %14 "🟪 <JNN-TNN> done | <key=val> <key=val> <key=val>"
tmux send-keys -t %14 "" Enter
```

**Note on tmux Enter:** Use `tmux send-keys -t <pane> "" Enter` or a second `send-keys` with `Enter` as the key argument. Do NOT rely on `""` alone to trigger Enter.

---

## 8. Lead Dispatch Sequence

Steps in order for each task:

```bash
# 1. Write TASK-BRIEF.md
# (Lead writes file)

# 2. Mirror to GDrive
cp <worktree>/jobs/.../TASK-BRIEF.md /mnt/gdrive/.../TASK-BRIEF.md

# 3. Inject into agent pane
#    If ok to clear (prior task complete, agent idle):
tmux send-keys -t %117 "/clear" Enter
sleep 5
tmux send-keys -t %117 "Read and execute the task brief at: <absolute path to TASK-BRIEF.md>" Enter

#    If NOT ok to clear (agent may have pending context):
tmux send-keys -t %117 "Read and execute the task brief at: <absolute path to TASK-BRIEF.md>" Enter
```

**When is it ok to clear?**
- Prior task TASK-LOG.md written to disk and evaluated by Lead
- Agent pane shows idle state (no `esc interrupt` indicator)
- No carry-over context needed from prior task

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

## 10. Agent Pane Lifecycle (OpenCode)

### Job transition pattern (reuse same pane)
```bash
# 1. Exit current OpenCode session
tmux send-keys -t %117 "q" Enter      # 'q' exits OpenCode TUI to shell
sleep 2

# 2. cd out of deleted worktree (if prior job worktree was removed)
tmux send-keys -t %117 "cd <new-worktree-path>" Enter
sleep 1

# 3. Launch OpenCode in new worktree
tmux send-keys -t %117 "opencode ." Enter
sleep 6                                 # wait for TUI to fully load

# 4. Optionally clear prior session context
tmux send-keys -t %117 "/clear" Enter
sleep 5

# 5. Send brief pointer
tmux send-keys -t %117 "Read and execute the task brief at: <path>" Enter
```

### Key findings
- `q` exits OpenCode TUI → shell (not `/exit`, not `/quit`)
- `opencode <path>` sets project root explicitly — preferred over `cd` + `opencode .` when pane $PWD is unknown/deleted
- `/clear` clears conversation history but requires **12–15s** to settle before next input — 5s and 10s are insufficient for this OpenCode instance; if prompt is swallowed, resend without re-clearing (do not send /clear again)
- `tmux send-keys -t <pane> "text" Enter` submits (single call with `Enter` key name)
- `tmux send-keys -t <pane> "text"` types but does NOT submit
- Two-send notify pattern: `send-keys "message"` then `send-keys "" Enter`

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
| Two-send tmux pattern for notify | ✅ Confirmed working | `send-keys "msg"` then `send-keys "" Enter` |
| `/clear` timing | ✅ Fixed | Sleep 5s after `/clear` before next input |
| OpenCode exit command | ✅ Confirmed | `q` (not `/exit`) |
| Worktree dir unpadded vs branch padded | ⚠️ Active | `git worktree move …__jN …__j0N` after job-start |
| Agent writes raw terminal output | ⚠️ Active | Brief requires "full output" — agent sometimes substitutes summaries |
| TASK-LOG.md not written to disk by default | ✅ Fixed | Added explicit write+mirror instructions to brief After section |
| Lead pane notification requires Enter | ✅ Fixed | Two-send pattern; `send-keys "" Enter` not `""` alone |

---

## 13. Quick Reference

### Lead issues a task
1. Write `TASK-BRIEF.md` → mirror to GDrive → inject pointer into agent pane

### Agent executes a task
1. Read brief → verify context → execute → write `TASK-LOG.md` → mirror → notify `%14`

### Lead evaluates a log
1. `Read TASK-LOG.md from disk` → assess format + content → accept or reject → write next brief

### Pane injection (ok to clear)
```bash
tmux send-keys -t %117 "q" Enter && sleep 2 && \
tmux send-keys -t %117 "cd <worktree> && opencode ." Enter && sleep 6 && \
tmux send-keys -t %117 "/clear" Enter && sleep 15 && \
tmux send-keys -t %117 "Read and execute the task brief at: <path>" Enter
```

### Pane injection (not ok to clear)
```bash
tmux send-keys -t %117 "Read and execute the task brief at: <path>" Enter
```

### Agent notify Lead
```bash
tmux send-keys -t %14 "🟪 J<NN>-T<NN> done | key=val key=val"
tmux send-keys -t %14 "" Enter
```
