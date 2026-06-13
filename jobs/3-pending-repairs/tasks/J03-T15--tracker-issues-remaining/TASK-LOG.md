# J03-T15 — Task Execution Log

## Summary

| Field | Value |
|-------|-------|
| Task | J03-T15 — Remaining RT Tracker Issues |
| Status | ✅ Completed |
| Timestamp | 2026-06-13 09:07 UTC |
| Branch | `cr/hashall-20260530-000517-claude__j03` |

## Results

### Step 1: Dry-run `trk_warn` for `other` bucket

Output: `/tmp/trk-warn-other-dry-j03t15.txt`

| Hash | Title | Indexer | Result |
|------|-------|---------|--------|
| 9e403665 | How.Its.Made.S32.1080p | TorrentLeech | **candidate_replace** (1080p, 73 seeders) |
| 07828500 | Legion.S03.1080p | FileList.io | **delete_rt** (no search hits) |

### Step 2: Execute replacements

Command: `make trk-warn-replace-individual BUCKET=other`
Output: `/tmp/trk-warn-other-replace-j03t15.txt`

**Cleanup: deleted=1 replaced=1 skipped=0**
- **How.Its.Made.S32** → ✅ Replaced with 1080p (TorrentLeech)
- **Legion.S03** → ❌ Deleted from RT (no 1080p replacement on FileList.io)
- No 4K/UHD torrents added

### Step 3: Re-check SNL S51E18 (deleted, previously no replacement)

Hash `e08fbf38bef3a0bb3a7a5a1cc0a3a6aff8898abd` is no longer present in RT (was already cleaned up prior to this task). `trk-warn-dry --hash` returned exit 0 with no output — torrent not found in client.

**Status: still_no_match** — torrent already removed from RT; no replacement was ever found.

### Step 4: Operator actions required

#### OnlyEncodes (4 items) — auth_err "InfoHash not found"
File: `/mnt/config/secrets/trackers/onlyencodes.env`
- Current value: `apiKey="your_api_key_here"` (placeholder — never configured)
- **Action**: Log in to onlyencodes.cc → Account → regenerate API key/passkey → update the file with the real key
- Affected hashes: 61c3c314, 05f8d888, 6d6d0735, 130b442d

#### Nebulance (1 item) — "Passkey not found"
File: `/mnt/config/secrets/trackers/nebulance.env`
- Current value: `apiKey="17d1c0cabc1995f7edcd2adfe090b992"` (real but rejected)
- **Action**: Log in to nebulance.io → regenerate passkey → update the file
- Affected hash: 8f18b392

### Tracker issue count

| Before | Action | After |
|--------|--------|-------|
| 8 total | +1 replaced, +1 deleted from RT, -6 unchanged | **5 remaining** (4 auth_err + 1 passkey) |

## Required artifacts

- step1_dry_run_output: `/tmp/trk-warn-other-dry-j03t15.txt`
- how_its_made_s32_replacement: `found_1080p`
- legion_s03_replacement: `not_found`
- snl_s51e18_status: `still_no_match`
- auth_err_operator_instructions: *documented above — operator must renew credentials for OnlyEncodes and Nebulance*
- tracker_issue_count_after: `5`
