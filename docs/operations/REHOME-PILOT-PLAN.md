# Rehome Crawl/Walk/Run Pilot Plan

**Created:** 2026-03-03
**Status:** Active — Part 1 complete, Phase 0 pre-flight next
**Scope:** (1) Archive dev/experimental tooling from the Feb 2026 repair effort, establishing a clean canonical code path. (2) Run the graduated rehome pilot using the hardened executor, fixing bugs that arise before advancing phases.

---

## Multi-Session Protocol

**Every session MUST:**

1. Read this document first — check current phase status and activity log.
2. Commit after every logical unit (archival, phase completion, bug fix) with a conventional commit message.
3. Update the Activity Log at every stopping point before ending the session.
4. Update `docs/operations/RUN-STATE.md` when the active toolchain changes.
5. Commit doc updates as a separate `docs:` commit before ending the session.

### Commit cadence

| Event | Commit message prefix |
|-------|-----------------------|
| Pilot plan written to repo | `docs(ops): add rehome pilot plan with activity log` |
| Scripts archived | `chore(bin): archive feb-2026 repair and legacy pipeline scripts` |
| rehome-106 rename | `refactor(bin): rename nohl-basics-qb-hash-root-report to qb-hash-root-report` |
| RUN-STATE.md update | `docs(ops): update active toolchain after script archival` |
| Phase complete | `ops(rehome-pilot): phase N complete — N torrents verified` |
| Bug fix | `fix(rehome): <description>` |
| Session end | `docs(ops): update pilot activity log — <phase> <status>` |

---

## Canonical Code Path

```
make rehome-safe-auto → scripts/rehome_safe_workflow.py
  └─ python -m rehome.cli plan --demote   [per candidate]
  └─ python -m rehome.cli apply --force   [hardened executor: executor.py]

make rehome-safe-verify / rehome-safe-cleanup → scripts/rehome_safe_verify_cleanup.py
make rehome-followup → python -m rehome.cli followup
```

`rehome-safe-auto` selects **MOVE** candidates only (100% movable bytes, recommendation=MOVE from status report). For REUSE-only or single-hash runs, use `make rehome-plan-demote` + `make rehome-apply-dry`/`make rehome-apply` directly.

**Hardened executor guarantees (as of 2026-03-03, v0.4.0):**
- Preflight blocks any torrent not at 100% progress or in a download/stoppedDL state
- tag_strict=True default — tag failures abort execution
- resume_on_failure=True default — unconditional torrent state restore on failure
- ATM rollback — re-enables Auto-Management if disabled then operation fails
- Concurrency lock — `fcntl.LOCK_EX|LOCK_NB` on `~/.hashall/rehome.lock`
- stoppedDL fast-fail — raises immediately if torrent enters stoppedDL after relocation
- Post-apply summary — mandatory state table after every `--force` run, exits 1 if ALARM

**Non-negotiables (from RUN-STATE.md):**
- One mutating qB workflow at a time
- No concurrent stoppedDL repair during rehome apply
- Any full DB refresh must cover all three archives: `/stash/media`, `/pool/data`, `/mnt/hotspare6tb`

---

## Part 1: Tooling Cleanup

### Status: ✅ Complete (2026-03-03)

### 1A. Archive → `bin/archive/2026-02-repair/`

Sequential-stage scripts from the Feb 2026 repair effort. Bypass the hardened executor or duplicate its functionality with unverified safety properties.

```
rehome-100_nohl-basics-qb-repair-baseline.sh
rehome-101_nohl-basics-qb-candidate-mapping.sh
rehome-102_nohl-basics-qb-repair-pilot.sh
rehome-103_nohl-basics-qb-repair-continue.sh
rehome-103_nohl-basics-qb-payload-ownership-audit.sh
rehome-104_nohl-basics-qb-build-clean-mapping.sh
rehome-105_nohl-basics-qb-repair-autoloop.sh
rehome-107_nohl-basics-qb-repair-lane-plan.sh
rehome-108_nohl-basics-qb-build-strict-map.sh
rehome-89_nohl-basics-qb-automation-audit.sh
rehome-90_nohl-basics-scan-stash.sh
rehome-91_nohl-basics-scan-pool.sh
rehome-92_nohl-basics-payload-sync.sh
rehome-93_nohl-basics-run-dryrun.sh
rehome-94_nohl-basics-run-apply.sh
rehome-95_nohl-basics-qb-missing-audit.sh
rehome-96_nohl-basics-qb-missing-remediate-dryrun.sh
rehome-97_nohl-basics-qb-missing-hardcase-reconnect.sh
rehome-98_orphaned-data-smart-move.sh
```

