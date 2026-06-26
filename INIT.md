# INIT — CR Lead Bootstrap Protocol

Session: `hashall-20260530-000517-claude`
Branch: `cr/hashall-20260530-000517-claude`
Worktree: `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude`
Updated: 2026-06-26

---

## YOU ARE THE CR LEAD

Execute all actions via Bash tool. Dispatch agents via `opencode run`. **Never narrate commands to the user — run them.** Never ask the user what to do next — check JOB-QUEUE.md. Never write agent code inline. Never commit without S05 check.

---

## STEP 1 — Orient (run this first, no exceptions)

```bash
# Kickstart CWD guard — detect orphaned job worktree
_cwd="$(pwd)"
if [[ "$_cwd" =~ __j[0-9]+ ]]; then
  _wt_registered=$(git worktree list 2>/dev/null | awk '{print $1}' | grep -Fxq "$_cwd" && echo yes || echo no)
  if [[ "$_wt_registered" == "no" ]]; then
    echo "⚠ WARNING: CWD is an orphaned job worktree: $_cwd"
    echo "  This directory is not a registered git worktree."
    echo "  Switch to CR worktree before continuing:"
    echo "  cd /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude"
  fi
fi

/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude/bin/chatrap lead status
```

Then confirm git state:

```bash
git -C /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude log --oneline -5
git -C /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude status --short
```

Expected: clean tree, branch `cr/hashall-20260530-000517-claude`. Verify HEAD matches `chatrap lead status` output above.

---

## STEP 2 — Mastery gate (must pass before any dispatch)

```bash
/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude/bin/chatrap ack lead \
  --repo-root /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude
```

If it fails: read `REPO-MASTERY.md`, retry. Do not proceed until it passes.

---

## STEP 3 — Next job (execute immediately after gate passes)

**Next job: j37 — code-bug-fix**
OPs: OP-04,OP-05,OP-06,OP-16
Goal: Audit 4 open code bugs; close those already fixed; fix any still open.

Tasks:
- **j37-t01** (discovery): Verify OP-05/06/16 status in current code; close confirmed-fixed OPs; document OP-04 fix scope
- **j37-t02** (implementation): Fix OP-04 SYSTEM_TAGS registry integration (scoped after t01)

**Session state as of 2026-06-26:**
- Merged: j28–j36 (j36 closed OP-29,32,46,48)
- RT stopped: 0 (all 80 resolved)
- RT seeding at 99.9x% (OP-43): River Monsters 127C3834, Transformers 96D896CA, Dexter S02 245F2BCE, Dexter S07 E36553B1 — check complete=1 by 2026-06-27
- Version: 0.8.67
- Open OPs: 28 (all slotted j37–j45 per JOB-QUEUE.md)

Set path variables (use these everywhere below):

```bash
CR_WORKTREE=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude
JOB=j37
JOB_WORKTREE=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__${JOB}
```

Create the worktree (use absolute path to avoid nesting — j22 lesson):

```bash
git -C ${CR_WORKTREE} \
  worktree add ${JOB_WORKTREE} \
  -b cr/hashall-20260530-000517-claude__${JOB} cr/hashall-20260530-000517-claude
```

Copy briefs into job worktree (OP-152 — `comms/` is gitignored, briefs are disk-only):

```bash
mkdir -p ${JOB_WORKTREE}/comms/briefs
cp ${CR_WORKTREE}/comms/briefs/TASK-BRIEF-${JOB}-*.md ${JOB_WORKTREE}/comms/briefs/
```

Then dispatch t01 immediately:

```bash
BRIEF="${JOB_WORKTREE}/comms/briefs/TASK-BRIEF-${JOB}-t01.md"
LOG="${CR_WORKTREE}/.agent/logs/hashall-20260530-000517-claude/${JOB}/${JOB}-t01-opencode.log"
mkdir -p "$(dirname "$LOG")"
(cd ${JOB_WORKTREE} && OPENCODE_MODEL=opencode-go/deepseek-v4-flash \
  opencode run "Read and execute $BRIEF. Follow it literally. Emit the required task-log." \
  2>&1 | tee "$LOG")
```

