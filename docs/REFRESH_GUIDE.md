# Hashall Refresh Guide

## Quick Reference

```bash
# INCREMENTAL (recommended for normal use) — minutes to ~1 hour
make db-refresh
make db-refresh-verbose

# FULL INTEGRITY AUDIT (very slow, only for verification) — 100+ hours
python3 -m hashall refresh --scan-hash-mode full --drift-policy full
```

## Understanding Scan Modes

### `--scan-hash-mode`

| Mode | Behavior | When to Use |
|------|----------|------------|
| `fast` (default) | Only hash files with changed mtime/size | Normal incremental updates |
| `full` | Rehash EVERY file from scratch | Full integrity verification (very slow) |
| `upgrade` | Add full hashes to existing quick-hashes | Backfill missing SHA256 |

### `--drift-policy`

| Policy | Behavior | When to Use |
|--------|----------|------------|
| `metadata` (default for fast) | Trust unchanged metadata, skip rehash | Most incremental runs |
| `quick` | Quick hash check on unchanged files | Safety check without full rehash |
| `full` | Aggressively rehash all unchanged files | Full integrity verification |

## Common Operations

### Normal incremental refresh (dedup + update)
```bash
make db-refresh-verbose
# or
python3 -m hashall refresh
```

**Expected:** minutes to ~1 hour  
**What it does:** scans for new/changed files, updates hashes, runs dedup

### Full integrity audit (find corruption, verify all files)
```bash
python3 -m hashall refresh --scan-hash-mode full --drift-policy full --verbose
```

**Expected:** 100+ hours (rehashes entire 35.7 TB dataset)  
**Warning:** very resource-intensive, only for verification after suspected corruption

### Backfill missing SHA256 hashes
```bash
python3 -m hashall refresh --scan-hash-mode upgrade
```

## Critical Operational Notes

### Refresh Lock Detection Bug (Fixed Apr 24)

**Issue:** Running refresh via `make` or shell pipe failed with "stale process" error  
**Cause:** Parent shell's cmdline contained "refresh" + "hashall", was detected as stale process  
**Fix:** Now excludes parent PID from stale-process scan (commit 9bae44b)

If you see this error anyway:
```bash
# Kill any actual stale refresh processes
pkill -f "python3 -m hashall refresh"

# Clear stale lock files
rm ~/.hashall/refresh.lock ~/.hashall/rehome.lock

# Retry
make db-refresh-verbose
```

### Performance Expectations

| Operation | Time | Notes |
|-----------|------|-------|
| Incremental (fast mode) | 1-60 min | Most common, recommended |
| Integrity audit (full mode) | 100+ hours | On 35.7 TB stash; rehashes everything |
| Dedup phase (if no rehash) | varies | Depends on number of duplicates |

### /pool Disk Space

**Critical:** `/pool` must have ≥5-10 GB free for recovery operations to succeed  
**Monitor:** `df -h /pool`  
**If full:** run `make db-refresh` on stash first to free space via dedup

## Troubleshooting

### "Another hashall refresh process is already running"
```bash
# Check for real stale processes
ps aux | grep "hashall refresh" | grep -v grep

# If any exist, kill them
kill -9 <pid>

# Clear locks
rm ~/.hashall/refresh.lock ~/.hashall/rehome.lock

# Retry
make db-refresh-verbose
```

### Very slow incremental refresh
Check if using `--scan-hash-mode full`. If so:
- Cancel with Ctrl+C
- Retry with `make db-refresh` (uses fast mode)
- Full mode is overkill for normal use

### Dedup not freeing space
- Run `make db-refresh` again (incremental, will dedup cross-linked hardlinks)
- Check `/pool` usage after: `df -h /pool`
