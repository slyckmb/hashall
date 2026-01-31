# Hashall Quick Reference
**Version:** 0.5.0 (Unified Catalog)
**Last Updated:** 2026-01-31

A cheat sheet for common hashall operations.

---

## Quick Start

```bash
# Scan your storage
hashall scan /pool
hashall scan /stash

# Find duplicates
hashall link analyze --device /pool

# Create dedup plan
hashall link plan "Monthly dedupe" --device /pool

# Execute (dry-run first!)
hashall link execute 1 --dry-run
hashall link execute 1 --force
```

---

## Common Commands

### Scanning

```bash
# Initial scan
hashall scan /pool

# Rescan (incremental update)
hashall scan /pool

# Scan multiple devices
hashall scan /pool && hashall scan /stash && hashall scan /backup
```

### Analysis

```bash
# Analyze single device
hashall link analyze --device /pool

# Analyze all devices
hashall link analyze

# Cross-device duplicates
hashall link analyze --cross-device

# Check catalog status
hashall link status
```

### Deduplication

```bash
# Create plan
hashall link plan "NAME" --device /pool

# Review plan
hashall link show-plan 1
hashall link show-plan 1 --limit 50

# Execute (ALWAYS dry-run first!)
hashall link execute 1 --dry-run
hashall link execute 1 --force
```

---

## Useful Queries

### Show All Devices

```bash
hashall link status
```

### Show Recent Scan Activity

```sql
sqlite3 ~/.hashall/catalog.db "
SELECT d.mount_point, datetime(h.started_at, 'unixepoch') as scan_time,
       h.files_added, h.files_removed, h.files_modified
FROM scan_history h
JOIN devices d ON h.device_id = d.device_id
ORDER BY h.started_at DESC
LIMIT 10;
"
```

### Find Biggest Dedup Opportunities

```sql
sqlite3 ~/.hashall/catalog.db "
SELECT * FROM duplicate_groups
ORDER BY total_wasted_bytes DESC
LIMIT 20;
"
```

### Show Hardlink Groups

```sql
sqlite3 ~/.hashall/catalog.db "
SELECT * FROM hardlink_groups
WHERE device_id = 49 AND path_count > 1
ORDER BY size DESC
LIMIT 20;
"
```

---

## Workflow Checklists

### Monthly Deduplication

- [ ] `hashall scan /pool` - Update catalog
- [ ] `hashall link analyze --device /pool` - Find opportunities
- [ ] `hashall link plan "Monthly dedupe" --device /pool` - Create plan
- [ ] `hashall link show-plan <id>` - Review actions
- [ ] `hashall link execute <id> --dry-run` - Test
- [ ] `hashall link execute <id> --force` - Execute

### Initial Setup

- [ ] `hashall scan /pool` - Scan first device
- [ ] `hashall scan /stash` - Scan second device
- [ ] `hashall scan /backup` - Scan third device
- [ ] `hashall link status` - Verify catalog
- [ ] Review dedup opportunities

### Cross-Device Audit

- [ ] `hashall scan /pool` - Update first device
- [ ] `hashall scan /stash` - Update second device
- [ ] `hashall link analyze --cross-device` - Find duplicates
- [ ] Review results (informational only)
- [ ] Decide: delete or consolidate?

---

## Troubleshooting

### "Device not found"
```bash
# Check registered devices
hashall conductor status

# Rescan the device
hashall scan /pool
```

### "Database locked"
```bash
# Check for running scans
ps aux | grep hashall

# Kill if stuck
kill <pid>
```

### "Permission denied"
```bash
# Check database permissions
ls -la ~/.hashall/catalog.db

# Fix if needed
chmod 644 ~/.hashall/catalog.db
```

### "Plan failed"
```bash
# Check execution log
hashall link show-plan <id>

# Common causes:
# - Files moved/deleted between plan and execution
# - Permission issues
# - Disk full

# Solution: Rescan and create new plan
hashall scan /pool
hashall link plan "Retry" --device /pool
```

---

## File Locations

| Item | Location |
|------|----------|
| **Catalog DB** | `~/.hashall/catalog.db` |
| **Logs** | `~/.hashall/logs/` (future) |
| **Config** | `~/.hashall/config.yaml` (future) |

---

## Important Concepts

### Unified Catalog
- **One database** for all storage
- **Device tables** (files_49, files_50, ...)
- **Incremental updates** (not snapshots)

### Hardlinks
- **Same inode** = already hardlinked
- **Different inode, same SHA1** = dedup opportunity
- **Cross-device** = can't hardlink (different filesystems)

### Link Plans
- **NOOP** - Already optimal, no action
- **HARDLINK** - Can link, same device
- **COPY_THEN_HARDLINK** - Cross-device (not implemented)
- **SKIP** - Safety issue, manual review

---

## Quick Tips

**Performance:**
- Scan during off-hours (CPU intensive)
- Use `--parallel` when available (future)
- Large scans: expect ~20-30 files/second

**Safety:**
- ALWAYS `--dry-run` before execute
- Review plans carefully
- Link creates backups (.bak files)
- Failures rollback automatically

**Best Practices:**
- Scan regularly (weekly/monthly)
- Keep catalog updated
- Archive old plans
- Monitor catalog size (VACUUM if large)

---

## See Also

- **[Full CLI Reference](cli.md)** - All commands and options
- **[Link Guide](link-guide.md)** - Complete workflow
- **[Architecture](architecture.md)** - How it works
- **[Schema](schema.md)** - Database design

---

**Need more help?** Check `docs/` or file an issue on GitHub.
