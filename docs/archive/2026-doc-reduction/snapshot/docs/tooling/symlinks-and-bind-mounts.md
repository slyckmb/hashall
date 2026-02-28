# Handling Symlinks, Bind Mounts, and Hardlinks

## The Problem

You want to avoid double-scanning the same files when they're accessible via:
- **Symlinked directories**: `/data/media -> /stash/media`
- **Bind mounts**: `/data/media` bind-mounted to `/stash/media`

But you DO want to track **hardlinks** (intentional duplicates with different paths).

---

## The Solution: Canonical Path Resolution + Device/Inode Tracking

### Key Principles

1. **Symlinks resolve to same canonical path** → Scan once
2. **Bind mounts have same device+inode** → Detect and skip
3. **Hardlinks have different canonical paths** → Record all paths

### Algorithm

```python
For each file encountered:
    1. Resolve to canonical path (follows symlinks)
    2. Get (device_id, inode)
    3. Create key: (device_id, inode, canonical_path)
    4. If key already seen in this scan → SKIP
    5. Else → SCAN and add to catalog
```

---

## Scenario Analysis

### Scenario 1: Symlinked Directory

```
Filesystem:
  /stash/media/movies/film.mp4    (device 49, inode 12345)
  /data/media -> /stash/media     (symlink)

When scanning /data/media/movies/film.mp4:
  1. Path: /data/media/movies/film.mp4
  2. Canonical: /stash/media/movies/film.mp4  ← Resolved!
  3. Key: (49, 12345, "/stash/media/movies/film.mp4")

When scanning /stash/media/movies/film.mp4:
  1. Path: /stash/media/movies/film.mp4
  2. Canonical: /stash/media/movies/film.mp4
  3. Key: (49, 12345, "/stash/media/movies/film.mp4")  ← SAME KEY!

Result: ✅ Only scanned once (via canonical path)
```

### Scenario 2: Bind Mount

```
Filesystem:
  /stash/media/movies/film.mp4    (device 49, inode 12345)
  /data/media  (bind mount to /stash/media)

When scanning /data/media/movies/film.mp4:
  1. Path: /data/media/movies/film.mp4
  2. Canonical: /data/media/movies/film.mp4  ← Already canonical
  3. Device: 49, Inode: 12345
  4. Key: (49, 12345, "/data/media/movies/film.mp4")

When scanning /stash/media/movies/film.mp4:
  1. Path: /stash/media/movies/film.mp4
  2. Canonical: /stash/media/movies/film.mp4
  3. Device: 49, Inode: 12345  ← SAME DEVICE+INODE!
  4. Key: (49, 12345, "/stash/media/movies/film.mp4")

Problem: Different canonical paths, but SAME content!
```

**Bind mount detection:**
```python
# Canonical paths differ, but (device, inode) is the same
# → Check if we've seen this (device, inode) before
# → If yes, it's a bind mount duplicate

if (device_id, inode) in seen_inodes:
    # Already scanned this physical file
    skip = True
```

### Scenario 3: Intentional Hardlinks (Should NOT Skip)

```
Filesystem:
  /pool/music/song.mp3           (device 49, inode 100)
  /pool/backup/song.mp3          (device 49, inode 100)

When scanning /pool/music/song.mp3:
  1. Path: /pool/music/song.mp3
  2. Canonical: /pool/music/song.mp3
  3. Key: (49, 100, "/pool/music/song.mp3")
  4. SCAN ✅

When scanning /pool/backup/song.mp3:
  1. Path: /pool/backup/song.mp3
  2. Canonical: /pool/backup/song.mp3  ← DIFFERENT!
  3. Key: (49, 100, "/pool/backup/song.mp3")  ← DIFFERENT KEY!
  4. SCAN ✅

Result: ✅ Both paths recorded (intentional hardlinks)
```

---

## Decision Tree

```
                    Encounter file
                         |
                         v
              Resolve to canonical path
                         |
                         v
            Get (device_id, inode)
                         |
                         v
    Key = (device_id, inode, canonical_path)
                         |
                         v
                 Already seen?
                    /        \
                  YES         NO
                   |           |
                   v           v
              SKIP (it's    SCAN (it's
              symlink or    new or
              bind mount)   hardlink)
```

