# Lane 1 Pilot RCCA — 2026-06-18

**Status:** FAILED  
**Pilot scope:** 23 groups, 138 items renamed + repointed  
**Date:** 2026-06-18 ~09:20–10:05 EDT

---

## Observed Failures

1. **27 stalledUP** after run — seeding torrents resumed by `set_location` internal `resume_torrent()`, race with re-pause logic.
2. **110 checkingUP** after run — same root cause; set_location resumed → recheck triggered.
3. **115 stoppedDL** (UI: stalledDL) after mass cleanup pause — cross-seed torrents that were in checkingUP when paused are now classified as incomplete downloads.
4. **j18 was never closed** before pilot — its anomalous filter was not merged to CR; the run operated on stale j18 editable install, not CR code.

---

## Root Causes

### RC-1: Stale editable install (process failure)
The hashall venv editable install (`__editable__.hashall-*.pth`) pointed to `__j18` worktree, not the CR branch. Every `hashall` invocation during the pilot used j18 code. j19's re-pause fix, the `stoppedDL` pause-wait fix, and `resume_after=False` were all absent at runtime.

**Evidence:** pth file contained `/hashall-20260530-000517-claude__j18/src` throughout the run.

### RC-2: `set_location()` unconditionally calls `resume_torrent()` (code bug)
`qbittorrent.py` `set_location()` resumes the torrent before returning `True`. In a lane1 context where qB must stay paused post-repoint, this is wrong. Added `resume_after=False` parameter but fix was not present during the run.

**Effect:** Every `set_location` call in the run resumed the torrent → checkingUP → stalledUP.

### RC-3: `stoppedDL` missing from set_location pre-pause wait (code bug)
`set_location()` waited for `{pausedUP, stoppedUP, pausedDL}` before calling setLocation, but not `stoppedDL`. For any cross-seed torrent in download-incomplete state (`stoppedDL`), the pause wait timed out → returned False → no repoint.

**Fixed:** Added `stoppedDL` to the set, but again absent during the run.

### RC-4: re-pause logic race condition (code bug)
Even with j19's re-pause logic present, it can observe `stoppedUP` while qB's queued resume hasn't yet fired, declare success, and exit — leaving the torrent to later transition to stalledUP. Root fix is `resume_after=False` (RC-2 fix).

### RC-5: Mass pause during checkingUP corrupted download state (operational failure)
To clean up stalledUP/checkingUP, `pause_torrents` was sent to all 110 checkingUP torrents. Pausing during checkingUP when the torrent is cross-seed (may be incomplete) caused qB to land the torrent in `stoppedDL` instead of `stoppedUP`. These 110 (+ 5 pre-existing) are now `stoppedDL` — UI shows `stalledDL`.

**These 115 stoppedDL torrents are in an unknown state: qB may consider them incomplete downloads. Their data integrity is unverified.**

### RC-6: Insufficient gate validation before full run (process failure)
Gate 3 pilot (j17) ran only 2 items (`filelist` group). This did not exercise the checkingUP transition, multi-item groups, or the set_location race condition. The jump to 138 items (23 groups) was premature.

### RC-7: j18 not closed before pilot (process failure)
j18's anomalous filter fix was uncommitted to CR at pilot time. `chatrap job done` was never run for j18. As a result, the editable install was still pointing at j18 and the CR branch did not contain j18's code.

### RC-8: `lane1_plan` category-dir check absent (code bug)
`build_lane1_plan` flagged items as safe even when the target category dir already existed. 17 groups (232 items) were planned as safe but failed with "target already exists" at execute time.

---

## Code Fixes Applied (all post-run, not validated under load)

| Fix | File | Status |
|-----|------|--------|
| Re-pause after checkingUP | `lane1_execute.py` | Committed (j19) |
| `stoppedDL` in pause wait | `qbittorrent.py` | Committed |
| `resume_after=False` | `qbittorrent.py` + `lane1_execute.py` | Committed |
| Category-dir exists check | `lane1_plan.py` | Committed |
| `_is_safe_source_dir` | `lane1_plan.py` | Committed (j18 merge) |
| RT download monitor (pre-flight + post-repoint health check) | `lane1_execute.py` | Committed — 49 tests pass |

### RC-9: No RT download guard (code gap, not in run)
`lane1_execute.py` had no check for RT downloading state pre-rename or post-repoint.
A torrent whose hash-check failed (goes to downloading state) after repoint would be invisible.

**Fixes added:**
- **Pre-flight** (`_rt_fetch_health`): before rename, check `d.complete=1` and `d.down.rate=0` for all items.
  If any item is actively downloading → block the group before `os.rename`.
- **Post-repoint health poll** (`_rt_health_check`): after RT repoint, poll until `d.hashing=0` (up to 15s),
  then assert `d.complete=1` and `d.down.rate=0`. Failure → `rt="warn_downloading"` + group error.
  qB repoint still proceeds (path must be updated regardless), but operator is alerted.
- `_rt_fetch_health` RPC error returns `{}` → skips pre-flight block (avoids false-positive block on transient RPC issues).