---

> **DISPATCH CONTRACT — NON-NEGOTIABLE**
> NEVER execute task steps directly using file-edit or shell tools.
> ALL task work MUST go through `opencode run <brief>`.
> Inline execution bypasses task logs, signal files, and friction tracking.

## AGENT DISPATCH PATTERN

For every task after t01:

```bash
BRIEF="${JOB_WORKTREE}/comms/briefs/TASK-BRIEF-${JOB}-tNN.md"
LOG="${CR_WORKTREE}/.agent/logs/hashall-20260530-000517-claude/${JOB}/${JOB}-tNN-opencode.log"
mkdir -p "$(dirname "$LOG")"
(cd ${JOB_WORKTREE} && OPENCODE_MODEL=<model> \
  opencode run "Read and execute $BRIEF. Follow it literally. Emit the required task-log." \
  2>&1 | tee "$LOG")
```

Tail progress: `tail -n 80 -F "$LOG"`

After agent completes — lead reviews output, then commits:

```bash
GIT_AUTHOR_NAME="agent: opencode (${OPENCODE_MODEL##*/})" GIT_AUTHOR_EMAIL=agent@chatrap.local \
  git -C ${JOB_WORKTREE} \
  commit -m "feat(${JOB}-tNN): <summary>

Job: ${JOB}
Task: tNN
Agent-Client: <agent>
Agent-Model: <model>
Agent-Model-Slug: <slug>"
```

S05 check after every commit (run from INSIDE the job worktree):

```bash
cd ${JOB_WORKTREE} && chatrap ack commit HEAD
```

---

## MODEL SELECTION

| Tier | Model | Use when |
|------|-------|----------|
| nano | `opencode-go/minimax-m3` | trivial edits, single-file docs |
| standard | `opencode-go/deepseek-v4-flash` | routine coding (default) |
| large | `opencode-go/deepseek-v4-pro` | multi-file refactors |
| reasoning | `opencode-go/qwen3.7-plus` | architecture, complex triage |
| fallback | `anthropic/claude-sonnet-4-6` | quota exhausted |

---

## INVARIANTS

- Binary: use `./bin/chatrap` from the job worktree, not installed `chatrap`
- Agents cannot commit (OP-131) — lead always commits after reviewing
- `comms/` is gitignored — briefs are on disk, not committed
- Never commit to `main` or to the CR branch from a job worktree
- After merging prompt changes: run `./bin/chatrap regen-shared`

---

## ANTI-PATTERNS (do not do these)

- Narrating a command instead of running it via Bash tool
- Asking the user "what should I do next?" — check JOB-QUEUE.md
- Writing implementation code inline instead of dispatching to an agent
- Reporting a commit done before S05 passes
- Running `chatrap` (installed) instead of `./bin/chatrap` (worktree) for validation
- Running `chatrap lead closeout --audit-done` without reading the friction output
  first — `--audit-done` should only be passed after genuinely reviewing friction entries
  and deciding whether to write new OPs
- Running more than one job per session without /clear — lead scope is one job;
  signal READY FOR /clear after closeout and wait for user to clear
- Proceeding when kickstart warns about orphaned CWD — run the cd command shown
  and re-execute Step 1 from the correct worktree
- Executing task steps inline (via Edit/Write/Bash) instead of `opencode run <brief>` — inline execution is always invalid in chatrap sessions
- Asking the user open-ended questions before checking INIT.md/lead-onboarding.md/CLI-LEAD-SOP.md for the answer
- Presenting unbounded "what do you want?" choices instead of bounded A/B/C options with a recommended COA
- Asking "Consent to proceed?" after already identifying a recommended COA — just execute it
