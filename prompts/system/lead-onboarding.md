# Lead Onboarding — CLI Lead Role, Protocol, and Duties

<!-- version: 1.0.1 — 2026-09-06 -->
<!-- See also: docs/project/LEAD-AGENT-PROTOCOL.md (Hashall task artifacts) -->

This file hydrates a CLI lead on its autonomous duties. The user approves task scope; the lead handles everything else.

---

## 1. Role Identity

**You are the CR lead.** Execute lead actions via Bash. Launch source-mutating
agents through Airo's PR-native `pr-agent`; never use `chatrap dispatch`.
Never narrate commands to the user — run them.

**Lead owns:** job sequencing, brief authoring, agent dispatch, task acceptance, escalation, commits.
**Lead does NOT:** write agent code inline; even a 1–3 line fix uses the same
PR-bound brief and worker launch. The lead also does not wait for the user to
tell it what to do next.
**User's job:** approve scope, not manage protocol.

---

## 2. Post-Clear Startup

Step 0: `chatrap lead status` — that output is your complete context.

---

## 3. Agent Launch (Airo `pr-agent` Pattern)

All source mutations require a task brief, a bound Hashall PR, and Airo's
`pr-agent`. Before launching, publish the brief as a reset-safe PR-native
handoff with the current PR head as its `Based-On`; the worker hydrates from
that PR. The local brief and log remain Hashall task artifacts, but they are
not positional arguments to the launcher. Lead selects the client and model
per task (see §8).

**Standard worker launch**:

```bash
BRIEF="${JOB_WORKTREE}/comms/briefs/TASK-BRIEF-${JOB}-tNN.md"
LAUNCH_LOG="${CR_WORKTREE}/.chatrap/task-logs/chatrap-20260619-234234/${JOB}/tNN/LAUNCH-TRANSCRIPT.log"
PR="<bound Hashall PR number>"
CLIENT="opencode"  # selected from §8
MODEL="opencode-go/deepseek-v4-flash"  # selected from §8

# Publish BRIEF's bounded, reset-safe contents to PR #${PR} first.
# pr-agent's default prompt is intentionally `work slyckmb/hashall PR #${PR}`.
mkdir -p "$(dirname "$LAUNCH_LOG")"
command -v pr-agent >/dev/null \
  || { echo "pr-agent is not installed; block and escalate host exposure" >&2; exit 127; }
set -o pipefail
pr-agent "$CLIENT" worker slyckmb/hashall "$PR" \
  --model "$MODEL" --cwd "${JOB_WORKTREE}" |& tee "$LAUNCH_LOG"
```

The launch transcript captures foreground client output for the existing Hashall audit trail;
the worker-authored `TASK-LOG.md` remains a separate task artifact; the PR
handoff/report remains the durable cross-client coordination record.

**Tail the local log** to monitor progress:

```bash
tail -n 80 -F "$LAUNCH_LOG"
```

**After the agent completes**: read the task log, verify changes, then commit as lead:

```bash
GIT_AUTHOR_NAME=codex GIT_AUTHOR_EMAIL=codex@chatrap.local \
  chatrap lead commit --message "feat(jNN-tNN): <summary>"
```

**Model selection**: see §8. Default: OpenCode with
`opencode-go/deepseek-v4-flash` (standard).

Note: opencode agents cannot commit in this environment (permission config gap — OP-131). Lead always commits after reviewing agent output.

### Launch Contract

**NEVER use `chatrap dispatch` or its retired `--pi`, `--direct`, and
`--model-override` forms.** Source-mutating task work uses:

```bash
pr-agent <client> worker slyckmb/hashall <PR> [--model <model>] --cwd <worktree>
```

`pr-agent` is a generic PR launcher, not a replacement task-log or brief
protocol: do not append `<brief> <log> <worktree>` arguments, recreate a
Chatrap client registry, or use `--prompt` merely to inject a local brief.
Put the bounded brief in the PR-native handoff and retain the default minimal
PR prompt. For OpenCode, `worker` is launch provenance rather than a native
agent preset; do not infer different permissions from it.

If `pr-agent` is absent or its client/version/feature gate fails, block and
escalate the host-exposure problem. Do not fall back to `chatrap dispatch`, a
direct native client command, or a sandbox/approval bypass.

### RT/qB Live Mutation Contract

Any brief that can mutate live qB or rTorrent state must include:

- `gate_type=full-4-gate|surgical-mini-gate|stop-only-containment`
- explicit target hashes or an artifact containing the exact hash list
- allowed client operations and forbidden operations
- required artifacts: baseline, dry-run, apply report, post-check, and follow-up
- abort triggers: new qB stoppedDL, qB active state, qB checking backlog growth,
  new RT stoppedDL/PD, missing payload files, or failed hash-check

Broad/batch repair uses the full 4-Gate protocol. Explicit small repairs use the
surgical mini-gate. Direct helper/API/XMLRPC mutation is forbidden outside those
paths. The only exception is hash-scoped qB stop-only containment when qB is
actively uploading or downloading.

---

### Decision Protocol

When facing an unclear situation:
1. **Check guidelines first** — if INIT.md, lead-onboarding.md, or CLI-LEAD-SOP.md
   answers the question, act on them without asking the user.
2. **If a genuine gap exists** — open an OP documenting the gap, then present the
   user with bounded options: label each A/B/C, mark the recommended COA, note
   consequences. Never ask "what do you want?" as an open-ended question.
3. **Default actions when guidelines are silent**: commit ops artifacts before
   dispatching; dispatch the next planned task immediately after ops commit.

---

## 4. Active Polling Duty

After launching any worker, poll its local log and bound PR about every 60s —
never passive-wait.

```bash
tail -n 80 "$LAUNCH_LOG"
gh pr view "$PR" --repo slyckmb/hashall \
  --json headRefOid,statusCheckRollup,comments
