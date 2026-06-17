# Gate 3 (Re-Run): Cross-Device Guard Refinement Pilot

**Agent:** opencode (deepseek-v4-flash-free)
**Date:** 2026-06-17
**Head:** `a276bc8`
**Verdict:** ✅ **CERTIFIED SAFE FOR FULL EXECUTION**

---

## Summary

Cross-device guard refined in `set_location` (`src/hashall/qbittorrent.py`): before
blocking on `st_dev` mismatch, the guard now checks whether torrent files already
exist at the target path on disk. If they do, `set_location` proceeds (qB only
updates metadata — no physical copy). If not, the original `ValueError` is raised.

All 5 new tests pass alongside 23 existing tests (28/28).

---

## Pilot Execution

### Item 1: `2d4016de` NOVA.S50 (HIGH)

| Phase | Result |
|---|---|
| Dry-run | ✅ Clean — repoint_qb_to_rt_path to `/pool/media/torrents/seeding/DigitalCore (API)` |
| Execute | ✅ Passed — bypass message: "files exist at target (metadata-only update)" |
| Post-state | ✅ Gone from drift report |

### Item 2: `f0bc85ee` Magic.City.S01 (HIGH)

| Phase | Result |
|---|---|
| Dry-run | ✅ Clean — repoint_qb_to_rt_path to `/pool/media/torrents/seeding/other` |
| Execute | ✅ Passed — bypass message: "files exist at target (metadata-only update)" |
| Post-state | ✅ Gone from drift report |

### Post-State Audit

```
Path drift: 2  high=0  medium=0  low=2
```
Both remaining items are LOW (manual_review, held for operator).
Neither HIGH item appears in the drift report.
No new drift items were created.
No file count or size anomalies detected.

### Journal

Both operations recorded cleanly in `out/client-drift/apply.jsonl`:

```json
{"hash": "2d4016de...", "status": "ok", "recheck_started": true, "save_path": "/pool/media/..."}
{"hash": "f0bc85ee...", "status": "ok", "recheck_started": true, "save_path": "/pool/media/..."}
```

---

## Recommendation

✅ **CERTIFIED SAFE FOR FULL EXECUTION**

The cross-device guard now correctly:
1. Blocks cross-device moves where files don't exist at target (no data copy)
2. Allows cross-device moves where files exist at target (metadata-only update)

The 2 LOW drift items (`a6d3ae00`, `e581c2ac`) remain held for operator review
as they require manual intervention (`no_client_on_required_pool_placement`).
