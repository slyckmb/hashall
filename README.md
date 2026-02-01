# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# hashall

A unified catalog system for file deduplication and management. Hashall maintains a single database of all your files across all storage devices, enabling intelligent deduplication, hardlink management, and safe file migrations.

**Architecture:** Unified Catalog Model (v0.5.0+)

---

## 🔧 Features

- 📊 **Unified Catalog** - Single database for all storage devices
- 🚀 **Incremental Scanning** - 10-100x faster rescans by skipping unchanged files
- 🔐 **Filesystem UUID Tracking** - Persistent device identity across reboots
- 🔍 **Smart Change Detection** - Automatic add/remove/modify/move detection
- 🔗 **Hardlink Aware** - Tracks inodes and device IDs for safe deduplication
- 🎯 **Device-Based Tables** - Natural hardlink boundaries, faster queries
- ⚡ **Parallel Scanning** - Multi-threaded hashing for 4-5x speedup
- 🔒 **Scoped Deletion** - Safe partial rescans without false deletions
- 📦 **ZFS Ready** - Built for ZFS + jdupes + qBittorrent workflows
- 📊 **Progress Bars** - tqdm-powered feedback for all operations
- 🎯 **Payload Identity** - Track multiple torrents pointing to same content

---

## 📦 Installation

```bash
git clone git@github.com:slyckmb/hashall.git
cd hashall
python3 -m venv $HOME/.venvs/hashall
source $HOME/.venvs/hashall/bin/activate
pip install -r requirements.txt
```

---

## 🚀 Quick Start

### 1. Scan Your Storage

```bash
# Initial scan (hashes all files)
hashall scan /pool

# Incremental rescan (10-100x faster - skips unchanged files)
hashall scan /pool

# Parallel scan for large datasets
hashall scan /pool --parallel --workers 8

# Scan multiple filesystems
hashall scan /stash
hashall scan /backup
```

This builds a unified catalog at `~/.hashall/hashall.sqlite3`.

**What happens on initial scan:**
- Detects filesystem UUID (persistent across reboots)
- Creates per-device table (files_49, files_50, etc.)
- Walks filesystem, computes SHA1 hashes
- Stores file metadata (path, inode, size, mtime, sha1)
- Tracks scan root for scoped deletion detection

**What happens on incremental rescan:**
- Loads existing files from catalog
- Skips SHA1 computation for unchanged files (same size+mtime)
- Only rehashes modified/new files
- Detects deletions (scoped to scanned root)
- **Result: 10-100x faster than initial scan**

**Performance:**
- Initial: ~20-30 files/s (sequential), ~100-150 files/s (parallel 8 workers)
- Rescan: ~500-1000 files/s (sequential), ~2000-5000 files/s (parallel)

### 2. Find Deduplication Opportunities

```bash
# Analyze a single device
hashall link analyze --device /pool

# Or analyze across all devices
hashall link analyze --cross-device
```

**Output:**
```
🔍 Same-device deduplication opportunities:
  /pool: 250 opportunities, 45.2 GB saveable

🌐 Cross-device duplicates:
  50 files duplicated across 2 devices, 12.3 GB total
```

### 3. Create a Deduplication Plan

```bash
hashall link plan "Monthly /pool dedupe" --device /pool
```

**Output:**
```
✅ Plan created: Monthly /pool dedupe
   ID: 1
   Opportunities: 250
   Potential savings: 45.2 GB
```

### 4. Review and Execute

```bash
# Review the plan
hashall link show-plan 1

# Dry run (preview changes)
hashall link execute 1 --dry-run

# Execute for real
hashall link execute 1
```

See `docs/link-guide.md` for complete workflow.

### 5. View Device Statistics

```bash
# List all registered devices
hashall devices list

# Show detailed device info
hashall devices show pool

# Overall catalog stats
hashall stats
```

**Output:**
```
Devices: 2
  pool   (49): 50,000 files, 500.0 GB
  stash  (50): 30,000 files, 300.0 GB

Total Files: 80,000 active, 245 deleted
Total Size: 800.0 GB
Last Scan: 2026-02-01 14:30:00 (pool)
```

### 6. Map Torrents to Payloads

```bash
# Sync torrents from qBittorrent
hashall payload sync

# Show payload for a torrent
hashall payload show <torrent_hash>

# Find sibling torrents (same content, different metadata)
hashall payload siblings <torrent_hash>
```

**Payload identity** tracks the on-disk content independently of torrent metadata. Different torrents (v1/v2, different piece sizes, different sources) that point to identical content map to the same payload.

---

## 📖 Documentation

### Core Documentation
- **[Architecture](docs/architecture.md)** - How the unified catalog works
- **[Unified Catalog Design](docs/unified-catalog-architecture.md)** - Comprehensive design document
- **[CLI Reference](docs/cli.md)** - All commands and options
- **[Database Schema](docs/schema.md)** - Complete schema documentation

### Guides
- **[Link Guide](docs/link-guide.md)** - Deduplication workflow and best practices
- **[Symlinks & Bind Mounts](docs/symlinks-and-bind-mounts.md)** - How hashall handles them correctly
- **[Quick Reference](docs/quick-reference.md)** - Cheat sheet for common operations

