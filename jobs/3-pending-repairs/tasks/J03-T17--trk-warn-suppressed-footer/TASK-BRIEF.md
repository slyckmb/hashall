---
id: J03-T17
job: 3-pending-repairs
slug: trk-warn-suppressed-footer
task_type: implementation
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-13
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T17 — trk-warn: suppressed-items footer

## Problem

`make trk-warn` silently hides three categories of tracker-error items:

1. **incomplete** (`complete=0`) — items with a tracker error message but not yet 100% done; currently
   skipped by `if int(complete) != 1 or not message: continue` in `build_rows()`. These are invisible
   even when they have real tracker failures (e.g. stoppedDL at 0%).
2. **conn_err** — transient connection errors; excluded unless `--restart-conn-err` is passed.
3. **peer_lim** — peer-limit warnings; excluded unless `--include-peer-limit` is passed.

The operator sees 6 tracker issues in `rt-status` but only 2 in `make trk-warn` — with no explanation
of where the other 4 went. Goal: always surface the suppressed count so the operator is never confused.

## Target file

```
~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
```

Current version: `v1.9.0`
Target version after patch: `v1.9.1`

## Change spec

### 1. `build_rows()` — count suppressed items

Return a second value (suppressed counts dict) alongside the existing row list.
Change signature from:

```python
def build_rows(include_peer_limit: bool, include_conn_err: bool = False) -> list[dict]:
```

to:

```python
def build_rows(include_peer_limit: bool, include_conn_err: bool = False) -> tuple[list[dict], dict[str, int]]:
```

Inside the loop, before the `continue` statements, tally into a local `suppressed` dict:

```python
suppressed: dict[str, int] = {"conn_err": 0, "peer_lim": 0, "incomplete": 0}

for hash_, name, complete, message, label in rows:
    if not message:
        continue
    if int(complete) != 1:
        # Count as suppressed-incomplete if it has a classifiable tracker message
        if classify(message):
            suppressed["incomplete"] += 1
        continue
    bucket = classify(message)
    if not bucket:
        continue
    if bucket == "conn_err" and not include_conn_err:
        suppressed["conn_err"] += 1
        continue
    if bucket == "peer_lim" and not include_peer_limit:
        suppressed["peer_lim"] += 1
        continue
    # ... rest of append logic unchanged ...
```

Return `out, suppressed` at the end of `build_rows`.

### 2. `print_text()` — add suppressed footer

Add `suppressed: dict[str, int]` as a new parameter to `print_text`.

After the last bucket block, if any suppressed count > 0, print ONE footer line:

```python
suppressed_parts = []
if suppressed.get("incomplete"):
    suppressed_parts.append(f"{suppressed['incomplete']} incomplete")
if suppressed.get("conn_err"):
    suppressed_parts.append(f"{suppressed['conn_err']} conn_err")
if suppressed.get("peer_lim"):
    suppressed_parts.append(f"{suppressed['peer_lim']} peer_lim")
if suppressed_parts:
    hints = []
    if suppressed.get("incomplete"):
        hints.append("--include-incomplete")
    if suppressed.get("conn_err"):
        hints.append("--restart-conn-err")
    if suppressed.get("peer_lim"):
        hints.append("--include-peer-limit")
    print(f"\nsuppressed: {', '.join(suppressed_parts)} — use {' / '.join(hints)} to see")
```

### 3. `--include-incomplete` flag — new argument

Add to argparse:

```python
parser.add_argument(
    "--include-incomplete",
    action="store_true",
    help="Include items with tracker errors that are not yet 100% complete (complete=0).",
)
```

Pass it through to `build_rows`:

```python
rows, suppressed = build_rows(
    include_peer_limit=args.include_peer_limit,
    include_conn_err=args.restart_conn_err,
    include_incomplete=getattr(args, "include_incomplete", False),
)
```

Update `build_rows` signature to accept `include_incomplete: bool = False` and skip the
suppression (but not the `continue`) when it is True. Incomplete items are always `report_only`
— do not allow cleanup/repair on them.

### 4. JSON mode

When `--json` is passed, include suppressed counts in the top-level output object:

```json
{"rows": [...], "suppressed": {"incomplete": 2, "conn_err": 1, "peer_lim": 0}}
```

