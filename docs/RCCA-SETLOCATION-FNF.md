# RCCA: set_location FileNotFoundError bypass

**Date:** 2026-06-18
**Task:** J23-T01
**File:** `src/hashall/qbittorrent.py`, method `set_location()`, lines 1440–1446

---

## Root Cause

When `os.stat(old_path)` raises `FileNotFoundError`, the code assumed the old
path "no longer exists" (e.g. after a same-device rename) and skipped ALL
cross-device checks unconditionally. This assumption is wrong for paths under
`/data/media/torrents/seeding/...` which are:

- **Container-internal paths** — `/data/` is a Docker bind mount, invisible to
  the host OS via `os.stat()`.
- **Fully accessible inside qB** — qBittorrent runs in a container where
  `/data/media/` maps to `/stash/media/` on the host.

With `skip_device_check = True`, `setLocation` was sent from `/data/media/...`
(stash) to `/pool/media/...` (pool). qB, running inside the container, performed
a **cross-device file move** it was never authorized to make. With
`resume_after=False`, no recheck was triggered, leaving torrents in stoppedDL.

## Impact

22 cross-seed dup repoints + 12 conflict repoints in j22 hit this path. Those
torrents had qB save_path at `/data/media/torrents/seeding/<tracker>/`. Host
`os.stat` returned FileNotFoundError → `skip_device_check = True` → qB moved
files stash→pool without authorization → torrents landed in stoppedDL.
(Batch recheck in J20-T02 recovered them by verifying data at pool paths.)

## Fix

Replace the unconditional `skip_device_check = True` with a `_files_exist_at_target`
check — the same guard used by the explicit cross-device case (lines 1453–1469).
Only allow the bypass if files are confirmed present at the target path.

### Before
```python
except FileNotFoundError:
    # Old path no longer exists (already renamed) → metadata-only, safe
    print(...)
    skip_device_check = True
```

### After
```python
except FileNotFoundError:
    # Cannot stat old path on host (container path /data/ not visible here).
    # Do not assume same-device; verify files exist at target before allowing.
    try:
        torrent_files = self.get_torrent_files(torrent_hash)
    except Exception:
        torrent_files = []
    if _files_exist_at_target(torrent_files, new_location):
        print(...)
        skip_device_check = True
    else:
        raise ValueError(...)
```

## Gate Validation

| Gate | Check | Status |
|------|-------|--------|
| 1 | Code review — diff matches fix exactly | ✅ |
| 2 | Syntax check | ✅ |
| 3 | Unit tests — pytest tests/test_qbittorrent.py | ✅ |
| 4 | Spot-check: FNF + files at target → allow; FNF + no files → block | ✅ |
