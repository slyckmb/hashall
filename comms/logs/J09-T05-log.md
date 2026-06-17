# J09-T05: Cold-read audit of rt-tracker-manual-report.py cleanup/execute flow

**Status:** done
**Task type:** discovery
**Branch:** cr/hashall-20260530-000517-claude__j09
**Head:** f1e1545808f78900e02438091962902f85a6dae3

## File audited

- `/home/michael/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py` (1770 lines, v1.9.6) — full read
- `/home/michael/dev/sys/docker/gluetun_qbit/bin/rt-erase-guard.py` (348 lines, v1.0.0) — snapshot/restore mechanism

## Audit scope

- cleanup_rows (lines 1176-1445): pre-check, erase, action-specific execution
- augment_rows_with_prowlarr (lines 517-674): Prowlarr search integration
- _escalating_search (lines 480-514): tiered escalation search
- snapshot_before_cleanup (lines 1097-1103): rt-erase-guard integration
- plan_action (lines 727-789): action assignment logic
- main() (lines 1448-1766): CLI flag handling, dryrun guard, qB client init

## Answers to specific questions

1. **Other action types with exec-block divergence?** No — `candidate_replace` and `candidate_upgrade_season_pack` use consistent URL sources in pre-check and execution. `candidate_replace_individual` was the only divergent one (fixed).

2. **Snapshot before all erases?** Yes — `snapshot_before_cleanup` captures all hashes upfront at line 1196. Items skipped by `live_row_matches` remain in snapshot (false positive, harmless).

3. **qB sync atomic with RT erase?** No — RT erase happens before any qB operation. No rollback mechanism for any action type.

4. **Prowlarr URLs cached or re-fetched?** Cached. `best_download_url` is set at search time; ephemeral Prowlarr signed URLs may expire by execution time. No re-search fallback.

5. **--dryrun prevents mutations?** Yes — all mutation paths are guarded by `not args.dryrun`. Prowlarr read-only HTTP requests still fire (expected for display). No QB client is created.

## Findings summary

| # | Severity | File:Line | Brief |
|---|----------|-----------|-------|
| 1 | **Medium** | :1348-1355 | `candidate_replace_individual` for auth_err items lacks hash-diff recheck (candidate_replace has it at :1391-1419) |
| 2 | **Medium** | :741-760 | `deleted`/`other` plan_action ignores escalation hits when no episode/season fallback matches — item deleted instead of replaced |
| 3 | **Medium** | :1264-1316 | `candidate_upgrade_season_pack` erases individual from RT+qB before confirming season pack download — data loss window |
| 4 | **Low-Med** | all replace sites | Prowlarr ephemeral download URLs fetched at search time, not re-fetched — can expire between scan and cleanup |
| 5 | **Low** | :1299-1304 | `candidate_upgrade_season_pack` defers qB sync to RT completion hook (async) — mirror can get out of sync |
| 6 | **Low** | :508 | 4K/HDR quality filter in _escalating_search may block the only available replacement hit |
| 7 | **Low** | :1168 | fix_multi_loc still_erroring check uses fragile "401" substring match |
| 8 | **Info** | :1235 v :1268 | RT metadata snapshot at pre-check time may be stale by execution time (theoretical) |

## Known fixed bugs (confirmed present, not re-reported)

1. auth_err escalation check in plan_action (:769-781) ✓
2. hold_wait_for_ep escalation fallback (:749-753) ✓
3. candidate_replace_individual exec block escalation fallback (:1318-1323) ✓

## Artifacts produced

- `docs/review/R5-rt-tracker-report-findings.md` (committed)
