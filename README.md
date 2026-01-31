# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# hashall

A unified catalog system for file deduplication and management. Hashall maintains a single database of all your files across all storage devices, enabling intelligent deduplication, hardlink management, and safe file migrations.

**Architecture:** Unified Catalog Model (v0.5.0+)

---

## 🔧 Features

- 📊 **Unified Catalog** - Single database for all storage devices
- 🔍 **Incremental Scanning** - Updates catalog with add/remove/modify/move detection
- 🔗 **Hardlink Aware** - Tracks inodes and device IDs for safe deduplication
- 🎯 **Device-Based Tables** - Natural hardlink boundaries, faster queries
- 🧠 **Smart Deduplication** - Conductor plans and executes hardlink operations
- 🔒 **Symlink Safe** - Canonical path resolution prevents double-scanning
- 📦 **ZFS Ready** - Built for ZFS + jdupes + qBittorrent workflows
- 📊 **Progress Bars** - tqdm-powered feedback for all operations

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
# Scan each filesystem you want to catalog
hashall scan /pool
hashall scan /stash
hashall scan /backup
```

This builds a unified catalog at `~/.hashall/catalog.db`.

**What happens:**
- Walks filesystem, computes SHA1 hashes
- Stores file metadata (path, inode, size, mtime, device_id)
- Resolves symlinks to canonical paths
- Detects add/remove/modify/move changes
- Updates in place (incremental, not snapshot)

### 2. Find Deduplication Opportunities

```bash
# Analyze a single device
hashall conductor analyze --device /pool

# Or analyze across all devices
hashall conductor analyze --cross-device
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
hashall conductor plan "Monthly /pool dedupe" --device /pool
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
hashall conductor show-plan 1

# Dry run (preview changes)
hashall conductor execute 1 --dry-run

# Execute for real
hashall conductor execute 1
```

See `docs/conductor-guide.md` for complete workflow.

---

## 📖 Documentation

### Core Documentation
- **[Architecture](docs/architecture.md)** - How the unified catalog works
- **[Unified Catalog Design](docs/unified-catalog-architecture.md)** - Comprehensive design document
- **[CLI Reference](docs/cli.md)** - All commands and options
- **[Database Schema](docs/schema.md)** - Complete schema documentation

### Guides
- **[Conductor Guide](docs/conductor-guide.md)** - Deduplication workflow and best practices
- **[Symlinks & Bind Mounts](docs/symlinks-and-bind-mounts.md)** - How hashall handles them correctly
- **[Quick Reference](docs/quick-reference.md)** - Cheat sheet for common operations

### Historical
- **[Archive](docs/archive/)** - Obsolete docs, session summaries, validation reports

---

## 💡 Common Workflows

### Monthly Deduplication

```bash
# 1. Update catalog
hashall scan /pool

# 2. Find and execute deduplication
hashall conductor plan "Monthly dedupe" --device /pool
hashall conductor execute <plan_id>
```

### Cross-Device Audit

```bash
# Scan all devices
hashall scan /pool
hashall scan /stash

# Find duplicates across devices (informational)
hashall conductor analyze --cross-device
```

### Verify Hardlinks Are Intact

```bash
hashall scan /data
hashall conductor analyze --device /data
# Look for NOOP items (already optimized)
```

### Check Catalog Status

```bash
hashall conductor status

# Output:
# 📊 Registered Devices:
#   /pool  (device 49) - 50,000 files, 500 GB
#   /stash (device 50) - 30,000 files, 300 GB
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

## 🏗️ Architecture Overview

### Unified Catalog Model

```
~/.hashall/catalog.db
  ├─ devices                  (registry: /pool, /stash, ...)
  ├─ files_49                 (files on device 49)
  ├─ files_50                 (files on device 50)
  ├─ hardlink_groups          (inodes with multiple paths)
  ├─ duplicate_groups         (same SHA1 across devices)
  └─ conductor_plans          (deduplication plans)
```

**Key concepts:**
- **One table per device** - Hardlinks only work within a device
- **Incremental updates** - Rescans update existing records, not snapshots
- **Canonical paths** - Symlinks resolved to avoid double-scanning
- **Conductor-ready** - Direct SQL queries, no JSON intermediates

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
- [x] Unified catalog with device tables
- [x] Incremental scan with change detection
- [x] Hardlink tracking (inode + device_id)
- [x] Symlink/bind mount safe scanning
- [x] Conductor deduplication planning
- [x] E2E integration tests
- [x] Canonical path resolution

### In Progress 🚧
- [ ] Conductor execution engine
- [ ] Parallel scanning (multi-threaded hashing)
- [ ] Migration tool (session → unified)

### Planned 📋
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
