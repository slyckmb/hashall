---
id: J03-T07
job: 3-pending-repairs
slug: state-policy-doc-audit
task_type: discovery
status: done
brief_revision_id: 1
created_by: lead
agent_start_timestamp: 2026-06-12T17:00:00Z
completed_at: 2026-06-12T17:45:00Z
brief_freeze_violation: "false"
---

# TASK-LOG: J03-T07 — RT/qB State Policy Doc Audit

## Summary

```
🟪 task-log=J03-T07_state-policy-doc-audit 🟪

status="done"
task_id="J03-T07"
task_type="discovery"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="All listed docs scanned; 5 categories reported; 24 total findings across contradictions, gaps, and stale data."
artifacts="findings below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none"
next="future TBD by lead after current task log"

docs_scanned=18
findings_contradictions=5
findings_gaps_in_existing=4
findings_gaps_in_policy=6
findings_code_mismatches=6
findings_stale=5
```

## Documents Scanned

Primary:
- `docs/RT-QB-STATE-POLICY.md` — new authoritative policy (236 lines)
- `docs/USER-NOTES.md` — original operator target state (69 lines)
- `docs/REQUIREMENTS.md` — product requirements (v1.6, last 2026-05-19)
- `docs/RUNBOOK.md` — operational procedures (340 lines, last 2026-05-26)
- `docs/SPRINT.md` — current sprint state (439 lines, last 2026-05-26)
- `docs/BACKLOG.md` — known gaps (232 lines, last 2026-05-20)
- `docs/RECOVERY.md` — recovery procedures (60 lines, last 2026-05-08)
- `docs/ARCHITECTURE.md` — system architecture (65 lines, last 2026-05-19)
- `docs/operations/RUN-STATE.md` — live evidence baseline (375 lines, last 2026-05-19)

Secondary:
- `docs/ops-log.md` — chronological ops history (465 lines, entries from March 2026)
- `docs/REFRESH_GUIDE.md` — refresh profiles reference (144 lines)
- `docs/archive/SUPERSEDED-STATE-GUIDANCE-2026-06-12.md` — archived old state guidance
- `docs/hashall-from-silo--downstream-tracker-issue-notes.md` — tracker issue notes
- `docs/tracker-issue-terminology.md` — tracker terminology
- `docs/hashall-answers-4questions.md`, `hashall-answers-3-4-10.md`, `hashall-answers-0418-1121.md`

Code:
- `src/hashall/path_normalize.py` — state classification functions
- `src/hashall/qb_repair_payload_group.py` — BROKEN_EXPECTED_STATES, GOOD_DONOR_STATES, GOOD_SEED_STATES
- `src/rehome/auto.py` — SEED_READY, `_is_qb_ready_state()`
- `src/rehome/cli.py` — `good_states` / `alarm_states` in `_print_post_apply_summary()`
- `src/hashall/cli.py` — `rt state-audit --bad-only` filter

---

## CATEGORY 1 — CONTRADICTIONS

### C1 — `path_normalize.py:_BAD_QB_STATES` dramatically under-inclusive vs policy

**Document:** `src/hashall/path_normalize.py:29`
**What it says:**
```python
_BAD_QB_STATES = {"error", "missingfiles"}
```
**What policy says:** qB must stop immediately for uploading, stalledUP, forcedUP, pausedUP, downloading. These are all violations requiring action, yet none appear in `_BAD_QB_STATES`.
**Assessment:** `_BAD_QB_STATES` should include all states the policy considers unacceptable. Currently only 2 of 7 unacceptable states are flagged. This means any code using `is_qb_bad_terminal_state()` (called from `path_normalize.py:83`, `hitchhiker.py`, etc.) will silently accept uploading/stalledUP/forcedUP/pausedUP/downloading qB items as non-bad.
**Severity:** HIGH — affects drift normalization and hitchhiker audit logic.

### C2 — `path_normalize.py:_BAD_RT_STATES` only flags "error"

