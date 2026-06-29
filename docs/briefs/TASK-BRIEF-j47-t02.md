🟦 task-brief=j47-t02_canonicalize-apply-executor 🟦
id=j47-t02
role=agent
task_type=implementation
goal=Build apply_repair_plan() executor and hashall canonicalize-apply / canonicalize-apply-batch CLI commands; default to --dry-run; require --force for live mutations
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260626-151456__j47
expected_branch=cr/hashall-20260626-151456__j47
expected_head=set_at_dispatch
allowed_mutation=files-only
allowed_commands=grep,find,cat,head,tail,python3,pip show,git log,git diff,git status,wc,ls,pytest
forbidden_commands=git commit,git push,pip install,opencode,chatrap job,rm -rf,make
success_criteria=
  - `apply_repair_plan(plan, db_session, config, dry_run=True) -> ApplyResult` added to `src/hashall/canonicalize.py`
  - `ApplyResult` dataclass: torrent_hash, plan_type, dry_run, success, pre_state, post_state, error, notes
  - fix_path_only implementation: rename source dir → canonical path; repoint RT; repoint qB; uses existing repoint functions from lane1_execute.py or equivalent — does NOT reimplement them
  - fix_placement_only implementation: validate cross-device rsync feasible (pool free space > payload size); rsync source → canonical device + path; repoint both clients; deferred cleanup via staged model
  - fix_both implementation: same as fix_placement_only but target path also differs from source structure
  - blocked plan_type: no-op, returns ApplyResult with success=False, error="blocked by external consumer"
  - ok plan_type: no-op, returns ApplyResult with success=True
  - dry_run=True (default): all actions logged but no filesystem or client state changes made
  - dry_run=False (--force): live mutations applied; pre_state captured before, post_state captured after
  - `hashall canonicalize-apply <hash> [--dry-run] [--force]` CLI added
  - `hashall canonicalize-apply-batch [--dry-run] [--force] [--limit N] [--plan-type <type>] [--json]` CLI added
  - Both commands print pre/post state summary; batch prints summary line at end
  - `python3 -c "from hashall.canonicalize import apply_repair_plan"` exits 0
  - `pytest tests/test_canonicalize.py -v` still passes (no regressions)
  - Version bumped to next patch in `src/hashall/__init__.py`
  - task-log emitted with status=done
final_output_required=true
worktree_mirror_required=false
brief_hash="none"
agent_start_timestamp="set by agent at start — brief frozen after"
brief_freeze_violation="false"
🟦 task-brief=j47-t02_canonicalize-apply-executor 🟦

---

## Context

`src/hashall/canonicalize.py` was written in j46-t02 and extended with CLI in j46-t03. This task adds the mutation layer.

Read `src/hashall/canonicalize.py` in full before writing. Read `src/hashall/lane1_execute.py` to understand the existing repoint functions — USE them, do not reimplement.

Also read:
- `docs/REQUIREMENTS.md §5.1` — staged cleanup model (deferred source deletion after MOVE)
- `docs/4-GATE-MUTATION-PROTOCOL.md` (from j47-t01) — understand the abort conditions the executor must support

## ApplyResult Dataclass

```python
@dataclass
class ApplyResult:
    torrent_hash: str
    plan_type: str                    # from RepairPlan
    dry_run: bool
    success: bool
    pre_state: dict                   # {rt_directory, qb_save_path, qb_state, rt_complete}
    post_state: dict | None           # None if dry_run or failure
    error: str | None
    notes: list[str]
```

## Executor Implementation Notes

### fix_path_only

No data movement — just a rename and repoint:
1. Confirm source path exists on disk (`os.path.exists(source_path)`)
2. Confirm target path does NOT exist (no collision)
3. `os.rename(source_path, target_path)` — atomic on same filesystem
4. Repoint RT: use existing RT repoint function (check lane1_execute.py for the right call)
5. Repoint qB: use existing qB set_location (check lane1_execute.py)
6. Record post_state
7. Safety: if RT or qB repoint fails, attempt to rename back (best-effort rollback)

### fix_placement_only and fix_both

Cross-device (or same-device + path change):
1. Validate pool free space ≥ payload_size (refuse if insufficient, do not proceed)
2. `rsync -a --hard-links source_path/ target_path/` (preserves hardlinks within payload)
3. Repoint RT to target_path
4. Repoint qB to target_path's save_path (parent of target_path)
5. Verify RT state transitions to seeding (stoppedUP or stalledUP — not stoppedDL)
6. Stage source for deferred cleanup (move to `.rehome-cleanup-stage/<hash>/`) — do NOT delete immediately
7. Deferred cleanup runs only after operator confirmation (not automated here)

### Safety invariants

- NEVER call apply_repair_plan with dry_run=False unless verdict.reliability == "reliable"
- NEVER proceed with fix_both if move_required and pool_free_bytes < payload_size_bytes
- NEVER call the executor from a job worktree that isn't the CR branch's HEAD (editable install guard: verify pth file before any live mutation)
- On any unexpected exception: log error, set success=False, return immediately — do not partially apply

## CLI Design

```
hashall canonicalize-apply <hash>
    --dry-run     (default) simulate actions, print what would happen
    --force       live execution; mutually exclusive with --dry-run
```

```
hashall canonicalize-apply-batch
    --dry-run           (default)
    --force             live execution
    --limit N           max items to process
    --plan-type <type>  filter to fix_path_only | fix_placement_only | fix_both
    --json              NDJSON output (one ApplyResult per line)
```

The batch command must abort immediately on any ApplyResult with success=False when --force is active. Do not skip failures and continue.

## Version Bump

Read current version from `src/hashall/__init__.py`. Bump patch (e.g. 0.8.62 → 0.8.63). Do not change minor or major.
