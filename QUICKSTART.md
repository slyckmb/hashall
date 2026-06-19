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

Re-execute Lane 1 migration safely after the 2026-06-18 pilot failure and Gate 0 recovery.
Lane 1 renames category dirs + repoints RT/qB for ~134 CATEGORY_DRIFT items (no data movement).
All code fixes are committed. Gate 0 incident recovery is complete (115→6 stoppedDL).
**Next: Gate 1 pre-flight, then Gate 2 dry-run, then Gate 3 single-group pilot.**

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
| Lane 1 true | 376 safe | Same-root rename (no data movement) | **In progress** — 2 done (filelist), 374 remaining |
| Compound drift | 2361 | STASH→POOL + rename | Deferred to Lane 2 |
| Pure ROOT_DRIFT | 1030 | Root migration only | Deferred to Lane 2 |
| Staging | 58 | `_rehome-unique` etc | Deferred (moratorium) |
| Target-exists | 12 | Content at canonical, clients not repointed | Deferred |
| Anomalous | 4 | Dangerous source paths (see below) | Excluded, manual review needed |
| Multi-target | ~36 | readarr→books+ebooks, speakarr→audiobooks+books | Excluded, need item-level moves |

### Pilot result (2026-06-18 — FAILED)

23 groups / 138 items attempted. Stale editable install (j18 not closed) + `resume_after=False` absent → 115 stoppedDL. Full RCCA in `docs/LANE1-PILOT-RCCA.md`. **All 9 root causes documented and fixed.**

### Gate 0 recovery (complete)

115 stoppedDL → **6 stoppedDL**. Remaining 6 are pre-existing (5 RT_INCOMPLETE + 1 MISSING_DATA). 4896 stoppedUP confirmed seeding. 0 RT writes during recovery.

### Clean target-absent groups (~134 items, ~23 groups) — ready to re-execute after Gate 1-3

All are cross-seed `cross-seed/` prefix additions on POOL:
Darkpeers (API):18, FileList.io:17, seedpool (API):17, hawke-uno:13, TorrentDay:10,
DigitalCore (API):9, YUSCENE (API):8, _movie:7, FearNoPeer:6, XSpeeds:5,
TorrentLeech:5, YOiNKED (API):4, DocsPedia:4, movies:3, onlyencodes:3,
filelist:2(done), tv:2, MyAnonamouse:1, yuscene:1, speedcd:1, HD-Space:1, torrentleech:1, SpeedCD:1, hawkeuno:1

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

**49 tests pass** in `tests/test_lane1_execute.py`.

---

## 7. Anomalous Items (Excluded from Automation)

4 items with dangerous source paths — must NOT be passed to `lane1-execute`:
- `/pool/media/torrents/seeding` (seeding root itself)
- `/pool/media/torrents/seeding/cross-seed` (cross-seed dir)
- `/pool/.../FileList.io/Beetlejuice.1988...` (content subdir, 2 levels deep)
- `/pool/.../FileList.io/UEFA.Europa...` (content subdir, 2 levels deep)

---

## 8. Next Actions After /clear

**Gate 1 — Pre-flight (do this before any lane1 execution):**
1. Verify editable install: `cat $(python3 -c "import site; print(site.getsitepackages()[0])")/__editable__.hashall-*.pth` — must show CR worktree path
2. Confirm no open jobs: `git worktree list` — only CR worktree should exist
3. Run test suite: `pytest tests/test_lane1_execute.py tests/test_lane1_plan.py -q` — all green
4. Snapshot qB state: `python3 -c "import sys; sys.path.insert(0,'src'); from hashall.qbittorrent import QBittorrentClient; qb=QBittorrentClient('http://localhost:9003',username='admin',password='adminadmin'); [print(t.state) for t in qb.get_torrents()]" | sort | uniq -c`
5. Confirm: **0 stalledUP, 0 checkingUP** before touching anything

**Gate 2 — Dry-run:**
6. `hashall payload lane1-plan` — confirm group list, check canonical_path values

**Gate 3 — Single-group pilot:**
7. Run ONE group (smallest, 1–3 items) with `hashall payload lane1-execute`
8. Check: 0 new stalledUP, 0 new stoppedDL, RT seeding at canonical path, qB stoppedUP
9. Wait 60s, re-check states — confirm no spontaneous transitions
10. Human sign-off before Gate 4

**Gate 4 — Batch (≤5 groups per batch, human sign-off between):**
11. `hashall payload lane1-execute` in batches, full state check after each

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
| `docs/CANONICAL-PATH-SPEC.md` | Authoritative path resolution spec |
| `docs/LANE1-PILOT-RCCA.md` | Pilot failure analysis — 9 root causes, Gate 0 complete |
| `docs/GATE0-STOPPDL-AUDIT.md` | Gate 0 T01 audit — 115 stoppedDL classified |
| `docs/GATE0-T02-REPAIR.md` | Gate 0 T02 repair — 115→6 stoppedDL, 4896 stoppedUP |
| `src/hashall/canonical_path_resolver.py` | Core resolver — 5-step decision tree |
| `src/hashall/lane1_plan.py` | Lane 1 dry-run plan generator |
| `src/hashall/lane1_execute.py` | Lane 1 execute — all fixes committed, 49 tests pass |
| `SESSION.md` | Live session goal + step |
| `~/.hashall/reports/lane1-plan-*.json` | Latest plan report (source of truth for groups) |