**Document:** `src/hashall/path_normalize.py:30`
**What it says:**
```python
_BAD_RT_STATES = {"error"}
```
**What policy says:** stoppedUP, stoppedDL, pausedDL, and downloading (cross-seed) are all unacceptable in RT and require action.
**Assessment:** Only "error" is flagged. Policy-violating states like stoppedUP (8 items currently) pass through as non-bad.
**Severity:** HIGH — affects drift normalization decisions.

### C3 — `cli.py` rt state-audit `--bad-only` treats stoppedUP as good

**Document:** `src/hashall/cli.py:4855`
**What it says:**
```python
rows = [row for row in rows if row["state"] not in {"uploading", "stalledUP", "stoppedUP"}]
```
This excludes stoppedUP from the bad-only results, treating it as a healthy state.
**What policy says (§2):** `stoppedUP` → ❌ NO — "Start it immediately. Should flip to stalledUP/uploading."
**Assessment:** Running `hashall rt state-audit --bad-only` will NOT show the 3 stoppedUP items, making them invisible to operators relying on this audit command.
**Severity:** MEDIUM — operator tool gives wrong signal.

### C4 — BACKLOG.md internal contradiction on Class 4 repair

**Document:** `docs/BACKLOG.md:194`
**What it says:**
> "Class 4 (`_rehome-unique/`) — no data movement, pure repoint; lowest risk"

**What the same document says at Gap 3 (line 60-73):**
> "SPRINT.md says 'Class 4 repairs: `_rehome-unique/<hash>/` — pure repoint, no data movement'. This is wrong for items with actual data. Investigation found three groups: Group A (items with data), Group B (empty dirs), Group C (nested staging)."

**Assessment:** The Canonical Tree Normalization section (line 194) contradicts Gap 3 (line 60-73) in the same file. The Gap 3 investigation is correct — some Class 4 items do have data. The taxonomy section was never updated after the investigation.
**Severity:** LOW — known gap, but could mislead agents planning Class 4 repairs.

### C5 — Path authority inconsistency across docs

**Documents:** `docs/RT-QB-STATE-POLICY.md:15`, `docs/RUNBOOK.md:127-128`, `docs/ARCHITECTURE.md:19`
**Policy §1 says:**
> "qBittorrent... is kept alive for its tag/category/path data, which is the authoritative source for canonical path resolution."

**RUNBOOK says:**
> "RT's path is canonical — repoint qB to match RT (offline fastresume patch). Exception: if RT's path is provably non-canonical..."

**ARCHITECTURE says:**
> "RT is the active seeder and path authority."

**Assessment:** The doc stack is inconsistent about which client is the path authority. The policy says qB is authoritative for canonical path resolution (the target/ideal path), while RUNBOOK says RT's actual path wins when both exist. These can be reconciled (qB=ideal target, RT=live location), but the doc relationship is not stated, causing confusion.
**Severity:** LOW — conceptually reconcilable, but unclear for agent readers.

---

## CATEGORY 2 — GAPS IN EXISTING DOCS

### G1 — RUNBOOK.md has no state-policy section

**Document:** `docs/RUNBOOK.md`
**Missing:** The entire state policy (acceptable/unacceptable RT/qB states, decision trees). RUNBOOK includes repair procedures but no reference to `docs/RT-QB-STATE-POLICY.md`. An agent reading RUNBOOK will find RT audit commands (`rt state-audit`, `rt repair-report`) but no description of what states are acceptable.
**Should reference:** `docs/RT-QB-STATE-POLICY.md` as prerequisite knowledge for all repair operations.
**Severity:** MEDIUM

### G2 — REQUIREMENTS.md §8.4 doesn't reference state policy

**Document:** `docs/REQUIREMENTS.md` §8.4
**Missing:** Requirements §8.4 is cited by both RUNBOOK and ARCHITECTURE as the authoritative reference for qB integration and RT path authority. But it doesn't mention `docs/RT-QB-STATE-POLICY.md` or link to it. A reader starting at §8.4 has no path to the state policy.
**Severity:** LOW

### G3 — ARCHITECTURE.md mentions RT/qB role but not state policy