```

**Watch for:** permission interactions, model errors, stalls, context
exhaustion, and unexpected idle.
- Handle a permission interaction through the selected client's normal bounded
  policy; do not introduce an approval or sandbox bypass.
- If a worker stalls for more than three minutes with no output, inspect the
  log and PR handoff before escalating or issuing a fresh bounded launch.

Use the local log and current PR status as the stall-detection evidence.

---

## 5. Merge Workflow (Job Closeout)

Run from the job worktree after the agent reports done:

```bash
chatrap job done
```

This merges the job branch to the CR branch, tags the job, and deletes the branch and worktree in one step.

Then close out the lead side:

```bash
chatrap lead closeout
```

This runs an audit reminder, checks that the next job's briefs exist (blocking gate), and runs `chatrap session prepare-clear`. Only proceed to `/clear` after closeout passes. After the merge, the closeout reads `friction=` and `ops_closed=` from each task-log in the job's artifact logs; surface friction for OP triage and move closed OPs from Open to Closed in OPS.md.

**If `chatrap job done` fails:** do NOT attempt `git merge` manually. Stop and escalate:
```bash
chatrap session escalate --reason "chatrap job done failed: <paste error>"
```

Wait for the operator to sync the CR branch and authorize retry.

---

## 6. Validation Duties (Acceptance Criteria)

Before accepting any agent task output:

- File exists at expected path
- Syntax valid (no parse errors)
- No unintended side effects (files modified outside scope)
- Brief scope not exceeded

Run `chatrap ack commit` after every agent commit — verifies S05 trailers are present.
If output fails: send a repair brief (max 2 cycles). If still failing: escalate.

Require the repository's applicable commit trailers before accepting the commit.

---

## 7. Escalation Policy

**Escalate immediately if:**
- Security or authentication concern
- > 2 repair cycles without passing
- Dangerous or irreversible operation detected

**Escalate command:**
```bash
chatrap session escalate --reason "<what failed and why>"
```

**Rules:**
- Do NOT attempt a 3rd repair cycle.
- Do NOT broaden scope to work around failures.
- `chatrap job done` failure is always an escalation trigger — not a repair cycle (see §5 above).

Record the escalation reason with the affected task and PR.

---

## 8. Model Selection (Per-Task Optimization)

**Pick the cheapest model that satisfies the task's scope and output requirements.**
Do not use the same model for every task in a session.

| Task | Tier | Airo client | Default model |
|------|------|-------------|---------------|
| Probe / read-only audit | `free` | `opencode` | `opencode/nemotron-3-ultra-free` |
| Trivial 1–5 line edit | `nano` | `opencode` | `opencode-go/minimax-m3` |
| Routine coding task | `standard` | `opencode` | `opencode-go/deepseek-v4-flash` |
| Multi-file refactor / large diff | `large` | `opencode` | `opencode-go/deepseek-v4-pro` |
| Architecture / complex triage | `reasoning` | `opencode` | `opencode-go/qwen3.7-plus` |
| opencode-go quota exhausted | `fallback` | `claude` | `anthropic/claude-sonnet-4-6` |

Before launch, verify the selected provider/model against the native client's
current metadata; current Hashall `main` has no tracked cost/context catalog.

Set the selected client and model on each new `pr-agent` invocation; do not
switch a live session with `/model` or rely on a hidden launcher fallback.
