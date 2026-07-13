task-brief=j51-t23_partial-fastresume-restore-tooling
id=j51-t23
role=agent
task_type=implementation
goal=Replace the one-off qB partial fastresume piece-map restore with guarded hash-scoped tooling.
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j51
expected_branch=cr/hashall-20260626-151456__j51
allowed_mutation=repo-files-only
forbidden_commands=git push,git commit,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*
final_output_required=true

# j51-t23 - Partial Fastresume Restore Tooling

Implement OP-86.

Context:
- During j51, four proven partial/no-seed qB rows drifted to 0% because qB `.fastresume` `pieces` were empty/all-zero while known-good backups still had 99.* piece maps.
- Manual recovery stopped qB, copied only backup `pieces`, corrected save-path shape for River/Transformers, cleared stale `qBt-downloadPath`, restarted qB, and verified qB mirrored RT at 99.* stoppedDL.

Requirements:
1. Add a guarded hash-scoped command or script for restoring partial qB fastresume piece maps from known-good backups.
2. Default to dry-run.
3. Require explicit hash input and explicit live flag for mutation.
4. Restore only the `pieces` field unless a validated path-shape correction is explicitly requested.
5. Validate current `.fastresume` and backup state before mutation.
6. Write a rollback ledger/report before live mutation.
7. Include post-restart verification guidance or a callable verifier path.
8. Add focused tests for dry-run, blocked unsafe input, backup missing, all-zero current pieces, nonzero backup pieces, and path-shape validation.
9. Update the relevant docs/runbook references.

Do not touch live qB state in this task.

Emit a task-log with changed files, tests run, and any follow-up OPs needed.