---

## Improved Algorithm with Inode Tracking

The issue with bind mounts is that canonical paths differ, but they point to the same physical file. We need to track inodes separately:

```python
seen_canonical_paths = set()      # Track canonical paths
seen_inodes = {}                  # Track (device, inode) -> canonical_path

for file in walk(root):
    canonical = file.resolve()
    device_id = file.stat().st_dev
    inode = file.stat().st_ino

    # Check if this exact canonical path was seen
    if canonical in seen_canonical_paths:
        skip("Duplicate canonical path - symlink")
        continue

    # Check if this inode was seen at a DIFFERENT canonical path
    inode_key = (device_id, inode)
    if inode_key in seen_inodes:
        previous_canonical = seen_inodes[inode_key]

        # Same canonical path? Shouldn't happen, but skip
        if previous_canonical == canonical:
            skip("Already scanned")
            continue

        # Different canonical path, same inode = bind mount or hardlink
        # Need to distinguish:

        if is_bind_mount(canonical, previous_canonical):
            skip("Bind mount duplicate")
            continue
        else:
            # It's a hardlink - record both paths
            scan("Hardlink - different path, same inode")

    # New file - scan it
    seen_canonical_paths.add(canonical)
    seen_inodes[inode_key] = canonical
    scan(file)
```

---

## Detecting Bind Mounts

How do we know if two paths with the same inode are a bind mount vs. hardlink?

### Method 1: Check Mount Points

```python
def is_bind_mount(path1, path2):
    """
    Check if path1 and path2 are on different mount points
    but same device (bind mount indicator).
    """
    mount1 = find_mount_point(path1)
    mount2 = find_mount_point(path2)

    # Different mount points but same device = bind mount
    return mount1 != mount2 and \
           path1.stat().st_dev == path2.stat().st_dev
```

### Method 2: Use /proc/mounts

```bash
# Check /proc/mounts for bind mounts
cat /proc/mounts | grep "bind"

# Example output:
/stash/media /data/media none rw,bind 0 0
```

### Method 3: Use findmnt

```bash
findmnt --list | grep bind

# Or programmatically:
findmnt -J --real
```

---

## Practical Implementation

### Step 1: Pre-scan Analysis

Before scanning, detect all bind mounts and symlinks:

```python
class SmartScanner:
    def __init__(self):
        self.bind_mounts = self.detect_bind_mounts()
        self.scan_roots = set()

    def detect_bind_mounts(self):
        """Return dict: {target: source}"""
        bind_mounts = {}
        with open('/proc/mounts') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and 'bind' in parts[3]:
                    source, target = parts[0], parts[1]
                    bind_mounts[target] = source
        return bind_mounts

    def add_scan_root(self, root):
        """Register a root to scan."""
        canonical = Path(root).resolve()

        # Check if this is a bind mount target
        if str(canonical) in self.bind_mounts:
            source = self.bind_mounts[str(canonical)]
            print(f"⚠️  {root} is a bind mount from {source}")
            print(f"   Will scan source instead: {source}")
            canonical = Path(source).resolve()

        # Check if we're already scanning this canonical root
        if canonical in self.scan_roots:
            print(f"⚠️  {root} already registered (canonical: {canonical})")
            return False

        self.scan_roots.add(canonical)
        return True
```

### Step 2: Scan with Deduplication

```python
def scan_directory(self, root):
    """Scan directory, avoiding symlinks and bind mount duplicates."""
    root = Path(root).resolve()

    # Track what we've seen in THIS scan
    seen_in_scan = set()  # (device, inode, canonical_path)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Don't follow symlinked directories
        dirnames[:] = [d for d in dirnames
                      if not (Path(dirpath) / d).is_symlink()]

        for filename in filenames:
            filepath = Path(dirpath) / filename

            # Skip symlinked files
            if filepath.is_symlink():
                print(f"⏭️  Skipping symlink: {filepath}")
                continue

            # Get canonical path
            canonical = filepath.resolve()

            # Get device and inode
            stat = filepath.stat()
            device_id = stat.st_dev
            inode = stat.st_ino

            # Check if already seen
            key = (device_id, inode, str(canonical))
            if key in seen_in_scan:
                print(f"⏭️  Already scanned: {canonical}")
                continue

            # Mark as seen
            seen_in_scan.add(key)

            # Process file
            print(f"✅ Scanning: {canonical}")
            self.process_file(canonical, device_id, inode, stat)
```

