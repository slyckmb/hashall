# QUICKSTART — hashall-20260530-000517-claude

_Read this first after /clear. Everything you need to resume in under 2 minutes._

---

## 1. Session Identity

| Field | Value |
|-------|-------|
| Chat ID | `hashall-20260530-000517-claude` |
| CR branch | `cr/hashall-20260530-000517-claude` |
| CR worktree | `/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude` |
| Lead pane | `%324` |
| Agent pane | `%463` (OpenCode / DeepSeek V4 Flash, Go tier) |

---

## 2. Current Goal

**CATEGORY_DRIFT = 0. All lane 1 + 1b work complete as of 2026-06-19.**

- Lane 1 (target-absent renames): 23 groups / 138 items — DONE
- Lane 1b (merge into existing category dirs): 19 groups / 232 items — DONE
- 12 "conflict" items (hardlinked, both paths existed): repointed RT+qB to canonical — DONE
- 22 cross-seed RT-only duplicates: repointed to cross-seed canonical — DONE
- `hashall payload lane1-plan` → **0 items** (confirmed 2026-06-19 ~02:00)

**Next: Lane 2 — ROOT_DRIFT (1030 items) + compound drift (2361 items, STASH→POOL + rename).**

---

## 3. Session Summary — What Has Been Done

| Job | Delivered |
|-----|-----------|
| j09 | Cold-read audit of 5 mutation tools, 47 findings, OPS.md created |
| j10 | 3 critical bug fixes: `_resolve_full_hash`, `set_location` pause guard, `repoint_both_to_pool` order |
| j11 | Gate 1+2 cert for drift fix; Gate 3 pilot blocked by cross-device guard (correct); Class 4 root cause |
| j12 | Cross-device guard bypass; both HIGH drift items cleared; drift high=0 |
| j13 | `CANONICAL-PATH-SPEC.md` v1.0.0-draft — 5-step decision tree |
| j14 | `canonical_path_resolver.py` + CLI `hashall payload canonical-path`; 3 bugs fixed; Gates 1-3 pass |
| j15 | RT multi-file directory normalization fix (`_normalize_rt_path`); Gate 3 re-run pass |
| j16 | `lane1_plan.py` + CLI `hashall payload lane1-plan`; anomalous source filter (partial — j18 pending) |
| j17 | `lane1_execute.py` + CLI `hashall payload lane1-execute`; filelist pilot (2 items) ✓ |
| j18 | Anomalous filter fix (`_is_safe_source_dir`) + `resume_after=False` in `set_location`; `stoppedDL` added to pause-wait set |
| j19 | Re-pause fix after `checkingUP` in `lane1_execute.py`; 134 tests pass |
| j20 | Gate 0 recovery: audit 115 stoppedDL (82 HEALTHY, 28 MISSING_DATA, 5 RT_INCOMPLETE); batch repair → 115→6 stoppedDL |
| j21 | Controlled experiment: qB `recheck_torrent()` does NOT trigger RT hash checks (hypothesis not confirmed) |
| j22 | Lane 1b executor: `execute_lane1b_merge_group()`, `lane1b-execute` CLI, cross-seed dup repoint fix (0.8.61) |
| j23 | `set_location()` FileNotFoundError bypass fix — blocked unauthorized cross-device move for container paths; RCCA at `docs/RCCA-SETLOCATION-FNF.md`; v0.8.62; 2 new tests |

---

## 4. Migration Moratorium

**No mutations** from `rehome`, `save_path_inference`, or `save-path-repair --execute`.
The canonical path resolver replaces them. Dry-run and audit commands permitted.

---

## 5. Current Migration State

**Gate 3 validated:** 4901 items — 1049 canonical, 3852 drifted, 0 unexpected combos.

### Lane breakdown

| Lane | Items | Type | Status |
|------|-------|------|--------|
| Lane 1 (target-absent) | 23 groups / 138 items | Same-root category rename | **COMPLETE** |
| Lane 1b (merge-into-existing) | 19 groups / 232 items | Per-item merge + repoint | **COMPLETE** |
| Conflict items | 12 | Target already has different content | Pending manual review |
| Cross-seed RT-only dups | 22 | "source missing, target exists" — RT repointed | **DONE** |
| Compound drift | 2361 | STASH→POOL + rename | Deferred to Lane 2 |
| Pure ROOT_DRIFT | 1030 | Root migration only | Deferred to Lane 2 |
| Staging | 58 | `_rehome-unique` etc | Deferred (moratorium) |
| Anomalous | 4 | Dangerous source paths (see below) | Excluded, manual review needed |

### Pilot result (2026-06-18 — FAILED)

23 groups / 138 items attempted. Stale editable install (j18 not closed) + `resume_after=False` absent → 115 stoppedDL. Full RCCA in `docs/LANE1-PILOT-RCCA.md`. **All 9 root causes documented and fixed.**

### Gate 0 recovery (complete)

115 stoppedDL → **6 stoppedDL**. Remaining 6 are pre-existing (5 RT_INCOMPLETE + 1 MISSING_DATA). 4896 stoppedUP confirmed seeding. 0 RT writes during recovery.

