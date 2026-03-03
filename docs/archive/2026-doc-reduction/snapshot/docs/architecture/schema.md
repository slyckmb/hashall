# Hashall Database Schema (Concise)
**Model:** Unified Catalog with Incremental Scanning
**Version:** 0.5.0
**Last Updated:** 2026-02-05

**Source of truth:** `src/hashall/migrations/`

---

## Summary (Tables + Purpose)

**Core**
- `devices`: filesystem identity (fs_uuid) + device registry
- `scan_roots`: scanned roots per filesystem (scoped deletion safety)
- `files_<device_id>`: per-device files (path, size, mtime, sha256, sha1, inode, status)
  - Indexes: sha256, sha1, inode, status

**Aggregates**
- `hardlink_groups`: inode groups within a device
- `duplicate_groups`: same SHA256 across devices

**Link Dedup**
- `link_plans`: plan metadata
- `link_actions`: per-action execution status

**Payload Identity**
- `payloads`: payload_hash + root_path + size/file_count
- `torrent_instances`: torrent_hash → payload mapping

**Audit**
- `scan_sessions`: scan metrics and history

---

## Invariants

- One table per device (`files_<device_id>`) is the hardlink boundary.
- File hash is **SHA256** (primary).
- Payload hash is **SHA256 over (path, size, sha256)**; NULL if any SHA256 missing.

---

## Where This Is Defined

- `src/hashall/migrations/0006_add_payload_tables.sql`
- `src/hashall/migrations/0007_incremental_scanning.sql`
- `src/hashall/migrations/0008_add_link_tables.sql`
- `src/hashall/migrations/0009_sha256_backfill.sql`