**Document:** `docs/ARCHITECTURE.md:19`
**Missing:** The architecture doc says "RT is the active seeder and path authority. qB is the passive backup mirror (paused/stopped)" but doesn't reference the state policy for the full state machine. References REQUIREMENTS.md §4.4 and §8.4 but not RT-QB-STATE-POLICY.md.
**Severity:** LOW

### G4 — SPRINT.md Slice 13 trk_warn counts are stale (23 vs 18)

**Document:** `docs/SPRINT.md:336-339`
**Missing:** Slice 13 says "trk_warns: 23 Deleted Aither Torrents" with 23 items in 4 groups. The new policy doc §5 says 11 deleted, 4 auth_err, 3 other = 18 total. SPRINT.md hasn't been updated to reflect current tracker issue state after Slice 13d/e execution and post-state verification.
**Severity:** LOW — historical slice documentation, but could confuse readers checking current counts.

---

## CATEGORY 3 — GAPS IN RT-QB-STATE-POLICY.md

### P1 — §8.1: 4 known stalledDL hashes not enumerated

**Section:** `docs/RT-QB-STATE-POLICY.md:197-211`
**Missing:** The policy references 4 known zero-seed stalledDL items but has "TBD" placeholders for hashes. J03-T06 found 6 stalledDL items, not 4. The policy needs updating with actual hashes and the correct count.
**Source for fix:** J03-T06 task log (6 stalledDL items identified).
**Severity:** MEDIUM — the "4 known" count appears in multiple places and may be wrong.

### P2 — No `checkingDL` timeout or fallback

**Section:** `docs/RT-QB-STATE-POLICY.md:33`
**Current text:** "checkingDL — ✅ TRANSIENT — Wait for completion. Will resolve to seeding or DL state."
**Gap:** No guidance on what to do if checkingDL persists for hours/days. Policy should specify a timeout threshold and fallback action.
**Severity:** LOW

### P3 — `start` vs `resume` ambiguity for stopped items

**Section:** `docs/RT-QB-STATE-POLICY.md:140-147`
**Current text:** "START IT" for stoppedUP, stoppedDL, pausedDL items.
**Gap:** Policy uses "Start it" generically but §9 notes this is an open question: "RT d.start vs d.resume — Which command to use for stopped vs paused items." The decision tree uses the ambiguous term without resolution.
**Severity:** LOW — noted as open question in §9.

### P4 — No mention of `queuedUP` / `queuedDL` states

**Section:** §2 (RT states) and §3 (qB states)
**Gap:** Neither the RT nor qB state tables mention `queuedUP` or `queuedDL`. The qB state table only lists 8 states but qB has additional queued states. Are queued states acceptable? What action to take?
**Severity:** MEDIUM — queued items are not addressed at all.

### P5 — `stoppedUP` at 100% vs not-100% distinction

**Section:** `docs/RT-QB-STATE-POLICY.md:37`
**Current text:** "stoppedUP — ❌ NO — Start it immediately. Should flip to stalledUP/uploading."
**Gap:** All stoppedUP items are treated the same, but a stoppedUP at 100% progress makes sense (was seeding, got stopped), while stoppedUP at <100% is rare. The policy could distinguish, though the current blanket "start it" rule is correct.
**Severity:** INFORMATIONAL — not blocking, but could be clearer.

### P6 — No reference to `~noHL` tag or qbit_manage integration

**Section:** §3 (qB states), §7 (qB decision tree)
**Gap:** The policy doesn't mention the `~noHL` tag or qbit_manage's role in hardlink detection. REQUIREMENTS.md §4.1.1 and RUN-STATE.md both reference `~noHL` as an advisory pre-filter. The state policy could note that `~noHL` is a cross-cutting indicator (torrents tagged `~noHL` are pool candidates, which indirectly affects whether qB should be stopped or seeding on stash).
**Severity:** LOW — `~noHL` affects placement policy, not state policy directly.

---

## CATEGORY 4 — CODE/DOC MISMATCHES

### M1 — `qb_repair_payload_group.py:BROKEN_EXPECTED_STATES` includes "downloading"

