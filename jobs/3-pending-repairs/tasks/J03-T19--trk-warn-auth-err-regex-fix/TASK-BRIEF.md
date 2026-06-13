---
id: J03-T19
job: 3-pending-repairs
slug: trk-warn-auth-err-regex-fix
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-13
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T19 — trk-warn: fix auth_err regex to match "InfoHash not found"

## Problem (from T18 gap assessment)

`rt-tracker-manual-report.py` BUCKET_PATTERNS line 64 has:

```python
("auth_err", re.compile(
    r"Invalid InfoHash|passkey|Torrent not found|not authorized|unauthorized|forbidden",
    re.I,
)),
```

The 4 OnlyEncodes items have tracker message: `"InfoHash not found"`.
This does NOT match `Invalid InfoHash` (requires the word "Invalid").
Result: 4 auth_err items are silently dropped — never shown by `make trk-warn`.

`rt-cache-summary.py` (rt-status source) uses `infohash` (plain, no "Invalid") so it catches them.
The fix aligns trk-warn with rt-cache-summary by broadening the match to plain `InfoHash`.

## Fix

In `rt-tracker-manual-report.py`, change line 64-67 from:

```python
("auth_err", re.compile(
    r"Invalid InfoHash|passkey|Torrent not found|not authorized|unauthorized|forbidden",
    re.I,
)),
```

to:

```python
("auth_err", re.compile(
    r"InfoHash|passkey|Torrent not found|not authorized|unauthorized|forbidden",
    re.I,
)),
```

`InfoHash` (without `Invalid`) matches both:
- `"Invalid InfoHash"` (existing messages)
- `"InfoHash not found"` (OnlyEncodes messages)

Also bump version `v1.9.1 → v1.9.2` in the module docstring (line 3).

## Target file

```
~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
```

## Verification

```bash
# Syntax check
python3 -m py_compile ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py && echo ok

# Smoke test — should now show 6 items (4 auth_err + 1 deleted + 1 other if present, or at least the 4 OnlyEncodes)
python3 ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py 2>&1

# Confirm auth_err count >= 4
python3 ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py 2>&1 | grep "^\[auth_err\]"
```

Expected: `[auth_err] 4` (or more if Nebulance S51E11 still active → 5)

## Commit

Branch: `cr/hashall-20260530-000517-claude--trk-warn-footer` (same docker branch as T17 — continue on it)

```bash
cd ~/dev/sys/docker
git checkout cr/hashall-20260530-000517-claude--trk-warn-footer
git add gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
GIT_AUTHOR_NAME="claude-code" GIT_AUTHOR_EMAIL="claude-code@chatrap.local" \
GIT_COMMITTER_NAME="claude-code" GIT_COMMITTER_EMAIL="claude-code@chatrap.local" \
git commit -m "fix(trk-warn): v1.9.2 — broaden auth_err regex to catch 'InfoHash not found'" \
  -m "Agent-Client: claude-code" \
  -m "Agent-Model: claude-sonnet-4-6" \
  -m "Agent-Model-Slug: claude-code-claude-sonnet-4-6" \
  -m "Job: j03" \
  -m "Task: J03-T19"
```

## Bootstrap context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
```

## Brief

```
🟦 task-brief=J03-T19_trk-warn-auth-err-regex-fix 🟦

id=J03-T19
role=agent
task_type=implementation
goal=Fix BUCKET_PATTERNS auth_err regex in rt-tracker-manual-report.py: change
     "Invalid InfoHash" to "InfoHash" so items with message "InfoHash not found"
     are classified correctly. Bump version to v1.9.2. Commit to docker branch.

repo=hashall (file in ~/dev/sys/docker/)
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
target_file=~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
expected_branch=cr/hashall-20260530-000517-claude__j03
allowed_mutation=files+commits

allowed_commands=
- Edit target file (one-line regex change + version bump)
- python3 -m py_compile <file>
- python3 <file> (smoke test, no --cleanup)
- git checkout / git add / git commit in ~/dev/sys/docker/

forbidden_commands=
- make trk-warn-cleanup / --cleanup / --repair
- Any git push
- Editing any other file

required_artifacts=
  version_after=v1.9.2
  auth_err_regex_after="InfoHash|passkey|Torrent not found|not authorized|unauthorized|forbidden"
  syntax_check=pass
  smoke_test_auth_err_count=<N>
  commit_sha=<sha>

success_criteria=
- Regex changed from "Invalid InfoHash" to "InfoHash"
- Version bumped to v1.9.2
- py_compile passes
- smoke test shows [auth_err] count >= 4
- committed to cr/hashall-20260530-000517-claude--trk-warn-footer with S05 trailers

stop_if=
- py_compile fails after edit

final_output_required=true
worktree_mirror_required=false

🟦 task-brief=J03-T19_trk-warn-auth-err-regex-fix 🟦
```

## After completing this task

1. Write TASK-LOG.md to this directory.
2. Notify Lead:
   `tmux send-keys -t %14 "🟪 J03-T19 done | version=v1.9.2 auth_err_count=<N> commit=<sha>" Enter`
