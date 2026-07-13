task-brief=j58-t02_qb-credential-argv-hardening
id=j58-t02
role=agent
task_type=implementation
goal=Prevent qB credentials from appearing in process argv, shell logs, reports, or tool output.
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j58
expected_branch=cr/hashall-20260626-151456__j58
allowed_mutation=repo-files-only
forbidden_commands=git push,git commit,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*
final_output_required=true

# j58-t02 - qB Credential Argv Hardening

Implement OP-73.

Context:
- During a DB refresh, a qB password was visible in a Python process command line because wrappers passed `--qbit-user/--qbit-pass`.
- Future qB client tools should load credentials from env/config/session mechanisms and redact any command/report output.

Requirements:
1. Audit qB credential call paths, especially `payload sync` wrappers and scripts.
2. Replace CLI password passing with env/config/cookie/session loading where feasible.
3. Redact credential values from logs, printed command lines, reports, and exceptions.
4. Preserve backward compatibility only if necessary, but warn/deprecate unsafe CLI password arguments.
5. Add a smoke test or focused unit test proving command construction/log output does not include qB secrets.
6. Update docs/runbooks for the safe credential path.

Do not run live qB mutation in this task.

Emit a task-log with changed files, tests run, and any follow-up OPs needed.
