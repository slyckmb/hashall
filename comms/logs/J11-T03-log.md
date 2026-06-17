# J11-T03: Class 4 Investigation

**Agent:** opencode (deepseek-v4-flash-free)
**Date:** 2026-06-17
**Status:** done

## Summary

Full investigation of `_rehome-unique/` (Class 4) growth. Found 84 items across
3 locations (stash: 46, pool: 36, hawke-uno: 2). Root cause: `hitchhiker-split`
batch run on May 29 after expanded group detection (May 19). Repair stalled due
to bugs in `save-path-repair` that have since been fixed. 22 empty dirs are
ghost entries from partial repair runs. Future growth stopped by `85ca30f`.

No live system mutations performed. All data is read-only.

## Deliverables

- Investigation report: `docs/class4-investigation.md` (committed)
- Task log: `comms/logs/J11-T03-log.md` (this file)

## Key Findings

| Question | Answer |
|---|---|
| When did new items appear? | May 29 — single batch from hitchhiker-split run |
| Are they all `_rehome-unique/`? | Yes, across 3 seeding root locations |
| Sub-patterns? | 40-char hashes under hawke-uno/ (2 items) vs 16-char elsewhere |
| Files on disk? | Yes — 55 non-empty dirs with real data, 22 empty (ghost dirs) |
| Which tool created them? | `hitchhiker-split` (hitchhiker_split.py) |
| Why 10→64→84? | 10 initial (Apr 21), +54 from batch (May 29), +20 from pool location not previously counted |
| Why stalled? | `save-path-repair` bugs A/B (now fixed in `2c34c6b` + `c7ffae0`) |

## Commands Run

```bash
# Discover and count all _rehome-unique locations
find /data/media /pool/media /mnt -maxdepth 4 -type d -name '_rehome-unique'

# Full inventory per location
for d in /data/media/torrents/seeding/_rehome-unique/*/; do
  hash=$(basename "$d")
  files=$(find "$d" -type f | wc -l)
  size=$(du -sh "$d" | cut -f1)
  echo "$hash  files=$files  size=$size"
done
# Same for /pool/media/torrents/seeding/_rehome-unique/*/
# Same for hawke-uno/_rehome-unique/*/

# Overlap check
comm -12 <(stash_hashes) <(pool_hashes)

# Catalog query (no _rehome-unique entries found — staging dirs not scanned)
sqlite3 ~/.hashall/catalog.db "SELECT COUNT(*) FROM files WHERE path LIKE '%_rehome-unique%'"

# Git history scan
git log --all --oneline --grep="hitchhiker"
git log --all --oneline --grep="rehome"
git log --all --oneline --grep="split"
```

## S05 Trailers

- Agent-Client: opencode
- Agent-Model: deepseek-v4-flash-free
- Agent-Model-Slug: opencode-deepseek-v4-flash-free
- Job: j11
- Task: J11-T03
