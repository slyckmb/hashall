# J12-T01: Cross-Device Guard Refinement

**Agent:** opencode (deepseek-v4-flash-free)
**Date:** 2026-06-17
**Status:** done

## Summary

Refined `set_location` cross-device guard in `qbittorrent.py`: before blocking on
`st_dev` mismatch, check if torrent files already exist at the target path. If
they do, allow the operation (metadata-only update). 5 new tests added. Gate 3
pilot on both HIGH drift items (2d4016de, f0bc85ee) completed successfully.

## Deliverables

- Modified `src/hashall/qbittorrent.py` (committed)
- Modified `tests/test_qbittorrent.py` (committed)
- Gate 3 results: `docs/gate3-j12-results.md` (committed)
- Task log: `comms/logs/J12-T01-log.md` (this file)

## Results Summary

| Item | Hash | Dry-Run | Execute | Post-State |
|------|------|---------|---------|------------|
| NOVA.S50 | 2d4016de | ✅ | ✅ | ✅ Removed from drift |
| Magic.City.S01 | f0bc85ee | ✅ | ✅ | ✅ Removed from drift |

## Edge Cases Covered

1. **Same device** — guard passes through (no change, existing behavior)
2. **Cross-device, files exist** — bypass, allow set_location (new behavior)
3. **Cross-device, no files** — raise ValueError (block, existing behavior)
4. **Cross-device, get_torrent_files fails** — safe fallback to block (raise ValueError)
5. **Empty file list** — `_files_exist_at_target` returns False, block

## S05 Trailers

- Agent-Client: opencode
- Agent-Model: deepseek-v4-flash-free
- Agent-Model-Slug: opencode-deepseek-v4-flash-free
- Job: j12
- Task: J12-T01
