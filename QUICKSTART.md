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
| Agent pane | `%463` (OpenCode / DeepSeek V4 Flash Free) |

---

## 2. Current Goal

Repair all torrent save-path drift and legacy path patterns to zero mismatches, migrating seed-only content to pool-media using validated, gate-checked tooling.

---

## 3. In-Flight Jobs

| Job | Branch | Status | Last commit |
|-----|--------|--------|-------------|
| j11 `drift-fix-class4-investigation` | `cr/hashall-20260530-000517-claude__j11` | **active — T03 running on agent** | `dca2e3d` AGENT-MASTERY.md v1.1.0 |

### j11 task status

| Task | Status | Finding |
|------|--------|---------|
| T01 — Gate 1+2 drift fix validation | ✅ done | CERTIFIED SAFE FOR DRY-RUN (`cd5c029`) |
| T02 — Gate 3 dry-run + pilot | ✅ done | BLOCKED — cross-device guard fired correctly (`6fe5107`) |
| T03 — Class 4 investigation | 🔄 **in-progress on agent pane %463** | 47.4K/24% tokens, running |

### What T02 found (important)

Both HIGH drift items (NOVA.S50 `2d4016de`, Magic.City.S01 `f0bc85ee`) have qB on stash (device 49) and RT on pool-media (device 45). Files already exist on pool-media (RT is seeding). The cross-device guard in `qbittorrent.py` blocked `set_location` because devices differ — but the guard is too conservative: it does not check whether files already exist at the target. If files exist there, no copy would occur. This is j12.

---

## 4. Next Actions (in order)

1. **Check agent pane %463** for T03 completion or stall:
   ```bash
   tmux capture-pane -t %463 -p 2>/dev/null | grep -E '[0-9]+\.[0-9]+K|Permission|Allow|next instruction|done'
   ```

2. **When T03 log arrives** — read it, triage Class 4 findings, update OPS.md, accept or block:
   ```bash
   cat /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j11/comms/logs/J11-T03-log.md
   ```

3. **Update T03 expected_head in J11-T03 brief, then accept T03**, update JOB-QUEUE.md, and close j11 with `chatrap job done` from the j11 worktree.

4. **Start j12** — cross-device guard refinement. Brief: before blocking on `st_dev` mismatch, check whether files exist at the target path. If they do, allow `set_location` (qB updates metadata only, no copy). Then re-run Gate 3 on the 2 HIGH drift items.

5. **After j12** — proceed to Slice 12b (2125 `cross-seed/<tracker>/` items): three-gate validation, then pilot 5 items.

---

## 5. Key Commands

```bash
# Check agent pane state
tmux capture-pane -t %463 -p -S -20 2>/dev/null | tail -20

# Send task brief to agent (replace BRIEF_PATH and TASK_ID)
tmux send-keys -t %463 "[chatrap-lead] task-brief ready: <TASK_ID> — read it at <BRIEF_PATH> — ack to %324 when received, then execute" Enter

# Check j11 job branch state
git -C /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j11 log --oneline -5

# Close j11 after all tasks accepted (run from j11 worktree)
cd /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j11 && chatrap job done

# Drift audit (always use ANCHOR_SCAN=200000)
make -C /home/michael/dev/work/hashall client-drift-audit ANCHOR_SCAN=200000
```

---

## 6. Open Risks and Blockers

| Risk | Severity | Detail |
|------|----------|--------|
| Cross-device guard too conservative | HIGH | Blocks 2 HIGH drift items that are actually safe. Fix in j12 before any bulk drift repair. |
| Class 4 grew from 10 → 64 items | MEDIUM | Cause unknown — T03 is investigating. Do not repair Class 4 until investigation complete. |
| 42+ open OPs in OPS.md | MEDIUM | Rollback fragmentation across all tools — no tool has a complete undo path. Gate everything. |
| Agent pane %463 narrow (30 cols) | LOW | Token counter and status wrap badly. Use `-S -20` captures and grep for key strings. |
| J11-T03 still in-flight | BLOCKER | Cannot close j11 or start j12 until T03 log is received and accepted. |
