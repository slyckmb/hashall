# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# 📘 Hashall: Smart Verify, Treehash, and Hardlink Design Spec

## 🧠 Purpose
To enhance `Hashall` with robust and efficient features for:
- Smart verification of file trees post-migration
- Treehash-based change detection and deduplication
- Inode and hardlink tracking
- Optional repair via rsync

---

## ✅ 1. Smart Verify System

### Goal:
Verify that `DEST_TREE` matches `SOURCE_TREE` fully — using SHA1, inode, and metadata checks.

### Flow:
1. **Detect `.hashall/hashall.json`** in both roots.
2. **Import scan_session** from JSON if not in DB.
3. **Scan both trees into the database** if needed.
4. **Update `.hashall/hashall.json`** with new session data.
5. **Compare `scan_session_id_source` to `scan_session_id_dest`** using DB-level diff.
6. **Output report** (terminal, file, or structured).
7. **Optional: Run rsync repair** for mismatched/missing files.

### CLI Concept:
```bash
hashall verify-trees /src /dst [--repair --force --rsync-source /src]
```

---

## 🌲 2. Treehash Design

### Purpose:
Represent the full content & structure of a file tree (or subtree) with a single hash.

### Per-scan Treehash:
- **Hash all (relpath, sha1, size, mtime)** into one digest
- Stored in `scan_session.treehash`
- Used for fast change detection and caching

### Subtree Treehash (optional):
- New table: `tree_hashes`

```sql
CREATE TABLE tree_hashes (
  id INTEGER PRIMARY KEY,
  scan_session_id INTEGER,
  root_path TEXT,          -- e.g. "Photos/2022/"
  device_id INTEGER,
  file_count INTEGER,
  treehash TEXT
);
```

### Derived From:
- The `files` table: grouped by prefix + `device_id`
- Uses a deterministic `compute_treehash()` function

### Enables:
- 📂 Subtree deduplication and comparison
- 🔄 Efficient repair target narrowing
- 📊 Quick integrity checks for nested trees
- ♻️ Hardlink suggestion engine

### Sample CLI (Future):
```bash
hashall trees --dupes
hashall trees --treehash-report
```

---

## 📦 3. Inode & Hardlink Tracking

### Purpose:
Detect and manage hardlinked files and physical storage dedup.

### Schema Changes:
```sql
ALTER TABLE files ADD COLUMN inode INTEGER;
ALTER TABLE files ADD COLUMN device_id INTEGER;
ALTER TABLE files ADD COLUMN is_hardlink INTEGER DEFAULT 0;
```

### Detection Logic:
```sql
UPDATE files
SET is_hardlink = 1
WHERE inode IN (
  SELECT inode FROM files GROUP BY inode, device_id HAVING COUNT(*) > 1
);
```

---

## 🔁 4. Rsync Repair Integration

### Purpose:
Automatically repair mismatches by pulling files from a known-good source.

### CLI Concept:
```bash
hashall verify-trees /src /dst --repair --rsync-source /src [--force]
```

### Flow:
1. Mismatched/missing files extracted from DB.
2. Create a `--files-from` manifest.
3. Run:
```bash
rsync -aHv --inplace --checksum --files-from manifest /src /dst
```

4. Save log and manifest to `verify_session`.

---

## 📊 5. Proposed Schema Changes

### scan_session (add):
```sql
treehash TEXT
```

### files (add):
```sql
inode INTEGER
device_id INTEGER
is_hardlink INTEGER DEFAULT 0
```

### new: tree_hashes
```sql
CREATE TABLE tree_hashes (
  id INTEGER PRIMARY KEY,
  scan_session_id INTEGER,
  root_path TEXT,
  device_id INTEGER,
  file_count INTEGER,
  treehash TEXT
);
```

---

## ✅ Summary

| Feature            | Description |
|--------------------|-------------|
| Smart Verify       | Full-tree diff + scan reuse |
| Treehash           | Change detection + dedup base |
| Treehash Table     | Enables subtree fingerprinting |
| Inode Tracking     | Hardlink detection and stats |
| Rsync Repair       | Optional self-healing |

Ready for review, approval, and phased implementation.
