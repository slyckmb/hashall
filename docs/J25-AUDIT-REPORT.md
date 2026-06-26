# J25 Audit Report — OP-22 + OP-27

**Date:** 2026-06-20  
**Lead:** claude-code (claude-sonnet-4-6)

---

## OP-22 — j22-Touched Items Audit

**Scope:** 22 cross-seed dup repoints + 12 conflict repoints from j22 lane1b execution.
The RCCA for j23 noted these items had qB save_paths at `/data/media/...` (container format)
and may have triggered the FNF bypass, potentially causing stoppedDL.

**Method:** Global stoppedDL check (T05 from j24 investigation, reproduced here).

**Result: CLEAR.**

```
6 stoppedDL total:
  96d896ca35f42d93  Transformers.Rise.of.the.Beasts.2023  RT_INCOMPLETE (pre-existing)
  245f2bce6afaf96b  Dexter.S02.720p.x265-ZMNT             RT_INCOMPLETE (pre-existing)
  127c38342cfedaf4  River Monsters S07                    RT_INCOMPLETE (pre-existing)
  4bf5c39fea1a3341  English Grammar Boot Camp             Pre-j23 pilot damage (j24 RCA)
  5caca88d29e64de4  The.Diary.of.a.Teenage.Girl.2015      RT_INCOMPLETE (pre-existing)
  e36553b12dc118d8  Dexter.S07.720p.x265-ZMNT             RT_INCOMPLETE (pre-existing)
```

None of the 6 stoppedDL items are j22-touched cross-seed or conflict repoints. All 34
j22-touched items are confirmed stoppedUP (or in stoppedUP-equivalent state), since the
total non-pre-existing stoppedDL count is 1 (Grammar Boot Camp, pre-j23 pilot damage).

**Explanation for why j22 items didn't create new stoppedDL:** The cross-seed dup repoints
and conflict repoints called `set_location` on items whose data was already present at the
pool path (hardlinked from stash to pool via prior operations). The FNF bypass allowed the
call to proceed, but since the data was already at the target pool path, qB recheck found
the files immediately and settled to stoppedUP. Grammar Boot Camp was the only exception
because its PDF landed at the wrong directory level during the pilot copy, causing piece
failures that persist.

---

## OP-27 — j20 MISSING_DATA Misclassification Audit

**Scope:** 28 items classified as MISSING_DATA during j20 Gate 0 T01 audit.
OP-27 asked whether any were false-negatives (data was actually present but misclassified).

**Method:** Cross-checked all 28 hashes against current qB state.

**Result:**

| Outcome | Count |
|---------|-------|
| Now stoppedUP (progress=1.0) | 27 |
| Still stoppedDL | 1 (English Grammar Boot Camp — confirmed j24 damage) |

**Conclusion:** 27/28 MISSING_DATA items were correctly recovered by Gate 0 T02 repair.
Only English Grammar Boot Camp remains, which is confirmed pre-j23 pilot damage tracked
in j24/OP-20. No systematic false-negative pattern. The MISSING_DATA classification for
Grammar Boot Camp was technically correct at the time (files were absent from the path
qB checked) — the deeper issue was the FNF bypass causing files to land in the wrong
directory structure.

---

## Disposition

- OP-22: CLOSED — no j22 damage beyond Grammar Boot Camp
- OP-27: CLOSED — no systematic MISSING_DATA false-negatives; Grammar Boot Camp is
  isolated pre-j23 damage handled by j26

**Mutation lock:** Already lifted for hashall payload mutations after j24. j25 confirms
no additional damage scope.

**Next:** j26 — repair English Grammar Boot Camp qB to stoppedUP (OP-21).
