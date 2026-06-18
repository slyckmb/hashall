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

Execute Lane 1 migration: rename category directories and repoint clients for the
378 same-root CATEGORY_DRIFT items (no data movement). The resolver is built and
4-gate validated. The execute path is proven (j17 pilot). A qB stalledUP fix is
needed in `lane1_execute.py` before running more groups.

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
| j18 | In progress: anomalous filter fix + qB stalledUP fix |

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

### Clean target-absent groups ready to execute (~134 items, ~23 groups)
All are cross-seed `cross-seed/` prefix additions on POOL:
Darkpeers (API):18, FileList.io:17, seedpool (API):17, hawke-uno:13, TorrentDay:10,
DigitalCore (API):9, YUSCENE (API):8, _movie:7, FearNoPeer:6, XSpeeds:5,
TorrentLeech:5, YOiNKED (API):4, DocsPedia:4, movies:3, onlyencodes:3,
filelist:2(done), tv:2, MyAnonamouse:1, yuscene:1, speedcd:1, HD-Space:1, torrentleech:1, SpeedCD:1, hawkeuno:1

---

## 6. CRITICAL: qB stalledUP Violation

`set_location` in qB: pause → setLocation → checkingUP (hash recheck) → **auto-resumes to stalledUP**.
The 2 filelist items were manually re-paused. `lane1_execute.py` needs this fix before any more groups run:

```python
# After set_location, poll until checkingUP finishes, then re-pause if needed
PAUSED_STATES = {"pausedUP", "stoppedUP", "pausedDL", "stoppedDL"}
CHECK_STATES  = {"checkingUP", "checkingDL", "moving"}
for _ in range(60):  # up to 30s
    info = qb_client.get_torrent_info(hash)
    if info and info.state not in CHECK_STATES:
        break
    time.sleep(0.5)
if info and info.state not in PAUSED_STATES:
    qb_client.pause_torrent(hash)
    time.sleep(1)
    info = qb_client.get_torrent_info(hash)
assert info.state in PAUSED_STATES
```

---

## 7. Anomalous Items (Excluded from Automation)

4 items with dangerous source paths — must NOT be passed to `lane1-execute`:
- `/pool/media/torrents/seeding` (seeding root itself)
- `/pool/media/torrents/seeding/cross-seed` (cross-seed dir)
- `/pool/.../FileList.io/Beetlejuice.1988...` (content subdir, 2 levels deep)
- `/pool/.../FileList.io/UEFA.Europa...` (content subdir, 2 levels deep)

---

## 8. Next Actions After /clear

1. **Check j18 status** — `tmux capture-pane -t %463 -p | tail -20`
   - If agent has committed anomalous filter fix → send execute fix brief (j18-T02)
   - If not → redirect agent to implement `_is_safe_source_dir()` in `lane1_plan.py`

2. **j18-T02** — fix `lane1_execute.py` stalledUP: poll checkingUP, re-pause if needed

3. **j18-T03** (or j19) — execute next batch of target-absent groups after fix validated

4. **Eventually** — merge clean target-absent groups (134 items), then plan Lane 2 (compound drift + ROOT_DRIFT)

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
| `src/hashall/canonical_path_resolver.py` | Core resolver — 5-step decision tree |
| `src/hashall/lane1_plan.py` | Lane 1 dry-run plan generator |
| `src/hashall/lane1_execute.py` | Lane 1 execute (stalledUP fix needed) |
| `SESSION.md` | Live session goal + step |
| `~/.hashall/reports/lane1-plan-*.json` | Latest plan report (source of truth for groups) |
