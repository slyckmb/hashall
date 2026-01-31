# Hashall Conductor Validation Report

> **Note:** This validation was performed on the session-based model (commit b67da27).
> Validation proved JSON export completeness for conductor integration.
> Results remain valid, but conductor implementation will use unified catalog model (direct DB access).

**Date:** 2026-01-30
**Purpose:** Validate hashall outputs are sufficient for stash↔pool conductor (planner/executor)
**Test Location:** /tmp/hashall_conductor_test
**Database:** /tmp/conductor_test.db

---

## Executive Summary

✅ **ALL VALIDATIONS PASSED**

Hashall export JSON contains all required fields for conductor operations:
- Content identification (sha1)
- Hardlink detection (inode, device_id)
- File metadata (size, mtime, path)
- Session tracking (scan_id, root_path)

**No code changes required.**

---

## Test Setup

Created test directory with:
- `unique.txt` — unique content
- `dupe1.txt`, `dupe2.txt` — same content, different inodes (not hardlinked)
- `hl_original.txt`, `hl_link.txt` — hardlinked files (same inode)

```bash
$ ls -li /tmp/hashall_conductor_test/
125925554 -rw-rw-r-- 1 michael dupe1.txt
125925555 -rw-rw-r-- 1 michael dupe2.txt
125925556 -rw-rw-r-- 2 michael hl_link.txt
125925556 -rw-rw-r-- 2 michael hl_original.txt
125925553 -rw-rw-r-- 1 michael unique.txt
```

**Scan and export commands:**
```bash
python -m hashall scan /tmp/hashall_conductor_test --db /tmp/conductor_test.db
python -m hashall export /tmp/conductor_test.db --root /tmp/hashall_conductor_test
```

**Output location:**
```
/tmp/hashall_conductor_test/.hashall/hashall.json
```

---

## Task A1: Export Schema Check

### Top-level JSON keys:
- `scan_id` — UUID for this scan session
- `root_path` — Scanned directory path
- `files` — Array of file objects

### Representative file object (unique.txt):
```json
{
  "path": "unique.txt",
  "size": 15,
  "mtime": 1769824502.9319592,
  "sha1": "089ca91e56e725986f85f83be240bbf0046059ad",
  "inode": 125925553,
  "device_id": 30
}
```

### Required fields verification:
| Field | Present | Purpose |
|-------|---------|---------|
| ✅ path | Yes | File path relative to root |
| ✅ size | Yes | File size in bytes |
| ✅ mtime | Yes | Modification timestamp |
| ✅ sha1 | Yes | Content hash for dedup detection |
| ✅ inode | Yes | Hardlink detection |
| ✅ device_id | Yes | Cross-device hardlink safety |

**Result: ✅ PASS**

All required fields present. Conductor can:
- Identify files by path
- Detect duplicates by sha1
- Detect hardlinks by (inode, device_id) tuple
- Track file metadata for verification

---

## Task A2: Hardlink Detection Proof

### Validation output:
```
hl_original.txt: inode=125925556, device_id=30, sha1=8abfd478...
hl_link.txt:     inode=125925556, device_id=30, sha1=8abfd478...

Same inode? True
Same device_id? True
Same sha1? True
```

**Result: ✅ PASS**

Hardlinked files correctly identified by matching `(inode, device_id)` tuple.

**Conductor implications:**
- Can detect when two paths reference the same physical file
- Can avoid breaking hardlinks during migration
- Can plan deduplication operations safely
- Can distinguish "already linked" from "should be linked"

**Example conductor logic:**
```python
def are_hardlinked(file1, file2):
    return (file1['inode'] == file2['inode'] and
            file1['device_id'] == file2['device_id'])
```

---

## Task A3: Duplicate-but-not-hardlinked Proof

### Validation output:
```
dupe1.txt: sha1=41dc3ae3..., inode=125925554, device_id=30
dupe2.txt: sha1=41dc3ae3..., inode=125925555, device_id=30

Same sha1? True
Same inode? False
Same device_id? True
```

**Result: ✅ PASS**

Duplicate files correctly distinguished from hardlinks:
- Same content (sha1 matches)
- Different inodes = separate physical files
- Can be safely deduplicated via hardlinking

**Conductor implications:**
- Can identify deduplication opportunities
- Can distinguish "identical content" from "already deduplicated"
- Can plan `ln` operations to create hardlinks
- Can calculate space savings potential

**Example conductor logic:**
```python
def find_dedup_candidates(files):
    """Find files with same sha1 but different inodes."""
    by_hash = {}
    for f in files:
        by_hash.setdefault(f['sha1'], []).append(f)

    candidates = []
    for sha1, file_list in by_hash.items():
        if len(file_list) > 1:
            # Check if they're not already hardlinked
            inodes = {(f['inode'], f['device_id']) for f in file_list}
            if len(inodes) > 1:
                candidates.append(file_list)
    return candidates
```

---

## Conductor Use Cases Validated

### ✅ Use Case 1: Detect existing hardlinks
**Goal:** Avoid breaking existing hardlinks during migration
**Method:** Compare `(inode, device_id)` tuples
**Status:** Supported — Task A2 proof

### ✅ Use Case 2: Identify deduplication opportunities
**Goal:** Find duplicate files that can be hardlinked
**Method:** Group by `sha1`, filter by different `(inode, device_id)`
**Status:** Supported — Task A3 proof

