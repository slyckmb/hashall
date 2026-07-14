task-brief=j59-t02_state-authority-migration
id=j59-t02
role=agent
task_type=implementation
goal=Migrate hashall chatrap authority from tracked markdown/legacy state into current .chatrap/state runtime files.
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j59
expected_branch=cr/hashall-20260626-151456__j59
allowed_mutation=repo-files-only
forbidden_commands=git push,git commit,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*
final_output_required=true

# j59-t02 - State Authority Migration

Implement the state migration portion of OP-89.

Inputs:
- `OPS.md`
- `JOB-QUEUE.md`
- `state/ops.json`
- `state/jobs.json`
- `.chatrap/state/queue.json`
- `.chatrap/state/session.json`
- j59-t01 audit report

Requirements:
1. Build or use current chatrap commands to populate `.chatrap/state/ops.json`, `.chatrap/state/queue.json`, and `.chatrap/state/jobs.json` with the current hashall OPs, jobs, holds, and run order.
2. Preserve j59 as the next job and OP-89 as its OP.
3. Preserve `hold-chatrap` for OP-42/71/72/77/88.
4. Preserve existing j51/j58/j52/j55/j42/j39/j43/j56/j45 ordering after j59.
5. Do not commit `.chatrap/` runtime files.
6. If current chatrap tooling cannot represent something from the legacy state, document the exact gap and open/update a follow-up OP rather than silently dropping data.
7. Render `OPS.md`/`JOB-QUEUE.md` from state only if the current tooling supports it safely. Do not hand-edit rendered views as authoritative input.

Validation:
- `chatrap state sync-check`
- `chatrap lead status`
- JSON schema/parse checks for any generated state files
- Confirm `git status` does not include `.chatrap/`

Do not mutate live RT/qB state.

Emit a task-log with files changed, state files generated, validation output, and remaining blockers.