**File:** `src/hashall/qb_repair_payload_group.py:42-50`
**Code:**
```python
BROKEN_EXPECTED_STATES = {
    "stoppeddl", "pauseddl", "missingfiles", "error",
    "queueddl", "stalleddl", "downloading",
}
```
**Policy says (§2):** `downloading` (non-cross-seed) is ACCEPTABLE — "Transitional — will flip to seeding when complete."
**Mismatch:** Code treats all `downloading` as broken. For non-cross-seed items, this is wrong. Policy only flags cross-seed downloading as a violation.
**Severity:** MEDIUM — may cause false-positive broken-state flags for transitional downloads.

### M2 — `qb_repair_payload_group.py:GOOD_DONOR_STATES` includes `pausedup`

**File:** `src/hashall/qb_repair_payload_group.py:41`
**Code:**
```python
GOOD_DONOR_STATES = {"stalledup", "stoppedup", "pausedup", "queuedup", "uploading", "forcedup"}
```
**Policy says (§3):** `pausedUP` → ❌ NO — "Stop immediately."
**Mismatch:** Code considers `pausedup` a valid donor state (and `GOOD_SEED_STATES` at line 52 agrees). Policy says it must be stopped.
**But note:** A donor in pausedUP may still have valid data, so this is about whether the code should also flag the donor's state for remediation, not about data availability.
**Severity:** LOW — correction: code should accept pausedUP donors but log a warning that the donor itself needs remediation.

### M3 — `rehome/cli.py:good_states` includes `pausedup` and `forcedup`

**File:** `src/rehome/cli.py:188-193`
**Code:**
```python
good_states = {
    "stalledup", "uploading", "queuedup", "forcedup",
    "stoppedup", "pausedup", "checkingup",
}
```
**Policy says (§3):** `pausedUP` → ❌ NO, `forcedUP` → ❌ NO. Both must be stopped immediately.
**Mismatch:** `_print_post_apply_summary()` considers pausedUP and forcedUP as "good" states equivalent to stalledUP. These should be flagged as needing attention per policy.
**Severity:** MEDIUM — post-apply summary would show ✅ for a pausedUP or forcedUP torrent, misleading the operator.

### M4 — `rehome/auto.py:SEED_READY` includes `pausedup`

**File:** `src/rehome/auto.py:26`
**Code:**
```python
SEED_READY = {"uploading", "stalledup", "queuedup", "forcedup", "pausedup", "stoppedup"}
```
**Policy says (§3):** `pausedUP` → ❌ NO.
**Mismatch:** `_is_qb_ready_state()` returns True for `pausedup`, treating it as an acceptable post-rehome seed state. Policy says it's not.
**Severity:** MEDIUM — rehome auto-apply may consider pausedUP items as "done" when they still need remediation.

### M5 — `path_normalize.py:_BAD_QB_STATES` missing 5 policy-violating states

**File:** `src/hashall/path_normalize.py:29`
**Code:**
```python
_BAD_QB_STATES = {"error", "missingfiles"}
```
**Policy says (§3):** uploading, stalledUP, forcedUP, pausedUP, downloading, error are all unacceptable.
**Mismatch:** Only `error` and `missingfiles` are flagged. `is_qb_bad_terminal_state()` returns False for uploading, stalledUP, forcedUP, pausedUP, downloading.
**Severity:** HIGH — this function is used in `derive_normalization_outcome_with_context()` (path_normalize.py:83) which reports "ambiguous_needs_review" when bad states are detected. Without the full state set, policy-violating items pass silently.

### M6 — `path_normalize.py:_BAD_RT_STATES` missing 3 policy-violating state groups

**File:** `src/hashall/path_normalize.py:30`
**Code:**
```python
_BAD_RT_STATES = {"error"}
```
**Policy says (§2):** stoppedUP, stoppedDL, pausedDL, downloading (cross-seed) are all unacceptable.
**Mismatch:** Only "error" is flagged. Policy-violating RT items (8 stoppedDL, 3 pausedDL currently) pass through as non-bad.
**Severity:** HIGH — same issue as M5 for RT state detection.

---

## CATEGORY 5 — STALE DATA

### S1 — RUN-STATE.md (2026-05-19)

