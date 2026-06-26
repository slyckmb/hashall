# Gate 3: Dry-Run + Limited Pilot Results (J11-T02)

**Agent:** opencode (deepseek-v4-flash-free)
**Date:** 2026-06-17
**Head:** `cd5c029a2d0bd3fb3e4ddd6ddff0ff0a70031aac`
**Verdict:** ⚠️ **BLOCKED — Cross-device guard prevents `repoint_qb_to_rt_path` for all HIGH items**

---

## Dry-Run Results (All 4 Items)

### Item 1: `2d4016de` NOVA.S50 (HIGH)
- Action: `repoint_qb_to_rt_path` — clean, proposed qB path `/pool/media/torrents/seeding/DigitalCore (API)`
- Checks: ✅ qb_nohl_tag_present_advisory, ✅ no_arr_library_hardlink_anchor_found
- **Result:** Dry-run clean. Would set qB save path to RT path.

### Item 2: `f0bc85ee` Magic.City.S01 (HIGH)
- Action: `repoint_qb_to_rt_path` — clean, proposed qB path `/pool/media/torrents/seeding/other`
- Checks: ✅ qb_nohl_tag_present_advisory, ✅ no_arr_library_hardlink_anchor_found
- **Result:** Dry-run clean. Would set qB save path to RT path.

### Item 3: `a6d3ae00` The.Rookie.S05 (LOW)
- Action: `manual_review` — blocked by `no_client_on_required_pool_placement`
- **Result:** Correctly blocked as expected. Held for operator review.

### Item 4: `e581c2ac` Lego.Masters.US.S04 (LOW)
- Action: `manual_review` — blocked by same `no_client_on_required_pool_placement` (confirmed via tool error)
- **Result:** Correctly blocked as expected. Held for operator review.

---

## Pilot Execute Results (2 HIGH Items Only)

### `2d4016de` NOVA.S50 — FAILED ✗

```text
ValueError: cross-device setLocation blocked for 2d4016de430ff734:
old path device 49 != new path device 45 (would trigger physical file copy)
```

- **Device 49:** `/data/media/` (stash pool)
- **Device 45:** `/pool/media/` (pool)
- Cross-device guard at `src/hashall/qbittorrent.py:1430` correctly blocked the operation
- No state was mutated — torrent remains fully seeded
- The cross-device check is a read-only guard; no files were moved or copied

### `f0bc85ee` Magic.City.S01 — FAILED ✗

```text
ValueError: cross-device setLocation blocked for f0bc85eedb5050da:
old path device 49 != new path device 45 (would trigger physical file copy)
```

- Same device mismatch (49 → 45)
- Cross-device guard correctly blocked
- No state mutated — torrent fully seeded

---

## Post-State Verification

`make client-drift-audit ANCHOR_SCAN=200000` shows:
- **Drift unchanged:** Same 4 items, same counts (high=2, low=2)
- **No new drift items appeared**
- **No state mutation confirmed** — the cross-device guard prevented all changes
- Both HIGH items still show as `repoint qb to rt path` with no blockers in audit

---

## Finding: Cross-Device Action Classification Gap

### Root Cause

Both HIGH drift items place qB on **stash** (device 49, `/data/media/torrents/seeding/`)
and RT on **pool** (device 45, `/pool/media/torrents/seeding/`). The proposed action
`repoint_qb_to_rt_path` would require qB to physically copy data across devices,
which is correctly blocked by the cross-device guard.

### What This Means

The drift detection correctly identifies the path difference, but the action
classifier (`repoint_qb_to_rt_path`) doesn't account for device boundaries.
When qB data is on a different device than the RT path, `repoint_qb_to_rt_path`
is **never safe** — it would always trigger a full data copy.

### Possible Resolutions (Operator Decision Required)

1. **Accept stash placement for these torrents** — change policy or suppress drift
   for cross-device items where qB is already on stash.

2. **Use `repoint_rt_to_qb_path` instead** — repoint RT to match qB's current stash
   path (no data copy needed). The torrent continues seeding from stash.

3. **Manual re-import** — operator manually re-adds the torrent from pool data
   to qB using the pool path (requires the data to already exist on pool or a
   manual copy).

4. **Extend the classifier** — teach the drift report to detect cross-device
   conditions and either suppress the drift or recommend `repoint_rt_to_qb_path`
   when the data can't be moved.

---

## Recommendation

⛔ **BLOCKED FOR FULL EXECUTION**

The cross-device guard correctly prevents `repoint_qb_to_rt_path` for both HIGH
items. The tooling protected against a destructive data copy. This is not a bug
in the guard — it's working as designed. However, the drift detection/action
classification pipeline has a gap: it recommends `repoint_qb_to_rt_path` even
when qB data is on a different device than the target path.

**Next step:** Operator decides on resolution from the options above. The LOW
items remain unaffected and can proceed after the cross-device classification
issue is resolved for the HIGH items.