### ✅ Use Case 3: Plan safe migrations
**Goal:** Move files between stash↔pool without data loss
**Method:** Use `sha1` for verification, `inode` for hardlink preservation
**Status:** Supported — Full metadata available

### ✅ Use Case 4: Calculate space usage
**Goal:** Determine actual vs. apparent disk usage
**Method:** Count unique `(inode, device_id)` tuples, multiply by size
**Status:** Supported — All required fields present

### ✅ Use Case 5: Verify transfers
**Goal:** Confirm successful copy/move operations
**Method:** Compare `sha1` before and after
**Status:** Supported — SHA1 hash available

---

## Data Completeness Assessment

| Conductor Need | Hashall Field | Available |
|----------------|---------------|-----------|
| File identification | path | ✅ |
| Content verification | sha1 | ✅ |
| Hardlink detection | inode, device_id | ✅ |
| Size calculations | size | ✅ |
| Freshness checks | mtime | ✅ |
| Session tracking | scan_id | ✅ |
| Root context | root_path | ✅ |

**Coverage: 7/7 (100%)**

---

## Sample Export Structure

Full export for reference:

```json
{
    "scan_id": "75cd3fde-444c-4fcb-b011-9e092699d7ca",
    "root_path": "/tmp/hashall_conductor_test",
    "files": [
        {
            "path": "unique.txt",
            "size": 15,
            "mtime": 1769824502.9319592,
            "sha1": "089ca91e56e725986f85f83be240bbf0046059ad",
            "inode": 125925553,
            "device_id": 30
        },
        {
            "path": "dupe1.txt",
            "size": 18,
            "mtime": 1769824502.9319592,
            "sha1": "41dc3ae3400d92bcd343f1f7d1fd3c399209f203",
            "inode": 125925554,
            "device_id": 30
        },
        {
            "path": "dupe2.txt",
            "size": 18,
            "mtime": 1769824502.9319592,
            "sha1": "41dc3ae3400d92bcd343f1f7d1fd3c399209f203",
            "inode": 125925555,
            "device_id": 30
        },
        {
            "path": "hl_original.txt",
            "size": 19,
            "mtime": 1769824502.9319592,
            "sha1": "8abfd478412a28ece07926dafb09e24bdfb44164",
            "inode": 125925556,
            "device_id": 30
        },
        {
            "path": "hl_link.txt",
            "size": 19,
            "mtime": 1769824502.9319592,
            "sha1": "8abfd478412a28ece07926dafb09e24bdfb44164",
            "inode": 125925556,
            "device_id": 30
        }
    ]
}
```

---

## Validation Summary

| Task | Description | Result |
|------|-------------|--------|
| A1 | Export schema check | ✅ PASS |
| A2 | Hardlink detection proof | ✅ PASS |
| A3 | Duplicate-but-not-hardlinked proof | ✅ PASS |

**Overall: ✅ ALL VALIDATIONS PASSED**

---

## Code Changes Made

**None.** All validations passed on first run.

Current hashall implementation (as of commit b67da27) provides complete and correct output for conductor operations.

---

## Recommendations for Conductor Implementation

### 1. Hardlink Detection
```python
def are_hardlinked(file1, file2):
    """Check if two file entries reference the same physical file."""
    return (file1['inode'] == file2['inode'] and
            file1['device_id'] == file2['device_id'])
```

### 2. Deduplication Candidate Detection
```python
def find_dedup_opportunities(export_data):
    """Find files with identical content but different inodes."""
    from collections import defaultdict

    by_hash = defaultdict(list)
    for f in export_data['files']:
        by_hash[f['sha1']].append(f)

    opportunities = []
    for sha1, files in by_hash.items():
        if len(files) > 1:
            # Check if they're not already hardlinked
            unique_inodes = {(f['inode'], f['device_id']) for f in files}
            if len(unique_inodes) > 1:
                opportunities.append({
                    'sha1': sha1,
                    'files': files,
                    'space_savings': (len(files) - 1) * files[0]['size']
                })

    return opportunities
```

### 3. Space Calculation
```python
def calculate_actual_space(export_data):
    """Calculate actual disk usage accounting for hardlinks."""
    unique_files = {}
    for f in export_data['files']:
        key = (f['inode'], f['device_id'])
        if key not in unique_files:
            unique_files[key] = f['size']

    return sum(unique_files.values())
```

### 4. Content Verification
```python
def verify_transfer(src_export, dst_export, file_path):
    """Verify a file was correctly transferred."""
    src_file = next(f for f in src_export['files'] if f['path'] == file_path)
    dst_file = next(f for f in dst_export['files'] if f['path'] == file_path)

    return (src_file['sha1'] == dst_file['sha1'] and
            src_file['size'] == dst_file['size'])
```

---

## Conclusion

Hashall export format is **production-ready** for conductor integration.

All required metadata is present and correctly populated:
- Content hashing for verification
- Hardlink detection for safe deduplication
- File metadata for planning operations
- Session tracking for reproducibility

The conductor can confidently use hashall exports to:
- Plan stash↔pool migrations
- Identify deduplication opportunities
- Preserve existing hardlinks
- Verify transfer integrity
- Calculate space savings

**Status: READY FOR CONDUCTOR INTEGRATION ✅**