**Document:** `docs/operations/RUN-STATE.md`
**Stale content:**
- Drift queue (3 cases: Alien, Twin Peaks, Novitiate) — these have been resolved in Slice 1/2/6
- RT-only row (Top Gun Maverick) — mirrored in Slice 7
- qB=4817, RT=4818 row counts — now 4889 each
- Catalog last scan: 2026-05-10 (9 days old at writing) — now over a month old
- Drift counts (1 high, 0 medium, 2 low) — almost certainly changed
**Estimated age:** 24 days stale
**Severity:** MEDIUM — outdated evidence baseline misleads agents starting fresh.

### S2 — RECOVERY.md (2026-05-08)

**Document:** `docs/RECOVERY.md`
**Stale content:**
- Repair queue (Easy: Spider-Man, Medium: 5 items, Hard: 5 items) — from May 8, likely resolved
- Last Evidence Snapshot: qB=5203, RT=5210 — now 4889 each
- Drift: qB-only=0, RT-only=7, path-drift=11 — significantly changed
- Active repair lane branch reference is obsolete
**Estimated age:** 35 days stale
**Severity:** LOW — RECOVERY.md is a cold-start orienter, but drift/queue data is misleading.

### S3 — SPRINT.md Evidence Baseline (2026-05-20)

**Document:** `docs/SPRINT.md:185-194`
**Stale content:**
- qB=4818, RT=4818 rows — now 4889 each
- Drift=0 — unknown current state
- Hitchhiker audit: 162 groups (54 Type A, 60 safe-to-split, 47 blocked, 1 busy) — likely changed after repairs
- Orphan GC candidates: 2480 (2477 aged, 2 new)
**Estimated age:** 23 days stale
**Severity:** LOW — historical baseline for sprint context.

### S4 — BACKLOG.md Canonical Tree Normalization baseline (2026-05-19)

**Document:** `docs/BACKLOG.md:181-191`
**Stale content:**
- Class counts from May 19 baseline: Class 1=10, Class 2=7, Class 3=14, Class 4=12, Class 5=47
- Slice 12a has since repaired 376 Class 4 dirs (per SPRINT.md line 29)
- Class 5 also had 38 repaired (line 33)
- Total non-canonical "~90 payloads" is almost certainly different now
**Estimated age:** 24 days stale
**Severity:** LOW — class counts are not live query results.

### S5 — ops-log.md (March 2026 entries)

**Document:** `docs/ops-log.md`
**Stale content:** Entries from 2026-03-06 through 2026-03-13 documenting historical rehome pilots, bug fixes, cleanup waves. Most describe operations that have been completed and superseded.
**Estimated age:** 91-96 days stale
**Severity:** INFORMATIONAL — historical record, not actionable. Doc itself notes its staleness at top: "Latest stale-assumption hardening note (2026-03-13)".

---

## Priority Action Items (Lead's Decision)

### HIGH (fix before next repair session)
1. **M5/HIGH** — `path_normalize.py:_BAD_QB_STATES` missing 5 states
2. **M6/HIGH** — `path_normalize.py:_BAD_RT_STATES` missing 3 state groups
3. **C1/HIGH** — `_BAD_QB_STATES` under-inclusive affects drift normalization
4. **C2/HIGH** — `_BAD_RT_STATES` under-inclusive affects drift normalization

### MEDIUM (fix soon)
5. **C3/MEDIUM** — `cli.py:4855` — `rt state-audit --bad-only` treats stoppedUP as good
6. **M3/MEDIUM** — `rehome/cli.py:good_states` includes pausedUP/forcedUP
7. **M4/MEDIUM** — `rehome/auto.py:SEED_READY` includes pausedUP
8. **M1/MEDIUM** — `BROKEN_EXPECTED_STATES` includes downloading
9. **G1/MEDIUM** — RUNBOOK.md missing state policy reference
10. **S1/MEDIUM** — RUN-STATE.md stale baseline (24 days)
11. **P4/MEDIUM** — Policy missing queuedUP/queuedDL states

### LOW (tracking/informational)
12-24. Remaining findings per categories above

---

```
🟪 task-log=J03-T07_state-policy-doc-audit 🟪
```
