# Tracker Issue Terminology Handoff: hashall

Intended destination:

`/home/michael/dev/work/hashall/docs/tracker-issue-terminology.md`

Source context:

Silo now uses `tracker_issue` for tracker announce problems that are not fatal download errors. The previous `trk_warn` term remains as an output alias in silo `rt-status.sh` so hashall workflows do not break.

## Current local references

`Makefile` defines:

`TRK_WARN_SCRIPT := $(HOME)/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py`

The following make targets call that script:

- tracker warning report
- prowlarr tracker warning report
- dry-run cleanup
- cleanup

These workflows are tied to the docker-side RT tooling, not directly to silo's dashboard filter implementation.

## Recommended terminology

Use `tracker_issue` in new docs and operator-facing text.

Keep `TRK_WARN_SCRIPT` and any `trk_warn` references until the docker-side script and Makefile targets are renamed together. That rename is cosmetic unless output parsing depends on the variable name.

## Compatibility expectations

Silo `rt-status.sh` now emits both:

- `tracker_issue=<n>`
- `trk_warn=<n>`

If hashall parses the status line, prefer `tracker_issue` when present and fall back to `trk_warn`.

If hashall calls `rt-tracker-manual-report.py`, no immediate change is required unless that script's help/output should be renamed.

## Suggested follow-up

After the docker repo mirrors the silo terminology change:

1. Update hashall docs to say `tracker_issue`.
2. Optionally rename `TRK_WARN_SCRIPT` to `TRACKER_ISSUE_SCRIPT`.
3. Keep a compatibility alias in the Makefile for one cycle if any shell snippets use `TRK_WARN_SCRIPT`.
4. Verify the manual report still accepts the same bucket names: `deleted`, `auth_err`, `other`.
