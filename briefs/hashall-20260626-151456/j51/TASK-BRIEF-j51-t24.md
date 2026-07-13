task-brief=j51-t24_apply-wrapper-pending-monitor
id=j51-t24
role=agent
task_type=implementation
goal=Make qb-stoppeddl-apply report moving qB rechecks as pending/needs-monitor instead of failed.
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j51
expected_branch=cr/hashall-20260626-151456__j51
allowed_mutation=repo-files-only
forbidden_commands=git push,git commit,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*
final_output_required=true

# j51-t24 - Apply Wrapper Pending Monitor

Implement OP-87.

Context:
- During the 2026-07-13 j51 hard-tail batch, Nintendo `09bceba1b43c` timed out inside `qb-stoppeddl-apply.py` while qB was still actively checking.
- The apply report marked it as failed, but a focused monitor later confirmed it completed as `stoppedUP progress=1.0 amount_left=0`.
- OP-84 fixed this class in the client-drift monitor; this task applies equivalent semantics to `qb-stoppeddl-apply.py`.

Requirements:
1. Find the post-apply qB check/monitor path in `qb-stoppeddl-apply.py`.
2. Treat moving progress or decreasing `amount_left` as active pending work, not immediate failure.
3. Add structured report fields for pending monitor outcomes, including enough data to continue monitoring.
4. Preserve hard failure for stable stoppedDL after grace, qB errors, missing torrent, or increasing risk state.
5. Add or update focused tests for moving stoppedDL/checkingDL, stable stoppedDL failure, and eventual stoppedUP success.
6. Update docs/runbook text if command behavior or reports change.

Do not run live qB mutation in this task.

Emit a task-log with changed files, tests run, and any follow-up OPs needed.
