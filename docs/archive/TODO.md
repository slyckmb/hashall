# ✅ TODO.md – Project Maintenance & Roadmap

This document tracks known issues, cleanup tasks, and optional enhancements for the `hashall` project.

---

## ✅ Must Fixes (Completed)

### ✅ Schema Consistency
- [x] Ensure `schema.sql`, migrations, and code agree on:
  - `files(scan_id TEXT)`
  - `files(rel_path TEXT)`
  - `files(sha1 TEXT)`
- [x] All `full_sha1` → `sha1` transition complete

### ✅ Path Handling
- [x] Replace `~` with `$HOME` in all relevant scripts
- [x] Confirmed safe expansion and portability

### ✅ SHA1 Hash Export Warnings
- [x] Files with missing `sha1` are logged and skipped
- [x] Final summary count shown in CLI export log

---

## 🟡 Recommended Enhancements

### 🔁 Database Safety & Validation
- [ ] Validate DB before overwriting during destructive ops
- [ ] Backup existing DB if one exists and migration is needed

### 🧪 Schema Validation
- [ ] Add runtime or CI check to validate schema version alignment

### 📄 Separate Logs for Skipped Files
- [ ] Write `skipped_files.json` or `.log` during export for skipped/missing hash entries
- [ ] Useful for debugging large datasets

---

## 🧹 Deferred / Optional Ideas

- [ ] Add DB versioning table and automatic upgrade history tracking
- [ ] GitHub Actions or pre-commit schema checks
- [ ] Add JSON schema validation CLI for exported data
- [ ] Export human-readable HTML or CSV reports (bonus feature)

---

_Last updated: 2025-06-19_