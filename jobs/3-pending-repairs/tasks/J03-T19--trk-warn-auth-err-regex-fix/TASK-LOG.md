# J03-T19 — trk-warn: fix auth_err regex

## Status: ✅ Completed 2026-06-13

## Changes

- File: `~/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py`
- Version: v1.9.1 → v1.9.2
- Regex: `Invalid InfoHash` → `InfoHash` in BUCKET_PATTERNS auth_err pattern
- Branch: `cr/docker-20260613-095239`
- Commit: `8e7c1bb` (note: also appears as `70ae75d` on that branch)

## Verification

- py_compile: pass
- smoke test: `[auth_err] 5` (4 OnlyEncodes + 1 Nebulance) — matches rt-status panel
