# J03-T13 — Tracker Warning: Replace Deleted Items

## Result Summary

- **Total deleted items**: 11
- **Season pack upgrades**: 8 (Euphoria S03E01-E08 → Euphoria US S03 2160p Kitsune)
- **Individual replacements**: 0 (none available)
- **Deleted from RT (no replacement)**: 2 (War Machine 2026, Killers of the Flower Moon)
- **No replacement found (hold)**: 1 (SNL S51E18)
- **Remaining deleted**: 1 (SNL S51E18 — no ep match found on Prowlarr yet)

## Execution

### Step 1: Dry-run
- Ran: `make trk-warn-dry BUCKET=deleted`
- Output saved: `/tmp/trk-warn-dry-j03t13.txt`
- Result: `candidate_upgrade_season_pack=8 delete_rt=2 report_only=1`

### Step 2: Season Pack Upgrades
- Ran: `make trk-warn-upgrade-packs BUCKET=deleted`
- Output saved: `/tmp/trk-warn-upgrade-j03t13.txt`
- Result: `deleted=2 replaced=8 skipped=0`
- 8 Euphoria episodes erased from tracker; season pack added via Prowlarr (Aither)

### Step 3: Individual Replacements
- Skipped — no individual replacements were found by Prowlarr for remaining items.
  - War Machine 2026: no search hits
  - SNL S51E18: on hold, no episode replacement found
  - Killers of the Flower Moon: no search hits

### Step 4: Verification
- Ran: `make trk-warn BUCKET=deleted`
- Result: `[deleted] 1` (only SNL S51E18 remains)

## Artifacts

| Artifact | Value |
|----------|-------|
| dry_run_output | `/tmp/trk-warn-dry-j03t13.txt` |
| pack_upgrades | 6DE6B6D9, 6ABA5D7D, 8AE4283B, FA60C4F5, 1C55FAA7, B60C32B2, 491F271E, CCD12D54 → Euphoria US S03 2160p AMZN WEB-DL DD+ 5.1 Atmos H.265-Kitsune |
| individual_replacements | None |
| no_replacement | 6EB07C0E (War Machine 2026 — no hits), 67DCE701 (Killers of the Flower Moon — no hits), E08FBF38 (SNL S51E18 — hold, no ep replacement) |
| final_tracker_issue_count | `[deleted] 1` |
