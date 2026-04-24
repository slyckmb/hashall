---
chat_id: hashall-20260420-175812-claude
status: in_progress
phase: execute
model_tier: standard
agent: claude
goal: "Hitchhiker split + save-path-repair + recovery from broken repair runs"
current_step: "recovery_executing"
files_changed: 6
repair_cycles: 1
created_at: 2026-04-20 17:58:14
updated_at: 2026-04-23 11:10:00
---

## Session Summary (2026-04-23 continuation)

**Objective:** Fix damage from two broken save-path-repair runs, recover 338 missingFiles hashes

### Context

After hitchhiker splits completed (all groups PARTIALLY_SPLIT), save-path-repair ran
twice with bugs. Two broken runs displaced content for 338 hashes.

### Bugs Found in save_path_repair.py

Six critical bugs identified via code walkthrough:

| Bug | File | Impact |
|-----|------|--------|
| `_move_tree`: `relative_to(src.parent)` → preserves hash dir in path | save_path_repair.py:105 | Files land at `dst/<hash>/content` not `dst/content` |
| `execute_repair`: `dst_parent = canonical.parent` not `canonical` | save_path_repair.py:317 | Files one dir level too high |
| Hash16 vs hash40 mismatch in qB/DB lookups | execute_repair:287 | qB category/tags unknown for new-style splits |
| Missing stop_qb → patch_fastresume → start_qb | execute_repair | qB save_path not persisted across restarts |
| Missing `recheck_torrent()` | execute_repair | Stays in missingFiles after move |
| RT gets save_path not content dir (save_path/name) | execute_repair:334 | RT directory wrong |

### Damage from two broken runs

- Run 1: ~156 hashes displaced (files at `parent_of_canonical/<hash>/content`)
- Run 2: background task, additional 182 hashes displaced  
- Total: 338 missingFiles in qB, 338 stoppedDL in RT

### Displacement patterns

- Uncategorized (stash): files at `/stash/media/torrents/<hash>/content`
- Cross-seed (stash): files at `/stash/media/torrents/seeding/cross-seed/<hash>/content`
- Movies/TV/other: files at `/stash/media/torrents/seeding/<hash>/content`
- Pool equivalents: same pattern under `/pool/media/torrents/`

### Files Modified (commit 6faa6d5)

- `src/hashall/save_path_repair.py` — fixed all 6 bugs
- `src/hashall/save_path_recovery.py` — NEW: batch recovery module
- `src/hashall/cli.py` — added `save-path-recover` command

### Recovery plan

- 338 candidates identified, 336/338 files located (2 in orphans, unrecoverable)
- 1935 files to move, 1446 already at canonical (cross-seed dup, skipped)
- Recovery: move files → stop qB → patch 336 fastresumes → start qB → recheck all → repoint RT

### Recovery execution (RUNNING as of 2026-04-23 ~11:10)

```
python3 -m hashall payload save-path-recover --execute
```

Recovery stops qB, patches fastresumes in batch, starts qB, rechecks all 338 hashes.

### Edge cases requiring manual fix after recovery

- `5bf579e7c4c98dae` (How It's Made S01-S32, DocsPedia): files in orphans path or lost
- `81ede24f8477eca6` (How It's Made S01-S32, DocsPedia): same group, in `/pool/torrents/orphans/`
- After recovery moves `80e7ac733040aa33` (same group) to `cross-seed/DocsPedia`, point
  both 5bf579 and 81ede24 fastresumes to same canonical path and recheck

### Next after recovery completes

1. Verify qB state: missingFiles should drop from 338 to ~2
2. Update qB cache: `python3 -m hashall qb-cache refresh` (or let daemon refresh)
3. Check RT stalledUP: all 338 RT stoppedDL should resume
4. Fix 2 edge case hashes manually
5. Continue with original plan: save-path-audit, drift detection

### Previous session work (2026-04-20)

See below for waves 10-12 history.

---

## Previous Session Summary (2026-04-20)

**Objective:** Complete orphaned_data → orphans migration (Big-picture TODO #2)

### Completed Tasks

1. **Wave 11: Code Refactoring** — Updated orphan_sweep.py, content_inventory.py,
   cli.py, qb_repair_payload_group.py to canonical orphans paths. Commit: d4bd9b0

2. **Wave 10: Final Orphan Rename Batch** — Moved all 17 roots from orphaned_data
   to orphans. Fixed RT repoints.

3. **Wave 12: Cleanup** — Removed stale cross-seed-link residue directory

### Big-Picture Next Steps (still valid)

1. Monitor/Fix RT↔qB drift after recovery completes
2. Restore canonical save paths (item #10)
3. Cross-seed-link → cross-seed normalization (item #1)
4. Fix broken live torrents (item #3)
5. Drain /pool/data torrent payloads (item #4)
