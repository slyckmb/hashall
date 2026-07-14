task-brief=j59-t04_lead-dispatch-workflow-update
id=j59-t04
role=agent
task_type=implementation
goal=Update hashall lead/brief guidance so source mutations go through chatrap dispatch instead of inline edits.
repo=hashall
worktree=/home/michael/dev/work/hashall/.chatrap/worktrees/hashall-20260626-151456__j59
expected_branch=cr/hashall-20260626-151456__j59
allowed_mutation=repo-files-only
forbidden_commands=git push,git commit,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*
final_output_required=true

# j59-t04 - Lead Dispatch Workflow Update

Implement the lead-dispatch portion of OP-89.

Problem:
- Recent lead work in this session included inline tracking/source-adjacent edits and direct-CR commits.
- Latest chatrap guidance says lead source mutations must be dispatched through `chatrap dispatch` / Pi / direct dispatch, not performed inline.
- Latest guidance replaces stale `opencode run` patterns with `chatrap dispatch`, uses `.chatrap/logs` and `.chatrap/task-logs`, and uses direct dispatch for tiny fixes.

Requirements:
1. Audit hashall guidance, runbooks, task briefs, and generated prompts for stale lead workflow instructions:
   - `opencode run`
   - `.agent/logs`
   - `.agent/artifacts`
   - inline source edit permission for lead
   - old task-log paths
2. Update repo-local guidance so future hashall lead work says:
   - source mutations require a task brief and `chatrap dispatch`
   - 1-3 line fixes use direct dispatch, not inline edits
   - Pi/direct logs go to current `.chatrap` locations
   - task logs are expected under `.chatrap/task-logs/<chat_id>/<job>/<task>/`
3. Preserve hashall-specific live RT/qB safety gates.
4. Add or update a brief template/check if one exists.
5. Add focused tests only if code changes are made.

Do not run live RT/qB mutation.

Emit a task-log with changed files, tests/checks run, and any remaining stale references.

Repair note after first dispatch:
- Do not probe `/home/michael/dev/work/hashall` or expect `./bin/chatrap`; this job worktree has the chatrap CLI on PATH.
- Required local edit targets are `INIT.md`, `QUICKSTART.md`, `REPO-MASTERY.md`, and `prompts/system/lead-onboarding.md` if stale references remain there.
- Preserve `.gitignore` legacy `.agent/*` ignore entries; those are harmless backward-compatible ignores, not workflow guidance.
- Write the required task log at `.chatrap/task-logs/hashall-20260626-151456/j59/j59-t04/TASK-LOG.md`.