**Exception — keep and rename:** `rehome-106_nohl-basics-qb-hash-root-report.sh` → `bin/qb-hash-root-report.sh`

### 1B. Archive → `bin/archive/legacy-pipeline/`

Predate the current Makefile targets; superseded by `make rehome-normalize-plan` and `make rehome-safe-auto`.

```
rehome-15_regen-ordered-and-run-batch.sh
rehome-20_normalize-refresh-plan_with-logs.sh
rehome-21_normalize-recover-skipped-and-replan_with-logs.sh
rehome-22_normalize-scan-sync-replan_with-logs.sh
rehome-23_normalize-live-prefix-hash-sync-replan_with-logs.sh
rehome-24_normalize-plan-dry-apply_with-logs.sh
rehome-30_nohl-discover-and-rank.sh
rehome-40_nohl-build-group-plan.sh
rehome-50_nohl-dryrun-group-batch.sh
rehome-55_nohl-fix-target-hash.sh
rehome-56_qb-missing-audit.sh
rehome-57_qb-missing-remediate.sh
rehome-60_nohl-apply-group-batch.sh
rehome-70_nohl-followup-and-reconcile.sh
rehome-80_nohl-report-and-next-batch.sh
rehome-99_qb-checking-watch.sh
rehome-stage0.sh
rehome-05_pilot-batch_plan-and-dryrun.sh
rehome-10_apply-batch-with-guards.sh
db-uuid-migration.sh
```

### 1C. RUN-STATE.md update

Replace `bin/rehome-106_nohl-basics-qb-hash-root-report.sh` with `bin/qb-hash-root-report.sh` in the active toolchain list.

---

## Part 2: The Pilot

### Phase 0 — Pre-flight (run before every phase)

```bash
# 1. Catalog freshness
PYTHONPATH=src python3 -m hashall stats --hash-coverage

# 2. Payload sync must be current
make payload-sync

# 3. No concurrent mutating qB workflow
# Check ps/screen for qb-stoppeddl-apply.py, qb-repair-*, qbit-repair-batch.sh

# 4. qBittorrent accessible
curl -s http://localhost:8080/api/v2/app/version

# 5. Tests pass
python -m pytest tests/test_rehome_*.py -q

# 6. No stale rehome lock
ls -la ~/.hashall/rehome.lock 2>/dev/null || echo "no lock — ok"
```

DB refresh (`./bin/codex-says-run-this-next.sh`) only needed if catalog > 24h stale.

### Phase 1 — Crawl: 1 torrent | Status: Pending

**Goal:** Prove end-to-end plan → apply → verify cycle works against real qB.

```bash
# Dry-run
make rehome-safe-auto REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data REHOME_SAFE_LIMIT=1

# Review output: decision=MOVE, source=/stash/media/..., target=/pool/data/seeds/..., no ALARM

# Apply
make rehome-safe-auto REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data REHOME_SAFE_LIMIT=1 REHOME_SAFE_APPLY=1

# Gate check
make rehome-safe-verify
```

**Pass criteria:**
- `rehome-safe-verify` gates: all GREEN
- qBittorrent state: `stalledUP` or `seeding`, progress=100%
- save_path points to pool path
- Post-apply summary: 0 ALARM rows

**Gate failure → stop, fix code, re-run Phase 1 from scratch.**

### Phase 2 — Walk-1: 5 torrents | Status: Blocked on Phase 1

```bash
make rehome-safe-auto REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data REHOME_SAFE_LIMIT=5
make rehome-safe-auto REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data REHOME_SAFE_LIMIT=5 REHOME_SAFE_APPLY=1
make rehome-safe-verify
make rehome-safe-cleanup
```

**Concurrency test (optional):** While apply running in terminal A, start second apply in terminal B. Expected: immediate "lock_held_by_pid" error.

### Phase 3 — Walk-2: 15 torrents | Status: Blocked on Phase 2

```bash
make rehome-safe-auto REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data REHOME_SAFE_LIMIT=15
make rehome-safe-auto REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data REHOME_SAFE_LIMIT=15 REHOME_SAFE_APPLY=1
make rehome-safe-verify
make rehome-followup REHOME_FOLLOWUP_CLEANUP=1
```

### Phase 4 — Run: Production batches | Status: Blocked on Phase 3

