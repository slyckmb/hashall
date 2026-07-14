task-brief=j59-t03_gitignore-and-tracked-control-cleanup
id=j59-t03
role=agent
task_type=implementation
goal=Apply latest chatrap gitignore and tracked-control-file hygiene safely.
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j59
expected_branch=cr/hashall-20260626-151456__j59
allowed_mutation=repo-files-only
forbidden_commands=git push,git commit,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*
final_output_required=true

# j59-t03 - Gitignore And Tracked Control Cleanup

Implement the file-hygiene portion of OP-89.

Known current findings:
- `chatrap lead sync-gitignore --dry-run` wants to add patterns for `.chatrap/logs/`, `.chatrap/signals/`, `.chatrap/artifacts/`, `.chatrap/task-logs/`, `state/jobs.json`, `CODEQ.md`, `.chatrap/state/session-rehydrate.json`, and `.chatrap/state/mastery-proof.json`.
- Latest guidance says `.chatrap/` runtime files must never be committed.
- Latest guidance says `OPS.md` and `JOB-QUEUE.md` are generated views, not authoritative state.
- Hashall currently tracks `OPS.md`, `JOB-QUEUE.md`, `state/jobs.json`, and `state/ops.json`.

Requirements:
1. Apply the current chatrap gitignore sync or equivalent focused patch.
2. Determine which tracked generated/control files must be untracked under latest chatrap standard.
3. If untracking is safe, use non-destructive `git rm --cached` only for generated/control files that should remain on disk.
4. If untracking is not safe because current hashall/chatrap tooling still depends on committed files, document the blocker and create/update a follow-up OP.
5. Confirm no `.chatrap/` path is staged.
6. Confirm generated views can still be rebuilt or read after the change.

Do not delete working copies of OP/queue data.
Do not mutate live RT/qB state.

Emit a task-log with exact file-hygiene decisions, commands run, files changed, and validation.