---

## 6. Code Fixes Applied (all committed, all tested)

All fixes are live in CR branch. **Do NOT proceed to Gate 1 without verifying editable install points to CR worktree.**

| Fix | File | Commit |
|-----|------|--------|
| `resume_after=False` in `set_location` | `qbittorrent.py` | j18 |
| `stoppedDL` added to pause-wait set | `qbittorrent.py` | j18 |
| Re-pause after `checkingUP` in execute | `lane1_execute.py` | j19 |
| Category-dir exists check in plan | `lane1_plan.py` | j18 |
| `_is_safe_source_dir` anomalous filter | `lane1_plan.py` | j18 |
| RT pre-flight download check (`_rt_fetch_health`) | `lane1_execute.py` | j19 |
| RT post-repoint health poll (`_rt_health_check`) | `lane1_execute.py` | j19 |

**36 tests pass** in `tests/test_lane1_execute.py` (v0.8.61).

---

## 7. Anomalous Items (Excluded from Automation)

4 items with dangerous source paths — must NOT be passed to `lane1-execute`:
- `/pool/media/torrents/seeding` (seeding root itself)
- `/pool/media/torrents/seeding/cross-seed` (cross-seed dir)
- `/pool/.../FileList.io/Beetlejuice.1988...` (content subdir, 2 levels deep)
- `/pool/.../FileList.io/UEFA.Europa...` (content subdir, 2 levels deep)

---

## 8. Next Actions After /clear

**MUTATION LOCK LIFTED** — j24/j25/j26 complete (2026-06-20). English Grammar Boot Camp repaired. stoppedDL = 5 (pre-existing only).

### ~~j24–j26 (COMPLETE 2026-06-20)~~ — damage investigation + repair

### Next jobs

| Job | Scope | OPs |
|-----|-------|-----|
| j27 | Operator review: 12 conflict items + 4 anomalous items — decision and resolution | OP-23, OP-24 |
| j28 | Lane 2 strategy decision + executor planning (STASH→POOL, 1030 ROOT_DRIFT + 2361 compound) | OP-26 |

**Lane 2 scope (deferred):**
- 1030 pure ROOT_DRIFT: same category, wrong seeding root (STASH→POOL)
- 2361 compound drift: wrong root AND wrong category simultaneously
- Both require cross-device copy — no executor exists yet; 19.4 TB unique data vs ~3.1 TB free on pool

**Pre-mutation gate (mandatory before any mutation run):**
```bash
pip install -e /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude -q
pip show hashall | grep Location  # must show CR worktree path
```

**qB state (confirmed 2026-06-20, after j24-j26):**
- stoppedUP: 4898 (English Grammar Boot Camp repaired +1)
- stoppedDL: 5 — all pre-existing RT_INCOMPLETE (Dexter S02/S07, River Monsters, Diary of Teenage Girl, Transformers)
- 0 items damaged by our work

---

## 9. Key Commands

```bash
# Check agent pane
tmux capture-pane -t %463 -p | tail -20

# Send brief to agent (ALWAYS /clear pane first, wait 15s)
tmux send-keys -t %463 "/clear" Enter && sleep 15
source /home/michael/dev/tools/chatrap/lib/chatrap-common.sh
chatrap_send_to_agent_pane %463 "$(cat /tmp/<brief-file>.md)"

# Re-run lane1 plan (after reinstall if needed)
pip install -e /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude -q
hashall payload lane1-plan

# Verify specific hash
hashall payload canonical-path --hash <hash>

# Create next job (from CR worktree)
chatrap job --name <slug>

# Close job (from job worktree)
cd <job-worktree> && chatrap job done
```

---

## 10. Key Files

| File | Purpose |
|------|---------|
| `docs/OPS.md` | All open opportunities and observations — OP-01 through OP-27 |
| `docs/CANONICAL-PATH-SPEC.md` | Authoritative path resolution spec |
| `docs/RCCA-SETLOCATION-FNF.md` | j23 RCCA — set_location FNF bypass root cause and fix |
| `docs/OP-INVESTIGATE-GRAMMAR-BREAK.md` | OP-20 procedure — English Grammar Boot Camp investigation |
| `docs/OP-REPAIR-GRAMMAR-QB.md` | OP-21 procedure — English Grammar Boot Camp qB repair |
| `docs/LANE1-PILOT-RCCA.md` | Pilot failure analysis — 9 root causes, Gate 0 complete |
| `docs/GATE0-STOPPDL-AUDIT.md` | Gate 0 T01 audit — 115 stoppedDL classified |
| `docs/GATE0-T02-REPAIR.md` | Gate 0 T02 repair — 115→6 stoppedDL, 4896 stoppedUP |
| `src/hashall/canonical_path_resolver.py` | Core resolver — 5-step decision tree |
| `src/hashall/lane1_plan.py` | Lane 1 dry-run plan generator |
| `src/hashall/lane1_execute.py` | Lane 1 execute — all fixes committed, 49 tests pass |
| `SESSION.md` | Live session goal + step |
| `~/.hashall/reports/lane1-plan-*.json` | Latest plan report (source of truth for groups) |
