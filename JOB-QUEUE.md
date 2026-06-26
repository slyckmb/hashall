# Job Queue — hashall CR

session: hashall-20260530-000517-claude
branch: cr/hashall-20260530-000517-claude
worktree: /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude
updated: 2026-06-26

---

## Active Execution Plan

| Job | Slug | OPs |
|-----|------|-----|
| j36 | close-resolved | OP-29,OP-32,OP-46,OP-48 | done |
| j37 | code-bug-fix | OP-04,OP-05,OP-06,OP-16 |
| j38 | rcca-and-audit | OP-19,OP-24,OP-47 |
| j39 | cross-seed-repair | OP-09,OP-15,OP-17 |
| j40 | docs-batch | OP-01,OP-02,OP-03,OP-07,OP-08,OP-11,OP-12,OP-13,OP-25 |
| j41 | explore-unified-tool | OP-18 |
| j42 | lane2-strategy | OP-23,OP-26 |
| j43 | rt-state-monitor | OP-10,OP-43 |
| j44 | chatrap-infra | OP-42,OP-44,OP-45 |
| j45 | cr-to-main | OP-14 |

---

## Dependencies

- j39 (cross-seed-repair) requires j37 (code-bug-fix) — must fix OP-16 before migrating ~2000 items
- j42 (lane2-strategy) benefits from j41 (explore-unified-tool) — tool design informs Lane 2 feasibility
- j45 (cr-to-main) is last — merge only after all planned repair jobs complete

---

## Run Order

j36 → j37 → j38 → j40 → j41 → j39 → j42 → j43 → j44 → j45

Notes:
- j40 (docs) is independent and can be interleaved
- j43 (monitoring) should run promptly — OP-43 items have a 48h check window
- j44 (chatrap infra) is upstream work; file issues with chatrap maintainers, not code in this repo
- j36 first to clear resolved OPs and keep opscan count accurate

---

## j37 — code-bug-fix

**Slug:** code-bug-fix
**OPs:** OP-04, OP-05, OP-06, OP-16
**Goal:** Audit 4 open code bugs; close those already fixed; fix any still open.

### Tasks

| Task | Type | Goal |
|------|------|------|
| j37-t01 | discovery | Verify OP-05, OP-06, OP-16 status in current code; close confirmed-fixed OPs; document OP-04 fix scope |
| j37-t02 | implementation | Fix OP-04: integrate SYSTEM_TAGS with traktor registry (TBD after t01) |

---

## Queue State Notes

JOB-QUEUE.md written 2026-06-26 by lead after opscan showed 32 unslotted OPs.
All 32 open OPs now slotted across 10 planned jobs.
Next job to dispatch: j36 (close-resolved).