---

## Storage in Catalog

Store the **canonical path** in the database:

```sql
CREATE TABLE files_49 (
    path TEXT PRIMARY KEY,           -- CANONICAL path (resolved)
    inode INTEGER NOT NULL,
    size INTEGER NOT NULL,
    ...
);
```

This ensures:
- No duplicates from symlinks/bind mounts
- Hardlinks still tracked (different canonical paths)
- Queries work on real paths

---

## User Workflow

### 1. Check Your Setup

```bash
# Find bind mounts
python canonical_path_handling.py find-bind-mounts

# Check relationship between two paths
python canonical_path_handling.py check /data/media /stash/media
```

Output example:
```
Analyzing relationship between:
  Path 1: /data/media
  Path 2: /stash/media

🔗 Path 1 is a symlink to: ../stash/media
Canonical paths:
  Path 1: /stash/media
  Path 2: /stash/media

✅ SAME: Both paths resolve to the same canonical location
   → Will only be scanned once
```

### 2. Scan Intelligently

```bash
# Just scan one root - symlinks will be resolved
hashall scan /data         # Resolves symlinks to /stash

# Or scan the canonical root directly
hashall scan /stash        # Direct scan of actual location
```

### 3. Verify No Duplicates

```bash
# Check for duplicate inodes in catalog
sqlite3 ~/.hashall/catalog.db "
  SELECT inode, COUNT(*) as paths, GROUP_CONCAT(path)
  FROM files_49
  GROUP BY inode
  HAVING paths > 1
"
```

This will show only intentional hardlinks, not bind mount/symlink duplicates.

---

## Summary

### ✅ What Gets Scanned Once

- Files accessed via symlinked directories
- Files accessed via bind mounts
- Files accessed via multiple symlinks to the same target

### ✅ What Gets Scanned Multiple Times (Intentional)

- Hardlinks (different paths, same inode)
- Files with same content but different inodes (duplicates to deduplicate)

### 🔑 Key Implementation Points

1. **Always resolve to canonical path**: `path.resolve()`
2. **Track (device_id, inode, canonical_path)** during scan
3. **Skip if already seen** in current scan
4. **Don't follow symlinks** in `os.walk()`
5. **Pre-detect bind mounts** to warn user or adjust scan roots

---

## Testing Scenarios

Create test cases:

```bash
# Setup test filesystem
mkdir -p /tmp/test/{real,symlink_target,bind_target}
echo "content" > /tmp/test/real/file.txt

# Symlink
ln -s /tmp/test/real /tmp/test/symlink_target

# Bind mount
sudo mount --bind /tmp/test/real /tmp/test/bind_target

# Hardlink
ln /tmp/test/real/file.txt /tmp/test/real/hardlink.txt

# Now scan /tmp/test
# Expected results:
# - file.txt and hardlink.txt: BOTH scanned (2 canonical paths)
# - symlink_target/file.txt: SKIPPED (resolves to real/file.txt)
# - bind_target/file.txt: SKIPPED (same device+inode as real/file.txt)
```

---

## Recommendation for hashall

Add to scan logic:

```python
class Scanner:
    def __init__(self):
        self.seen_in_scan = set()

    def scan(self, root):
        self.seen_in_scan.clear()
        root = Path(root).resolve()  # Resolve root first

        for filepath in walk(root):
            if filepath.is_symlink():
                continue  # Skip symlinks

            canonical = filepath.resolve()
            stat = filepath.stat()
            key = (stat.st_dev, stat.st_ino, str(canonical))

            if key in self.seen_in_scan:
                continue  # Already scanned

            self.seen_in_scan.add(key)
            self.process_file(canonical, stat)
```

Simple, effective, handles all cases correctly.
