# R5: rt-tracker-manual-report.py Cleanup/Execute Flow Audit

**Date:** 2026-06-17
**Task:** J09-T05
**Scope:** Cold-read audit of `rt-tracker-manual-report.py` v1.9.6 cleanup/execute flow, Prowlarr integration, snapshot/erase-guard integration
**Target:** `/home/michael/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py` (1770 lines)

---

## Question 1: Other action types with exec-block/pre-check divergence?

**Finding:** No divergence found for `candidate_replace` or `candidate_upgrade_season_pack`.

Both use the same URL source in pre-check and execution:
- `candidate_replace`: checks `prowlarr.best_download_url` at line 1211, uses same at line 1373 ✓
- `candidate_upgrade_season_pack`: checks `season_upgrade.best_download_url` at line 1218, uses same at line 1267 ✓

The `candidate_replace_individual` was the only one with this divergence, fixed by the escalation fallback at both pre-check (lines 1222-1233) and execution (lines 1319-1327).

However, a related asymmetry was found in the **auth_err hash-recheck** logic (see Bug #1 below).

---

## Question 2: Snapshot before all erases?

**Finding:** Yes — `snapshot_before_cleanup` at line 1196 captures ALL candidate hashes upfront in a single `rt-erase-guard.py snapshot` call, before any `d.erase()`.

Items that fail `live_row_matches` (line 1203) are skipped from erase but remain in the snapshot. This is a false positive in the snapshot but harmless — the restore operation simply skips hashes already present in RT.

---

## Question 3: qB mirror sync atomic with RT erase?

**Finding:** No — RT erase always happens before qB operations, with no rollback mechanism.

Per action type:
- **delete_rt** (lines 1252-1262): RT erase → qB delete. If qB delete fails, RT is already erased. The error is recorded in `deleted_entry["qb_error"]` but there is no retry or rollback.
- **candidate_replace** (lines 1429-1441): RT load → qB delete old → qB add new. If qB add fails, the new torrent is in RT but not in qB (recorded in `replaced_entry["qb_add_error"]`).
- **candidate_replace_individual** (lines 1342-1367): Same pattern as candidate_replace.
- **candidate_upgrade_season_pack** (lines 1281-1315): RT erase → qB delete individual ep → fetch season pack → RT load pack. If the fetch/load fails, the individual ep is erased from RT AND deleted from qB, but the season pack was never added. See Bug #3.

---

## Question 4: Prowlarr download URLs cached or re-fetched?

**Finding:** Cached. `best_download_url` is stored at search time (from `summarize_prowlarr_hits` via Prowlarr `downloadUrl`) and used at execution time without re-querying.

Prowlarr `downloadUrl` values are ephemeral signed URLs that may expire between `--prowlarr` scan and `--cleanup` execution. The script has no retry or re-search mechanism if the URL has expired. This affects all replacement action types. See Bug #5.

---

## Question 5: Does --dryrun prevent ALL side effects?

**Finding:** Yes for mutations. No for read-only network activity.

- `do_cleanup = bool(args.cleanup and not args.dryrun)` — guarded ✓
- `do_restart_conn_err = bool(args.restart_conn_err and not args.dryrun)` — guarded ✓
- `do_fix_multi_loc = bool(args.fix_multi_loc and not args.dryrun)` — guarded ✓
- `qb_client` is only instantiated inside `if do_cleanup and args.qb_sync` — guarded ✓
- Prowlarr search runs (read-only HTTP requests to Prowlarr API) — expected for display purposes, no mutation ✓
- `annotate_actions` is CPU-only — no side effects ✓

---

## Bug #1 — Medium: `candidate_replace_individual` for auth_err items lacks hash-diff recheck

**File:** `rt-tracker-manual-report.py:1348-1355`
**Severity:** Medium

### Description

The `candidate_replace` path (lines 1391-1419) includes an auth_err optimization: it snapshots RT hashes before `rt_load_torrent`, diffs after to find the new hash, and triggers `d.check_hash()` to force immediate recheck. The `candidate_replace_individual` path (lines 1348-1355) does NOT do this.

This matters because `plan_action` can assign `candidate_replace_individual` to auth_err items (escalation-hit path at lines 772-773, 780-781). When a torrent is loaded with a different passkey/announce URL (common for auth_err fixes), the new hash may have a different info_hash that RT will not automatically recheck. Without the hash-diff → `d.check_hash()` call, the new torrent stays in an unverified state until the next RT restart or manual action.

### Reproduction

1. An auth_err item has 0 same-tracker hits but escalation finds a hit on another tracker
2. `plan_action` returns `candidate_replace_individual` with reason `auth_err_escalation_hit`
3. In `cleanup_rows`, the item is erased (line 1247), then the individual replacement is loaded (lines 1348-1355)
4. The new torrent has a different info_hash (different tracker = different passkey/announce)
5. No `d.check_hash()` is called on the new hash — it stays unchecked until next restart

### Proposed fix

Add hash-before/hash-after diff logic (same pattern as lines 1391-1419) to the `candidate_replace_individual` execution path, gated on `row["bucket"] == "auth_err"`:

```python
hashes_before: set[str] = set()
if row["bucket"] == "auth_err":
    try:
        hashes_before = {str(r[0]).lower() for r in client.d.multicall2("", "main", "d.hash=") if isinstance(r, list) and r}
    except Exception:
        pass

torrent_bytes = fetch_torrent_bytes_from_prowlarr(...)
rt_load_torrent(torrent_bytes, save_path, arr_label)

if row["bucket"] == "auth_err" and hashes_before:
    import time as _time
    _time.sleep(1.5)
    hashes_after = {str(r[0]).lower() for r in client.d.multicall2("", "main", "d.hash=") if isinstance(r, list) and r}
    new_hashes = hashes_after - hashes_before
    for new_h in new_hashes:
        try:
            client.d.check_hash(new_h)
        except Exception:
            pass
```

---

## Bug #2 — Medium: `deleted`/`other` bucket in `plan_action` ignores escalation hits when no fallback patterns match

**File:** `rt-tracker-manual-report.py:741-760`
**Severity:** Medium

### Description

The `plan_action` function for `deleted`/`other` buckets checks fallback patterns in order:

1. `individual_ep_replacement` → `candidate_replace_individual`
2. `hold_wait_for_ep` → checks escalation hits (known fix #2) → `candidate_replace_individual` or hold
3. `season_upgrade` → `candidate_upgrade_season_pack`
4. **Falls to `delete_rt`**

If escalation found hits but NONE of the above flags are set (e.g., the item is a movie, not an episode, so no episode-search flags fire), the escalation is silently ignored and the item is marked for deletion. The escalation search already proved the content exists on another tracker — this should be a replacement candidate.

Compare with the `auth_err` path (lines 768-782) which checks `escalation` at two levels (error path and no-hits path) and correctly routes to `candidate_replace_individual`.

### Reproduction

1. A deleted movie has 0 same-tracker Prowlarr hits and is not an episode (no `individual_ep_replacement`, `hold_wait_for_ep`, or `season_upgrade`)
2. Escalation search finds a hit on a different tracker (`escalation.stage` = 2 or 3, `escalation.hits` non-empty)
3. `plan_action` returns `delete_rt` — the escalation hit is never used
4. The item is erased without attempting a replacement

### Proposed fix

After the season_upgrade check and before the `delete_rt` fallthrough, add an escalation-hit check:

```python
if prowlarr.get("escalation"):
    esc = prowlarr.get("escalation") or {}
    if esc.get("hits"):
        return "candidate_replace_individual", "deleted_found_via_escalation"
```

This would route the item to replacement via `candidate_replace_individual`, using `escalation.summary.best_download_url` (the exec block fallback at lines 1319-1327 already handles this URL source).

---

## Bug #3 — Medium: `candidate_upgrade_season_pack` erases individual from RT+qB before confirming season pack download

**File:** `rt-tracker-manual-report.py:1264-1316`
**Severity:** Medium

### Description

The `candidate_upgrade_season_pack` execution flow is:

1. RT `d.erase(row["hash"])` at line 1247 (shared erase for all actions)
2. qB `delete_torrent(row["hash"])` at lines 1282-1287 (individual ep removed from qB)
3. `fetch_torrent_bytes_from_prowlarr(dl_url)` at lines 1291-1297
4. `rt_load_torrent(torrent_bytes)` at line 1305 (season pack added to RT)

If step 3 fails (expired Prowlarr URL, network error, etc.), the individual episode is already gone from RT (step 1) and qB (step 2), but the replacement season pack was never added. The error is recorded in `upgraded_entry["season_pack_error"]` but the data is already lost.

Recovery is theoretically possible via the snapshot (taken at line 1196), but this requires operator intervention — it's a silent data loss window.

### Reproduction

1. A deleted episode has a season pack upgrade available with `candidate_upgrade_season_pack` action
2. `--cleanup --upgrade-season-packs` is run
3. RT erase succeeds (line 1247), qB delete succeeds (line 1284)
4. `fetch_torrent_bytes_from_prowlarr` fails — Prowlarr URL expired or indexer down
5. The individual episode is gone from both RT and qB. No season pack was added.

### Proposed fix

Reorder the operations so the season pack is fetched BEFORE erasing the individual episode. If the fetch fails, the individual episode is preserved:

```python
# In the pre-check or before erase: fetch season pack first
try:
    torrent_bytes = fetch_torrent_bytes_from_prowlarr(...)
except Exception as exc:
    payload["skipped"].append({"hash": row["hash"], "reason": f"season_pack_fetch_failed:{exc}"})
    continue

# Then proceed with erase (shared erase at lines 1237-1250)
# Then qB delete + RT load
```

This requires moving the shared erase (lines 1237-1250) inside each action branch for `candidate_upgrade_season_pack`, or adding a pre-fetch before the erase.

---

## Bug #4 — Low-Medium: Prowlarr download URLs fetched at search time can expire by cleanup time

**File:** `rt-tracker-manual-report.py:999-1011` (fetch_torrent_bytes_from_prowlarr), all call sites
**Severity:** Low-Medium

### Description

Prowlarr `downloadUrl` values are ephemeral signed URLs. They are fetched during `augment_rows_with_prowlarr` (search time) and stored in `row["prowlarr"]` without the source data needed to re-search. When `--cleanup` executes later (potentially minutes to hours after the prowlarr scan), `fetch_torrent_bytes_from_prowlarr` attempts to use the same URL — which may have expired.

There is no retry or automatic re-search. A failed URL fetch causes the item to be skipped (recorded as `replace_failed:ExpiredURL` or similar). The item was already erased from RT by that point.

This affects all replacement action types:
- `candidate_replace` (line 1375)
- `candidate_replace_individual` (line 1349)
- `candidate_upgrade_season_pack` (line 1292)

### Reproduction

1. Run `--prowlarr --cleanup --bucket deleted` on a batch of 20 items
2. The prowlarr scan fetches URLs for all 20 (takes ~10-15 seconds per item)
3. By the time cleanup reaches item #15, the earliest URLs may be 3+ minutes old
4. Prowlarr signed URLs have short TTLs (often 1-5 minutes depending on indexer)
5. Items 15-20 fail with `fetch_torrent_bytes_from_prowlarr` exceptions

### Proposed fix

Add a re-search fallback in `fetch_torrent_bytes_from_prowlarr` or at each replacement site: when the cached download URL fails, re-run the Prowlarr search for the same query to get a fresh URL, then retry the fetch.

---

## Bug #5 — Low: `candidate_upgrade_season_pack` does not sync to qB synchronously

**File:** `rt-tracker-manual-report.py:1299-1304`
**Severity:** Low

### Description

`candidate_replace` and `candidate_replace_individual` both add the replacement torrent to qB inline (lines 1435-1441, 1357-1365). `candidate_upgrade_season_pack` defers qB sync to an RT completion hook (`rt_qb_mirror_enqueue.sh`).

If the completion hook is not installed, fails, or the operator doesn't run `make rt-qb-mirror-queue-apply`, the qB mirror will be out of sync: the season pack is in RT but not in qB, while the old individual episode was already deleted from qB (line 1282-1287).

### Proposed fix

Add synchronous qB sync for season packs, same pattern as `candidate_replace`:

```python
if qb_client is not None:
    try:
        result = qb_client.add_torrent(
            torrent_bytes, save_path, label if label != "-" else "",
            paused=False, skip_checking=True,
        )
        upgraded_entry["qb_add_result"] = result
    except Exception as exc:
        upgraded_entry["qb_add_error"] = str(exc)
```

---

## Bug #6 — Low: `_escalating_search` 4K quality filter may block valid replacements

**File:** `rt-tracker-manual-report.py:508`
**Severity:** Low

### Description

The escalation search filters out 4K/UHD/HDR/DV content:

```python
hits = [h for h in hits if not re.search(r"2160p|UHD|HDR\b|\.DV\b", h.get("title", ""), re.I)]
```

The `HDR\b` pattern matches "HDR10", "HDR10+", "HDR" etc. The `\.DV\b` pattern uses a literal dot which in a title may be a space or other separator. This means HDR10 and DV content is filtered from ALL escalation searches, which is appropriate for the quality policy of a 1080p SDR library.

However, this is applied to ALL escalation stages, including stage 4 (all indexers). If the only available hit for a given episode is an HDR version, it won't appear in escalation results, and the episode gets deleted instead of replaced with the closest available match.

This is arguably a policy choice, not a bug — flagged as a note for operator awareness.

---

## Bug #7 — Low: `fix_multi_loc` still_erroring check uses fragile 401 substring match

**File:** `rt-tracker-manual-report.py:1168`
**Severity:** Low

### Description

The still_erroring detection at line 1168:

```python
if new_msg and "more than" in new_msg.lower() and "401" in new_msg:
    payload["still_erroring"].append(...)
```

A different tracker error message containing "401" (e.g., a 401 Unauthorized or HTTP 401 reference) would falsely flag the item as still-erroring even if the multi_loc condition actually cleared. Similarly, if the multi_loc message persists but doesn't contain "401" (which it normally does), the item would be falsely reported as cleared.

### Proposed fix

Use a more specific pattern — ideally the full multi_loc regex match or check against the original `MULTI_LOC_PATTERN`:

```python
if new_msg and re.search(r"more than \d+ locations.*401", new_msg, re.I):
```

---

## Bug #8 — Info: RT metadata fetched at line 1235 may be stale by time of use

**File:** `rt-tracker-manual-report.py:1235` (rt_get_torrent_meta) vs lines 1268-1333 (usage)
**Severity:** Info

### Description

`rt_get_torrent_meta` is called at line 1235 (after pre-checks pass, before `stop/close/erase`). The metadata (directory, label, base_path, name) is captured here and used later in each action-specific execution branch (lines 1268-1333). Between capture and use, `client.d.stop()` (1237), `client.d.close()` (1241), and `client.d.erase()` (1247) run.

While `d.stop()` and `d.close()` should not modify the label or directory, `d.erase()` removes the torrent entirely. After erase, reading `meta_before` values is fine since they were captured before. However, there is a tiny window where:
- An external process changes the label or directory between `rt_get_torrent_meta` and `stop/close/erase`
- The replacement uses stale path/label data

In practice this is extremely unlikely and the metadata fields are stable once a torrent is complete. Flagged as an informational observation.

---

## Summary

| # | Severity | Location | Description |
|---|----------|----------|-------------|
| 1 | **Medium** | lines 1348-1355 | `candidate_replace_individual` for auth_err items lacks hash-diff recheck (same optimization as `candidate_replace` at 1391-1419) |
| 2 | **Medium** | lines 741-760 | `deleted`/`other` `plan_action` path ignores escalation hits when no fallback patterns match (delete instead of replace) |
| 3 | **Medium** | lines 1264-1316 | `candidate_upgrade_season_pack` erases individual from RT+qB before confirming season pack download — data loss window |
| 4 | **Low-Med** | all replacement sites | Prowlarr ephemeral download URLs fetched at search time, not re-fetched at execution — can expire between scan and cleanup |
| 5 | **Low** | lines 1299-1304 | `candidate_upgrade_season_pack` defers qB sync to RT completion hook (async) — mirror can get out of sync |
| 6 | **Low** | line 508 | 4K/HDR filter in `_escalating_search` may block the only available replacement hit |
| 7 | **Low** | line 1168 | `fix_multi_loc` still_erroring check uses fragile "401" substring — potential false positive/negative |
| 8 | **Info** | line 1235 vs 1268-1333 | RT metadata snapshot may be stale by execution time (theoretical) |

## Known fixed bugs (not re-reported)

These 3 fixes from v1.9.6 (commit 940f5e9) were confirmed present and correct:
1. `auth_err` escalation check in `plan_action` (lines 769-781) ✓
2. `hold_wait_for_ep` escalation fallback (lines 749-753) ✓
3. `candidate_replace_individual` exec block escalation fallback (lines 1318-1323) ✓

The escalation mechanism works correctly where it was installed — the gaps are in paths where it was NOT installed (Bug #2) or where a different optimization was missed (Bug #1).
