task-brief=j58-t01_explicit-hash-mutation-scope
id=j58-t01
role=agent
task_type=implementation
goal=Prevent delegated hashall mutation tasks from acting on visible but out-of-scope torrents.
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j58
expected_branch=cr/hashall-20260626-151456__j58
allowed_mutation=repo-files-only
forbidden_commands=git push,git commit,rm -rf,docker,*--apply-live*,*--delete-live*,*--rsync-live*,*d.start*,*d.check_hash*
final_output_required=true

# j58-t01 - Explicit Hash Mutation Scope

Implement OP-45.

Context:
- A prior delegated agent ran `d.check_hash` on Diary of Teenage Girl even though it was not a target hash.
- The safety rule is simple: live torrent-state mutation briefs must name exact allowed hashes and, where useful, excluded hashes. Agents must not scan visible stopped torrents and mutate anything opportunistically.

Requirements:
1. Audit hashall task-brief templates, runbooks, and mutation guidance for live RT/qB actions.
2. Add reusable language requiring explicit allowed hash lists for any torrent-state mutation.
3. Add reusable language forbidding mutation of visible-but-out-of-scope torrents.
4. If there is a brief generator or checker, add a lightweight validation that mutation briefs include explicit hash scope.
5. Add focused tests if code changes are made.
6. Update JOB-QUEUE/OPS only if new follow-up work is discovered.

Do not run live RT/qB commands.

Emit a task-log with changed files, tests run, and any follow-up OPs needed.
