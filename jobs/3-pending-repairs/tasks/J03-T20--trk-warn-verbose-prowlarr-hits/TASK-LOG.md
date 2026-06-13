# J03-T20 — trk-warn: verbose prowlarr hits

## Summary

- **File**: `~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py`
- **Version**: v1.9.2 → v1.9.3
- **Branch**: `cr/docker-20260613-095239`
- **Commit**: `e68e636`

## Changes

1. Added `--verbose-prowlarr` flag that auto-enables `--prowlarr`
2. Added `_annotate_skip_reason()` function for hit exclusion annotation
3. Stored `all_hits_raw` and `all_hits_count` in summary dict
4. Added annotated hit list output in `print_text()` when `verbose_prowlarr=True`
5. Bumped version from v1.9.2 to v1.9.3

## Verification

- `python3 -m py_compile` → ok
- `--bucket deleted --verbose-prowlarr` smoke test → runs clean, shows `all_hits (0 total, 0 same-tracker):` header