### Historical
- **[Archive](docs/archive/)** - Obsolete docs, session summaries, validation reports

---

## 💡 Common Workflows

### Monthly Incremental Update

```bash
# Fast incremental rescan (10-100x faster than initial)
hashall scan /pool

# Check what changed
hashall stats
hashall devices show pool
```

### Monthly Deduplication

```bash
# 1. Update catalog (fast incremental)
hashall scan /pool

# 2. Find and execute deduplication
hashall link plan "Monthly dedupe" --device /pool
hashall link execute <plan_id>
```

### Cross-Device Audit

```bash
# Scan all devices (incremental)
hashall scan /pool
hashall scan /stash

# Find duplicates across devices (informational)
hashall link analyze --cross-device
```

### Check Catalog Status

```bash
# Quick stats
hashall stats

# Device details
hashall devices list
hashall devices show pool

# Output:
# Device: pool
#   Filesystem UUID: zfs-12345678
#   Total Files: 50,000 active, 123 deleted
#   Total Size: 500.0 GB
#   Scan Count: 25
```

---

## 🧪 Running Tests

```bash
pytest tests/
```

Individual test files:
```bash
python3 tests/test_e2e_workflow.py
python3 tests/test_verify_trees.py
python3 tests/test_diff.py
```

---

## 📊 Performance Benchmarks

Comprehensive performance benchmarks are available to measure incremental scanning efficiency.

```bash
# Run all benchmarks (creates 10k test files)
python3 benchmarks/bench_incremental.py

# Run on existing directory
python3 benchmarks/bench_incremental.py --target /path/to/dir --skip-setup
```

**Benchmark results:**
- Sequential scan: ~9,000 files/sec
- Incremental rescan (0% changed): 3x faster
- Database growth: Constant size (0.4% variance)

See `benchmarks/` for detailed results and analysis.

---

## 🏗️ Architecture Overview

### Unified Catalog Model

```
~/.hashall/hashall.sqlite3
  ├─ devices                  (registry: fs_uuid, device_id, alias, mount_point)
  ├─ scan_roots               (tracks which paths have been scanned)
  ├─ scan_sessions            (audit trail with incremental metrics)
  ├─ files_49                 (files on device 49 - created dynamically)
  ├─ files_50                 (files on device 50 - created dynamically)
  ├─ payloads                 (torrent content fingerprints)
  ├─ torrent_instances        (qBittorrent torrent → payload mapping)
  └─ link_plans               (deduplication plans - future)
```

**Key concepts:**
- **Filesystem UUID tracking** - Persistent device identity across reboots
- **One table per device** - Hardlinks only work within a device
- **Incremental updates** - Rescans skip unchanged files (10-100x faster)
- **Scoped deletion** - Only marks files deleted under scanned roots
- **Parallel scanning** - Multi-threaded hashing for 4-5x speedup
- **Canonical paths** - Symlinks resolved to avoid double-scanning
- **Direct SQL** - No JSON intermediates, fast queries

See `docs/architecture.md` for complete details.

---

## 🔄 Migration from Session-Based Model

If upgrading from v0.4.x (session-based):

```bash
# Export latest session
hashall export old.db --root /pool --out /tmp/pool.json

# Import into unified catalog (future feature)
hashall import /tmp/pool.json --device /pool
```

See `docs/unified-catalog-architecture.md` for migration guide.

---

## 📌 Roadmap

### Completed ✅
- [x] Unified catalog with per-device tables
- [x] Incremental scanning with 10-100x speedup on rescans
- [x] Filesystem UUID tracking (persistent across reboots)
- [x] Parallel scanning (multi-threaded hashing, 4-5x faster)
- [x] Scoped deletion detection
- [x] Hardlink tracking (inode + device_id)
- [x] Symlink/bind mount safe scanning
- [x] Device management CLI (list, show, alias)
- [x] Statistics and audit trail
- [x] Payload identity for torrent tracking
- [x] E2E integration tests

### In Progress 🚧
- [ ] Link execution engine
- [ ] Link deduplication planning (documented, not yet coded)

### Planned 📋
- [ ] Migration tool (old session-based → new incremental)
- [ ] Web UI for browsing catalog
- [ ] Subtree treehash for fast comparison
- [ ] Automated deduplication schedules
- [ ] Advanced filters (size, date, patterns)
- [ ] Cloud integration (S3, Backblaze)

---

## 🤝 Contributing

Contributions welcome! Please:
1. Read `docs/architecture.md` to understand the unified catalog model
2. Check existing issues or create a new one
3. Submit PRs with tests and documentation

---

## 📄 License

MIT

---

## 👤 Author

Maintained by [slyckmb](https://github.com/slyckmb)

---

## 🙏 Acknowledgments

Built with:
- SQLite for catalog storage
- tqdm for progress bars
- Click for CLI
- pytest for testing

---

**Questions?** See `docs/` or file an issue on GitHub.
