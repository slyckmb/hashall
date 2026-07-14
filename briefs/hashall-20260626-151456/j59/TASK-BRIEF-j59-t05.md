task-brief=j59-t05_validation-and-clear-readiness
id=j59-t05
role=agent
task_type=validation
goal=Validate that hashall passes latest chatrap lead/status/prep/wrap/clear expectations after the upgrade.
repo=hashall
worktree=/home/michael/dev/work/hashall/.chatrap/worktrees/hashall-20260626-151456__j59
expected_branch=cr/hashall-20260626-151456__j59
allowed_mutation=reports-only
allowed_commands=cat,grep,rg,sed,awk,jq,python3,git status,git diff,git log,find,chatrap
forbidden_commands=git push,git commit,git add,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*
final_output_required=true

# j59-t05 - Validation And Clear Readiness

Validate OP-89 after j59-t01 through j59-t04.

Run and capture:
1. `git status --short`
2. `chatrap lead status`
3. `chatrap state sync-check`
4. Any current state validation commands that work with the new `.chatrap/state` schema
5. `chatrap prep j59 --non-interactive` if still relevant, or prep for the next post-j59 job if j59 is complete
6. `chatrap session prepare-clear`
7. `git diff --check`
8. Checks proving no `.chatrap/` path is staged or tracked

Expected outcome:
- Lead status has a dispatchable next job.
- `.chatrap/state/queue.json` is not empty for this session.
- Prepare-clear does not report `next=unknown`.
- `.gitignore` contains latest chatrap runtime patterns.
- No live RT/qB state changed.

Write `comms/reports/J59-T05-VALIDATION.md`.

Emit a task-log with pass/fail table and exact blockers.
