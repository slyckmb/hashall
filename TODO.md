# Hashall Worktree TODO — claude-hashall-20260223-124028

Running list of improvements and follow-ups discovered during this session.

---

## sha256-backfill UX

- [ ] **Add progress/heartbeat to `dupes --auto-upgrade`** (`src/hashall/scan.py` or wherever `find_duplicates` lives): ran 14+ min at 101% CPU / 0 disk IO with zero output — indistinguishable from a hang. Needs at minimum: "found N collision groups, upgrading M files..." printed before the IO phase starts, and a progress bar during file reads.

- [ ] **Add progress/heartbeat to `sha256-backfill`** (`src/hashall/sha256_migration.py`): command ran for 8+ min with zero output and nothing in log — impossible to distinguish from a hang. At minimum emit a line every N batches showing files processed / files remaining / elapsed time. A tqdm progress bar would be better.

- [ ] **Fix logging in `sha256-backfill`**: output goes nowhere useful during long runs. Should log to the hashall log file AND emit progress to stdout so `tee` capture in scripts works. Broader issue: several commands have silent long phases — audit and add heartbeats consistently.

- [ ] **Root cause of lost SHA256 on rotation:** when `files_49` couldn't be renamed (target slot occupied), the scan treated all 180k stash files as new `Added` entries and re-hashed only quick_hash — discarding previously computed SHA256. Fix: the collision+rename logic should preserve the old table's data into the new table before the scan runs, not leave it orphaned. Workaround for this session: `bin/db-recover-sha256-from-backup.sh` recovers 102k values from pre-rotation backup via path+size+mtime match.

- [ ] **Full sha256-backfill deferred**: ~330k files (stash 180k, pool 110k, hotspare 39k) are missing full SHA256 (have quick_hash only from scan). Full backfill would take many hours. Deferred — run as a background maintenance job. Payload sync and dedupe only need SHA256 for collision candidates, not all files.

---

## Device ID / Rotation

- [x] **Bug fixed (this session):** `register_or_update_device` crashed with `UNIQUE constraint` when device IDs rotated on reboot and a new ID collided with an existing device's old ID. Fixed by parking the colliding device at a temp negative ID *before* renaming the files table (ordering mattered). Also fixed `rename_files_table` and collision code to quote SQL identifiers (negative IDs contain `-` which broke `ALTER TABLE`). Orphaned `files_49` table dropped after step 1 re-scan.

- [ ] **Future improvement:** Consider using a fully unique/deterministic identifier per filesystem (e.g., ZFS GUID, filesystem UUID) as the *primary* device identity — eliminating any reliance on the kernel `device_id` (which can reassign on reboot). This would make the rotation-handling code unnecessary and prevent surprise reassignments entirely.

---

## qbit Recovery (this session)

- [ ] Triage stoppedUP (3009), stoppedDL (2103), missingFiles (2), count_partial (80) after DB refresh is stable.
- [ ] Re-link torrents that lost content path during failed rehome ops.
- [ ] Start safe stoppedUP (100% complete) torrents via API.
- [ ] Run watchdog with `--enforce-paused-dl` after restarts to contain any re-downloads.

---

## DB Refresh (this session — in progress)

- [x] Backup catalog.db
- [x] Verify qbit API (v5.1.4 @ localhost:9003)
- [x] Step 1: scan /stash/media — 180,143 files, 85.9 TB (full rescan due to rotation bug, now fixed)
- [x] Step 2: scan /pool/data + /mnt/hotspare6tb — pool: 4,661 deleted (rehome casualties), 3,486 added; hotspare: 1,162 added
- [x] Step 3: SHA256 recovery — 102,771 values restored from backup in 1s; 77,346 stash files still missing (new/modified since backup, handled lazily by payload sync)
- [x] Step 4: payload sync — 5,129 torrents synced, 5,150 instances mapped (100%), 4,741 complete payloads, 388 incomplete (missing SHA256), 307 orphans pruned

---
