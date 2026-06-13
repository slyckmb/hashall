# J03-T18 — trk-warn vs rt-status gap assessment

## Status: ✅ Completed 2026-06-13

## Findings

- **gap**: 4 items (rt-status=6, trk-warn=2)
- **cause**: BUCKET_PATTERNS auth_err regex requires `"Invalid InfoHash"` but 4 OnlyEncodes items have message `"InfoHash not found"` (no "Invalid") — rt-cache-summary uses plain `infohash` so it catches them; trk-warn did not
- **include_incomplete**: no — gap was not a complete=0 issue; all 4 items are complete=1 but fail the regex
- **fix**: add plain `InfoHash` to auth_err regex in rt-tracker-manual-report.py line 64 → assigned to T19
