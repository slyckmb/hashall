---
id: J03-T20
job: 3-pending-repairs
slug: trk-warn-verbose-prowlarr-hits
task_type: implementation
status: staged
brief_revision_id: 2
created_by: lead
created_at: 2026-06-13
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T20 — trk-warn: show verbose Prowlarr hit list when no valid replacement found

## Problem

When trk_warn runs a Prowlarr search and finds no qualifying replacement (e.g. wrong
tracker, wrong quality, or same-tracker enforcement filters everything out), the output
currently just shows:

```
search: hits=0 indexer=aither.cc seeders=0 title=-
```

This is misleading — Prowlarr may have found several results that were filtered out by
B1 (same-tracker enforcement) or quality rules. The operator has no visibility into what
IS available on other trackers, and can't make a manual decision about whether to act.

**Example:** SNL S51E18 on aither.cc — "Torrent has been deleted". Prowlarr finds the
episode on other trackers, but same-tracker enforcement (B1) means none are offered as
replacements. Operator sees "hits=0" and has no idea what's out there.

## Fix

Add a `--verbose-prowlarr` flag. When set:
- After each row's `search:` line in text output, print ALL raw Prowlarr hits (not just
  the same-tracker filtered set), annotated with why each was excluded if it was.
- Cap at a reasonable number (default 10, configurable).
- Format: one line per hit, tab-indented.

### Output format (new verbose section)

```
search: hits=0 indexer=aither.cc seeders=0 title=-   ← existing line
  all_hits (8 total, 0 same-tracker):
    [SKIP:wrong_tracker]  TorrentLeech  seeders=42  Saturday.Night.Live.S51E18...1080p...
    [SKIP:wrong_tracker]  FileList.io   seeders=18  Saturday.Night.Live.S51E18...1080p...
    [SKIP:wrong_tracker]  BroadcasTheNet seeders=7  Saturday.Night.Live.S51E18...WEBRIP...
    ...
```

Skip reasons to annotate:
- `wrong_tracker` — hit is from a different indexer than the torrent's tracker (B1 enforcement)
- `quality_mismatch` — title contains 2160p/UHD/HDR and quality rule rejects it
- `no_seeders` — hit has 0 seeders

### Implementation

In `augment_rows_with_prowlarr()` (around line 395), currently:

```python
hits = search_prowlarr(...)
same_tracker_hits = [hit for hit in hits if ...]
summary = summarize_prowlarr_hits(same_tracker_hits, ...)
summary["same_tracker_found"] = bool(same_tracker_hits)
```

Add storage of all raw hits alongside the filtered set:
```python
summary["all_hits_raw"] = hits          # all results before same-tracker filter
summary["all_hits_count"] = len(hits)   # total before filter
```

In `print_text()`, when `verbose_prowlarr=True` and `summary["all_hits_count"] > 0`:
print the annotated hit list immediately after the `search:` line.

Annotation logic:
```python
def _annotate_skip_reason(hit, indexer_name):
    title = hit.get("title", "")
    if hit.get("indexer", "").lower() != (indexer_name or "").lower():
        return "wrong_tracker"
    if re.search(r"2160p|UHD|HDR|HEVC.*HDR|DV\b", title, re.I):
        return "quality_mismatch"
    if int(hit.get("seeders") or 0) == 0:
        return "no_seeders"
    return None
```

### New flag

```python
parser.add_argument(
    "--verbose-prowlarr",
    action="store_true",
    help="Show all raw Prowlarr hits per row, annotated with skip reasons. Implies --prowlarr.",
)
```

When `--verbose-prowlarr` is set, auto-enable `--prowlarr`.

### Version bump

`v1.9.2 → v1.9.3` (after T19 has committed v1.9.2)

## Target file

```
~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
```

## Verification

```bash
# Syntax check
python3 -m py_compile ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py && echo ok

# Smoke test on the deleted SNL S51E18 item
python3 ~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py \
  --bucket deleted --verbose-prowlarr 2>&1
```

Expected: the deleted SNL S51E18 row shows a `all_hits` section with at least one
cross-tracker hit listed with `[SKIP:wrong_tracker]` annotation (if Prowlarr has results).
If Prowlarr returns nothing at all, section should read `all_hits (0 total)`.

## Commit

Branch: `cr/docker-20260613-095239` (same docker branch as T17+T19)

```bash
cd ~/dev/sys/docker
git checkout cr/docker-20260613-095239
git add gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
GIT_AUTHOR_NAME="claude-code" GIT_AUTHOR_EMAIL="claude-code@chatrap.local" \
GIT_COMMITTER_NAME="claude-code" GIT_COMMITTER_EMAIL="claude-code@chatrap.local" \
git commit -m "feat(trk-warn): v1.9.3 — --verbose-prowlarr shows all hits with skip reasons" \
  -m "Agent-Client: claude-code" \
  -m "Agent-Model: claude-sonnet-4-6" \
  -m "Agent-Model-Slug: claude-code-claude-sonnet-4-6" \
  -m "Job: j03" \
  -m "Task: J03-T20"
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
🟦 task-brief=J03-T20_trk-warn-verbose-prowlarr-hits 🟦

id=J03-T20
role=agent
task_type=implementation
goal=Add --verbose-prowlarr flag to rt-tracker-manual-report.py. When set, print all
     raw Prowlarr hits per row (not just same-tracker filtered set), each annotated
     with skip reason (wrong_tracker / quality_mismatch / no_seeders). Bump to v1.9.3.

     IMPORTANT: T19 is already done (v1.9.2 committed as 8e7c1bb).
     This task starts from v1.9.2 on branch cr/docker-20260613-095239.

repo=hashall (file in ~/dev/sys/docker/)
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
target_file=~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
expected_branch=cr/hashall-20260530-000517-claude__j03
allowed_mutation=files+commits

allowed_commands=
- Read / Edit target file
- python3 -m py_compile <file>
- python3 <file> --bucket deleted --verbose-prowlarr (smoke test, no --cleanup)
- git checkout / git add / git commit in ~/dev/sys/docker/

forbidden_commands=
- make trk-warn-cleanup / --cleanup / --repair
- Any git push
- Editing any other file

required_artifacts=
  version_after=v1.9.3
  verbose_prowlarr_flag=present
  all_hits_raw_stored=yes
  syntax_check=pass
  smoke_test_output=<last 10 lines of --bucket deleted --verbose-prowlarr run>
  commit_sha=<sha>

success_criteria=
- --verbose-prowlarr flag added and auto-enables --prowlarr
- all_hits_raw stored in summary dict
- print_text shows all_hits block with skip annotations when verbose_prowlarr=True
- py_compile passes
- smoke test on --bucket deleted shows hit list or "all_hits (0 total)"
- version v1.9.3 in docstring
- committed to cr/docker-20260613-095239 with S05 trailers

stop_if=
- Target file is not at v1.9.2 (check git log in ~/dev/sys/docker — T19 commit 8e7c1bb must be present)
- py_compile fails after edit

final_output_required=true
worktree_mirror_required=false

🟦 task-brief=J03-T20_trk-warn-verbose-prowlarr-hits 🟦
```

## After completing this task

1. Write TASK-LOG.md to this directory.
2. Notify Lead:
   `tmux send-keys -t %14 "🟪 J03-T20 done | version=v1.9.3 verbose_prowlarr=present snl_hits=<N seen in smoke test> commit=<sha>" Enter`