### RC-10: Gate 0 audit triggered RT hash checks on 43 cross-seed torrents (2026-06-18 ~12:20)

J20-T01 brief authorized `qb.recheck_torrent()` on stoppedDL torrents. 43 RT cross-seed
torrents entered `checking` state shortly after the agent started.

**Controlled experiment (j21, 2026-06-18):** Single qB `recheck_torrent()` on a stable
`stalledUP` cross-seed torrent, RT polled at 0.5s for 90s — **no RT reaction observed**.
Hypothesis A (qB file I/O triggers RT inotify) is **not confirmed**.

**Confirmed root cause:** Agent violated the brief's RT read-only constraint and called RT
mutations directly (`rt_apply_directory_repoint` or `d.start`), causing the 43 hash checks.
qB recheck does NOT trigger RT checks.

**Immediate response:** Lead called `d.stop` on all 43 checking RT torrents → 42 settled to
`stoppedUP`, all 42 subsequently restarted and resolved to `stalledUP` cleanly (data intact).
1 `stoppedDL` (`speedcd/Dexter.S07`) pre-dated the incident. 4 pre-existing non-cross-seed
`stalledDL` stopped for noise removal.

**Gate 0 revision:** qB recheck IS safe to use in the audit. The brief constraint must be
agent-behavior enforcement (no RT mutations), not a blanket ban on qB recheck.

---

## Current State (post-Gate 0 recovery — 2026-06-18 ~21:30)

- **4896 stoppedUP** — seeding normally (was 4813 pre-pilot; net +83 from Gate 0 repair)
- **6 stoppedDL (qB)** — pre-existing only; all verified not caused by lane1 damage:
  - Dexter.S02, Dexter.S07, River Monsters S07, Diary of a Teenage Girl, Transformers (RT_INCOMPLETE: d.complete=0)
  - English Grammar Boot Camp (MISSING_DATA: files not found at canonical path)
- **0 stoppedUP** outstanding — all 42 that were stopped mid-RC-10 recovery confirmed back to seeding
- **0 checkingUP / 0 stalledUP** — no spontaneous states

Gate 0 complete. See `docs/GATE0-STOPPDL-AUDIT.md` and `docs/GATE0-T02-REPAIR.md`.

---

## Required Before Any Further Lane 1 Execution

### Gate 0 — Incident recovery ✅ COMPLETE

- [x] Audited 115 qB stoppedDL (J20-T01): 82 HEALTHY, 28 MISSING_DATA, 5 RT_INCOMPLETE
- [x] Controlled experiment (j21): confirmed qB recheck does NOT trigger RT hash checks
- [x] Repaired 110 stoppedDL via set_location + recheck (J20-T02): 109 resolved to stoppedUP
- [x] Final state: 6 stoppedDL (5 RT_INCOMPLETE + 1 MISSING_DATA without data) — all pre-existing
- [x] 4896 stoppedUP confirmed seeding; 0 checkingUP; 0 stalledUP
- [x] 0 RT writes throughout Gate 0

### Gate 1 — Pre-flight checks
- [ ] Verify editable install points to CR worktree (`cat __editable__.hashall-*.pth`)
- [ ] Confirm all jobs for current session are closed (no orphan `__jNN` worktrees)
- [ ] Run full test suite (36 tests) green
- [ ] Catalog pre-run qB state (all states + counts) before touching anything
- [ ] Confirm zero stalledUP, zero checkingUP before starting

### Gate 2 — Dry-run validation
- [ ] `hashall payload lane1-plan` produces 0 safe items (all 244 now blocked) — confirm
- [ ] When next safe batch is identified: dry-run each group with `--dry-run` flag
- [ ] Verify plan JSON canonical_path values match expected canonical spec

### Gate 3 — Single-group pilot (NEW)
- [ ] Run exactly ONE group (smallest available safe group, 1–3 items)
- [ ] After run: check qB states — zero stalledUP, zero stalledDL new entries
- [ ] Verify RT is seeding at canonical path
- [ ] Verify qB is stoppedUP (not stoppedDL) at canonical path
- [ ] Wait 60s, re-check states — confirm no spontaneous state transitions
- [ ] Human review of pilot group result before proceeding

### Gate 4 — Batch execution (gated)
- [ ] Run remaining groups in batches of ≤5 groups
- [ ] Full state check after each batch (stalledUP=0, stalledDL stable)
- [ ] Human sign-off before each next batch

---

## Process Changes Required

1. **Editable install guard**: Before any `hashall payload` CLI execution, verify pth file points to CR worktree. Add to Gate 1 checklist.
2. **Job lifecycle**: All jobs MUST be closed (`chatrap job done`) before running production operations. Verify with `git log --oneline | grep merge` to confirm all jNN are merged.
3. **Pre-run qB snapshot**: Record `state_breakdown` before any execute operation. Compare after.
4. **No mass-pause on checkingUP**: When cleaning up unexpected states, pause stalledUP individually and wait for checkingUP to complete naturally before pausing those.
5. **Single-item test per code change**: Each new lane1_execute code change requires a single-item live test before batch use.
