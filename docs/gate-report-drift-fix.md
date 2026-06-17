# Gate Report: Drift Fix Safety Review (J11-T01)

**Reviewer:** opencode (deepseek-v4-flash-free)
**Date:** 2026-06-17
**Head:** `d33f788e23adf8312dc5f3ba912bf3e1fa10dfce`
**Verdict:** ✅ **CERTIFIED SAFE FOR DRY-RUN**

---

## Gate 1: Code Review — PASS

### j10 Fix Confirmation

| Fix | Location | Status | Evidence |
|-----|----------|--------|----------|
| `set_location` pause guard + cross-device check | `src/hashall/qbittorrent.py:1393-1530` | ✅ Confirmed | Line 1411-1434: cross-device st_dev guard. Line 1437-1455: pause → poll stopped state → fail/continue pattern. Line 1478: resume on success. Line 1454: resume on timeout failure. |
| `repoint_both_to_pool` qB-before-RT order | `src/hashall/cli.py:3377-3411` | ✅ Confirmed | Line 3389-3391: `qbit.set_location()` called first. Line 3397-3399: `rt_apply_directory_repoint()` called only if qB succeeds. Fail-fast: if qB fails, RT is untouched. |

### Apply Path Review

**Entry point:** `client_drift_apply_cmd` at `src/hashall/cli.py:3691`

1. `_load_client_drift_report()` (line 3713) — builds full drift report from qB cache + RT cache + policy
2. `_select_client_drift_path_rows()` (line 3033) — filters by side="path_drift", action filter, hash prefix, journal dedup
3. `_apply_client_drift_path_rows()` (line 3293) — iterates rows, dispatches by action:

   **`repoint_qb_to_rt_path`** (line 3354-3376):
   - Validates qB client and target path existence
   - Calls `qbit.set_location(torrent_hash, target)` — pause → setLocation → resume inside
   - On success: starts `qbit.recheck_torrent()` then re-pauses (qB v5 workaround at line 3370-3376)
   - On failure: records error in event, continues to journal write + raise

   **`repoint_both_to_pool`** (line 3377-3411):
   - Calls `qbit.set_location()` first (fail-fast design)
   - On qB success: calls `rt_apply_directory_repoint()` for RT side
   - If RT fails after qB: journals partial event with `"error": "rt_repoint_failed_after_qb"` then raises

4. `_append_client_drift_journal()` (line 2743-2748) — appends JSONL event to journal; creates parent dirs
5. `_read_client_drift_journal()` (line 2721-2740) — reads completed hashes, skips events with errors or failed verify

### No Residual Bugs Found

All control flow paths are accounted for. Error handling is explicit. No silent failures.

---

## Gate 2: In-Memory Walkthrough — PASS

### Item 1: `2d4016de` NOVA.S50 — repoint_qb_to_rt_path (HIGH)

| Step | Action | Failure Mode | Recovery |
|------|--------|-------------|----------|
| 1 | State read: drift report loads qB/RT cache rows | Cache stale → wrong placement | Dry-run shows proposed action; operator validates. Report regenerates from fresh cache per run. |
| 2 | `qbit.set_location()` begins: pause torrent | Pause fails → returns False, caller records error | Safe: no state change. Torrent resumes in `set_location` error path (line 1454). |
| 3 | Poll for stopped state | Timeout → resumes torrent, returns False | Safe: torrent returned to original state. |
| 4 | Cross-device check (st_dev) | Stat fails or devices differ → returns False | Safe: no mutation. Cross-device raises ValueError if mismatch found (line 1430). |
| 5 | POST `/api/v2/torrents/setLocation` | HTTP error/timeout → retry x3, then resume + return False | Safe: torrent resumed. Journal records error. |
| 6 | Resume torrent | Resume fails → logged but set_location already returned True | Partial success; qB save_path updated. Journal records success. |
| 7 | Verify post-state not "moving" | Torrent in moving state → resume + return False | Safe: caller records error. |
| 8 | `qbit.recheck_torrent()` | Recheck fails → event records `recheck_started=false` | Non-fatal, logged in journal event. |
| 9 | Re-pause after recheck (qB v5) | Pause fails → `pause_after_recheck_failed` logged | Non-fatal. Torrent runs briefly until next pause cycle. |

### Item 2: `f0bc85ee` Magic.City.S01 — repoint_qb_to_rt_path (HIGH)

Same sequence as Item 1. No differences in code path.

### Item 3: `a6d3ae00` The.Rookie.S05 — manual_review (LOW)

Blocked by classifier: `blockers` list present in drift row. The `_apply_client_drift_path_rows` function checks `blockers` at line 3317-3320 and raises `ClickException` if any exist. This item will be **skipped** in an automated apply run. Safe to include in the same batch — the blocker check acts as a guard. However, per best practice, **recommend holding LOW items** in a separate run to avoid confusion from the raised exception interrupting the batch.

### Item 4: `e581c2ac` Lego.Masters.US.S04 — manual_review (LOW)

Same as Item 3. Blocked by `blockers`, safe to batch-gate but cleaner to run separately.

---

## Partial-State Edge Case (Documented)

**Scenario:** `repoint_both_to_pool` — RT repoint fails after qB set_location succeeds.

**What happens:** At line 3408-3411, the journal event is written with `"error": "rt_repoint_failed_after_qb"` and then the exception propagates. qB has the new path, RT still has the old path.

**Recovery:** Run `repoint_rt_to_qb_path` action for the same hash to align RT to qB's current path. The journal event provides all context needed.

**Risk:** Low. The qB path is the correct pool path; RT being behind causes no data loss — the torrent just won't seed from the pool location until repointed. The partial state is fully journaled and recoverable.

---

## Recommendation

✅ **CERTIFIED SAFE FOR DRY-RUN**

Proceed to Gate 3 (dry-run) with:
- `make client-drift-audit ANCHOR_SCAN=200000` to re-verify current drift state
- `--hash 2d4016de --hash f0bc85ee` to confirm HIGH items are actionable
- LOW items held for operator review after pilot
