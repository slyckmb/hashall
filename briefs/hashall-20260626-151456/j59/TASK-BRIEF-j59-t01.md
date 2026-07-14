task-brief=j59-t01_latest-chatrap-standard-audit
id=j59-t01
role=agent
task_type=audit
goal=Produce a precise gap report comparing latest chatrap guidance against current hashall repo state.
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j59
expected_branch=cr/hashall-20260626-151456__j59
allowed_mutation=reports-only
allowed_commands=cat,grep,rg,sed,awk,jq,python3,git status,git diff,git log,find,chatrap
forbidden_commands=git push,git commit,git add,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*
final_output_required=true

# j59-t01 - Latest Chatrap Standard Audit

Implement the audit portion of OP-89.

Read latest chatrap guidance and infra from the local chatrap checkout, especially:
- `docs/INFRA-RULES.md`
- `prompts/system/lead-onboarding.md`
- `prompts/system/session-lifecycle.md`
- `docs/WORKFLOW-REDESIGN.md`
- `bin/chatrap-state.sh`
- `bin/chatrap-lead.sh`

Compare that guidance to hashall current state:
- `.gitignore`
- `OPS.md`
- `JOB-QUEUE.md`
- `state/jobs.json`
- `state/ops.json`
- `.chatrap/state/*.json`
- `QUICKSTART.md`
- `REPO-MASTERY.md`
- task briefs and runbook references to `.agent`, `opencode run`, `.agent/logs`, or inline source edits
- `chatrap lead status`
- `chatrap session prepare-clear`

Write a report at `comms/reports/J59-T01-CHATRAP-STANDARD-AUDIT.md` with:
1. Current latest rules, in plain language.
2. Every hashall divergence found.
3. Which divergences are safe to fix mechanically.
4. Which divergences need migration sequencing.
5. Which divergences may be blocked by current chatrap tooling.
6. Recommended task-by-task implementation order.

Do not mutate repo source or live services.

Emit a task-log with report path, commands run, and follow-up OP suggestions.
