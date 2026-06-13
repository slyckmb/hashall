# Superseded State Guidance

**Archived:** 2026-06-12  
**Reason:** Superseded by `docs/RT-QB-STATE-POLICY.md` which was written after
operator Q&A on 2026-06-12 and corrects the stoppedUP/stalledUP/downloading rules.  
**Key correction:** `stoppedUP` was listed as acceptable in RT — it is NOT.
All RT items must be in an active state (stalledUP, uploading, or a DL state).

---

## Original Target State (from USER-NOTES.md, 2026-05-29)

> ### rTorrent
>
> All items should be actively seeding. The only acceptable non-seeding states
> are 4 stalledDL items that genuinely have zero seeds for their tiny payload
> files (typically season-pack extras like .nfo or sample clips).
>
> Acceptable RT states: stoppedUP, stalledUP, uploading.  
> Unacceptable RT states: stoppedDL, pausedDL, stalledDL (except the 4 known),
> checkingDL (transient, should converge to stoppedUP), downloading (transient).
>
> ### qBittorrent
>
> qB is a passive, silent mirror of RT. It never actively seeds. Every hash in
> RT must also exist in qB with matching progress. All qB items must be in a
> stopped/paused state at all times — after add, during recheck, and after
> recheck. The qB client is kept alive on life support for its tag/category/path
> data, which is the authoritative source for canonical path resolution.
>
> Acceptable qB states: stoppedUP, stoppedDL (only when RT is also incomplete),
> pausedDL (only when RT is also incomplete).  
> Unacceptable qB states: error, downloading, pausedUP, anything not stopped/paused.

---

**See `docs/RT-QB-STATE-POLICY.md` for the corrected authoritative policy.**
