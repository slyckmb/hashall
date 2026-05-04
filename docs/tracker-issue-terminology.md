# Tracker Issue Terminology

Silo uses `tracker_issue` for tracker announce problems that are not fatal download errors.
The previous term `trk_warn` remains as an output alias in silo `rt-status.sh` for backwards compatibility.

## Hashall usage

`TRK_WARN_SCRIPT` in the Makefile points to the docker-side report script:

```make
TRK_WARN_SCRIPT := $(HOME)/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
```

Keep this variable and any `trk_warn` Makefile targets as-is until the docker repo mirrors the rename.
That rename is cosmetic unless output parsing depends on the variable name.

## Parsing rt-status output

Silo `rt-status.sh` emits both fields:

```
tracker_issue=<n>
trk_warn=<n>
```

If hashall parses the status line, prefer `tracker_issue` when present and fall back to `trk_warn`.

## Follow-up (after docker repo rename)

1. Rename `TRK_WARN_SCRIPT` → `TRACKER_ISSUE_SCRIPT` in Makefile.
2. Keep a compatibility alias for one cycle if any shell snippets use the old name.
3. Verify the manual report script still accepts the same bucket names: `deleted`, `auth_err`, `other`.