```bash
./bin/codex-says-run-this-next.sh   # Full DB refresh before production run

make rehome-safe-auto REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data REHOME_SAFE_LIMIT=50
make rehome-safe-auto REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data REHOME_SAFE_LIMIT=50 REHOME_SAFE_APPLY=1
make rehome-safe-verify
make rehome-safe-cleanup
make rehome-followup REHOME_FOLLOWUP_CLEANUP=1
# Repeat with increasing limits
```

---

## Code Fix Protocol

1. **Stop** — do not retry or advance
2. **Capture** — plan JSONs from `~/.logs/hashall/reports/rehome-plans/`, run log from `~/.logs/hashall/reports/rehome-safe-runs/`
3. **Root-cause** — read the relevant source file
4. **Fix + test:** `python -m pytest tests/test_rehome_*.py -q`
5. **Commit:** `fix(rehome): <description>`
6. **Re-run same phase from scratch** with fresh plan generation

If a torrent is left in bad state: use qBittorrent UI or `qbit-repair-batch.sh` to restore before re-running.

---

## Logs and Artifacts

- Safe run logs: `~/.logs/hashall/reports/rehome-safe-runs/`
- Rehome plan JSONs: `~/.logs/hashall/reports/rehome-plans/`
- Hashall runtime log: `~/.logs/hashall/hashall.log`

---

## Activity Log

### 2026-03-03 — Session 1

- ✅ Hardening plan executed: 6 commits, 13 issues fixed (C1,C3,C6,C7,C8,H1,H2,H3,H4,H5,M3,M5,C10), version bumped to 0.4.0
- ✅ Crawl/walk/run pilot plan written to repo (`docs/operations/REHOME-PILOT-PLAN.md`)
- ✅ Part 1A: Archived 20 nohl-basics scripts → `bin/archive/2026-02-repair/`
- ✅ Part 1B: Archived 20 legacy pipeline scripts → `bin/archive/legacy-pipeline/`
- ✅ Part 1C: Renamed `rehome-106_nohl-basics-qb-hash-root-report.sh` → `bin/qb-hash-root-report.sh`, updated callers in codex-says-run-this-next.sh, full-hashall-db-refresh.sh, RUN-STATE.md
- ✅ Removed 17 test files for archived scripts; fixed test_rehome_106 to reference renamed script; 85 tests passing 0 failing
- ✅ Phase 0 pre-flight: payload-sync ran (5135 processed, 4903 complete). Scans fresh from 2026-03-03 13:23:36 per stats.

### 2026-03-03 — Session 2

- ✅ Discovered correct device IDs: stash=44 (alias "stash"), pool=231 (alias "pool"). Plan doc was wrong (49/44 from pre-reboot IDs). Renamed catalog alias "data" → "pool" to avoid confusion with /data/media.
- ✅ Root-caused 0 MOVE candidates: 7,347 ghost payloads had device_id=49 (old stash) — `register_or_update_device()` renamed `files_49→files_44` but did NOT update `payloads.device_id`. Orphan GC blocked by spike-protection (7,331 > limit=1000).
- ✅ Catalog cleanup (with backup): deleted 7,331 device-49 orphan payloads (no torrent refs). Deleted 249 device-44 /pool/ payloads (catalog inconsistency, no refs). Kept 16 device-49 + 3 device-44 entries with active torrent refs.
- ✅ Phase 1 dry-run succeeded: West Wing S07 group, 2 stalledUP torrents, decision=REUSE, dryrun_ok=1/1, 0 ALARM rows.
- ✅ Fix 1 — `src/hashall/device.py`: `register_or_update_device()` now migrates `payloads.device_id` when device_id changes. Ghost-payload accumulation permanently closed.
- ✅ Fix 2 — `src/hashall/device.py`: added `resolve_device_id(conn, value)` — accepts alias (e.g. "stash") or integer string, returns current `device_id`.
- ✅ Fix 3 — `src/rehome/cli.py`: `plan`, `plan-batch`, `normalize-plan` now accept `--stash-device`/`--pool-device` as alias or integer (was `type=int` only).
- ✅ Fix 4 — `scripts/rehome_safe_workflow.py`: `--stash-device`/`--pool-device` now accept alias or integer; resolution happens on startup.
- ✅ Makefile + bin scripts: updated all examples and defaults to use stable aliases ("stash", "pool") instead of volatile integers.
- ✅ All `REHOME_STASH_DEVICE=49 REHOME_POOL_DEVICE=44` references replaced with aliases throughout docs.
- 🔲 Phase 1 (crawl) apply: pending — dry-run passed, code fixes committed, ready to run with REHOME_STASH_DEVICE=stash REHOME_POOL_DEVICE=data