### 5. Version bump

Update the module docstring from `v1.9.0` to `v1.9.1`.

## What NOT to change

- Cleanup, dryrun, repair, upgrade-season-packs, replace-individual paths — untouched.
- `conn_err` restart logic — untouched.
- `BUCKET_PATTERNS` — untouched.
- `DEFAULT_BUCKETS` — untouched.
- Makefile targets — untouched (the Makefile targets already pass the right flags; the footer
  appears automatically in their output).

## Verification

After editing, run:

```bash
python3 ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py 2>&1 | tail -5
```

Expected: output ends with a `suppressed:` line if any suppressed items exist, or normal output
if nothing was suppressed.

Also run:

```bash
python3 -c "
import ast, sys
with open(os.path.expanduser('~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py')) as f:
    src = f.read()
ast.parse(src)
print('syntax ok')
" 2>&1
```

(Or: `python3 -m py_compile ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py && echo ok`)

## Commit

This file lives in `~/dev/sys/docker/` which has a chatrap pre-commit guard on `main`.
Commit to a branch: `cr/hashall-20260530-000517-claude--trk-warn-footer`

```bash
cd ~/dev/sys/docker
git checkout -b cr/hashall-20260530-000517-claude--trk-warn-footer
git add gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
GIT_AUTHOR_NAME="claude-code" GIT_AUTHOR_EMAIL="claude-code@chatrap.local" \
GIT_COMMITTER_NAME="claude-code" GIT_COMMITTER_EMAIL="claude-code@chatrap.local" \
git commit -m "fix(trk-warn): v1.9.1 — suppressed-items footer for conn_err/peer_lim/incomplete" \
  -m "Agent-Client: claude-code" \
  -m "Agent-Model: claude-sonnet-4-6" \
  -m "Agent-Model-Slug: claude-code-claude-sonnet-4-6" \
  -m "Job: j03" \
  -m "Task: J03-T17"
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
🟦 task-brief=J03-T17_trk-warn-suppressed-footer 🟦

id=J03-T17
role=agent
task_type=implementation
goal=Patch rt-tracker-manual-report.py v1.9.0 → v1.9.1 to emit a "suppressed: N incomplete,
     N conn_err, N peer_lim" footer line so the operator always knows when items are hidden.
     Also add --include-incomplete flag for completeness.

repo=hashall (file lives in ~/dev/sys/docker/ — separate repo)
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
target_file=~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
expected_branch=cr/hashall-20260530-000517-claude__j03  (hashall worktree; commit to docker branch)
expected_head=current
allowed_mutation=files+commits

allowed_commands=
- Read / Edit the target file
- python3 -m py_compile <file> (syntax check)
- python3 <file> (smoke test — read-only, no --cleanup)
- git commands in ~/dev/sys/docker/ only (checkout new branch, add, commit)
- git branch --show-current (verify)

forbidden_commands=
- make trk-warn-cleanup / --cleanup / --repair (destructive)
- Any git push
- Editing any file outside ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
- Editing Makefile or hashall source

required_artifacts=
  version_after=v1.9.1
  suppressed_footer_present=true
  syntax_check=pass
  smoke_test_output=<last 5 lines of python3 <file> run>
  docker_branch=cr/hashall-20260530-000517-claude--trk-warn-footer
  commit_sha=<sha>

success_criteria=
- build_rows() returns (rows, suppressed) tuple
- print_text() emits suppressed footer when any count > 0
- --include-incomplete flag added
- JSON mode includes suppressed counts
- py_compile passes
- smoke test shows footer (or "0 suppressed" behavior is correct)
- committed to docker branch with S05 trailers

stop_if=
- File has merge conflicts or unexpected content that changes scope
- py_compile fails after edit

final_output_required=true
worktree_mirror_required=false

🟦 task-brief=J03-T17_trk-warn-suppressed-footer 🟦
```

## After completing this task

1. Write TASK-LOG.md to this directory.
2. Notify Lead:
   `tmux send-keys -t %14 "🟪 J03-T17 done | version=v1.9.1 syntax=pass footer=present docker_branch=cr/hashall-20260530-000517-claude--trk-warn-footer commit=<sha>" Enter`
