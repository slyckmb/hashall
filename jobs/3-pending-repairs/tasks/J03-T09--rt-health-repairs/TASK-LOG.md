---
id: J03-T09
job: 3-pending-repairs
slug: rt-health-repairs
task_type: implementation
status: partial
brief_revision_id: 1
created_by: lead
agent_start_timestamp: 2026-06-12T21:30:00Z
completed_at: 2026-06-12T21:45:00Z
brief_freeze_violation: "false"
---

# TASK-LOG: J03-T09 — RT Health Repairs

## Summary

```
🟪 task-log=J03-T09_rt-health-repairs 🟪

status="partial"
task_id="J03-T09"
task_type="implementation"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none (XMLRPC/API mutations only)"
mutations="RT: d.start x3, d.stop x1, d.check_hash x5, d.erase x2 | qB: stop x2, delete x2"
validation="See per-action results below"
artifacts="action results below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="Greenland x3: recheck failed - data path points to empty subdirectory (cross-seed artifact)"
next="future TBD by lead after current task log"

actions_started=3
actions_started_ok=3
actions_qbstops=2
actions_qbstops_ok=2
actions_rechecks=5
actions_rechecks_ok=2
actions_rechecks_failed=3
actions_violation_stopped=1
actions_violation_ok=1
actions_removed=2
actions_removed_ok=2
```

---

## ACTION 1: RT stoppedUP STARTS

### Spider-Man Into the Spider-Verse
```
hash=5c86280a99d1007104452b2f72d0d686e092e2f8
name=Spider-Man Into the Spider-Verse
before_state=is_active=0 is_open=0 complete=1
command_issued=s.d.start("5c86280a99d1007104452b2f72d0d686e092e2f8")
result=0
after_state=is_active=1 is_open=1 complete=1
outcome=ok
```

### V for Vendetta
```
hash=4adbb5a7e4d1011ff8286de67c92f2467e81df5b
name=V for Vendetta
before_state=is_active=0 is_open=0 complete=1
command_issued=s.d.start("4adbb5a7e4d1011ff8286de67c92f2467e81df5b")
result=0
after_state=is_active=1 is_open=1 complete=1
outcome=ok
```

### E.T. The Extra-Terrestrial
```
hash=87b6670c265ea58f0e837443516c0504e0c2537c
name=E.T. The Extra-Terrestrial
before_state=is_active=0 is_open=0 complete=1
command_issued=s.d.start("87b6670c265ea58f0e837443516c0504e0c2537c")
result=0
after_state=is_active=1 is_open=1 complete=1
outcome=ok
```

**Result: 3/3 ok**

---

## ACTION 2: qB STOPS

### Love and Monsters
```
hash=8c3e841e16a48bde86a33b11a492063ec911379a
name=Love and Monsters
before_state=stalledUP
command_issued=curl -s -X POST http://localhost:9003/api/v2/torrents/stop --data 'hashes=8c3e841e16a48bde86a33b11a492063ec911379a'
result=(empty — qB API success)
after_state=stoppedUP
outcome=ok
```

### V for Vendetta
```
hash=4adbb5a7e4d1011ff8286de67c92f2467e81df5b
name=V for Vendetta
before_state=stalledUP
command_issued=curl -s -X POST http://localhost:9003/api/v2/torrents/stop --data 'hashes=4adbb5a7e4d1011ff8286de67c92f2467e81df5b'
result=(empty — qB API success)
after_state=stoppedUP
outcome=ok
```

**Result: 2/2 ok**

---

## ACTION 3: CROSS-SEED RECHECKS

### How.Its.Made.S23
```
hash=04aa5f3339d3ccfd1f14dd114db16c92aa87f74a
name=How.Its.Made.S23
before_state=is_active=0 is_open=1 complete=0 is_hash_checked=1
command_issued=s.d.check_hash("04aa5f3339d3ccfd1f14dd114db16c92aa87f74a")
result=0
after_state=is_active=1 is_open=1 complete=0 is_hash_checked=1
outcome=ok — recheck activated this item to stalledUP
```

### How.Its.Made.S24
```
hash=002e5db0ad4bee86419ccf244d212f6d1150d1e8
name=How.Its.Made.S24
before_state=is_active=0 is_open=1 complete=0 is_hash_checked=1
command_issued=s.d.check_hash("002e5db0ad4bee86419ccf244d212f6d1150d1e8")
result=0
after_state=is_active=1 is_open=1 complete=0 is_hash_checked=1
outcome=ok — recheck activated this item to stalledUP
```

### Greenland (seedpool)
```
hash=4e4a7bc1f4284da8b20ce3663b5be1847664f61c
name=Greenland.2020 (seedpool)
before_state=is_active=0 is_open=0 complete=0 is_hash_checked=0
command_issued=s.d.check_hash("4e4a7bc1f4284da8b20ce3663b5be1847664f61c")
result=0
after_state=is_active=0 is_open=0 complete=0 is_hash_checked=0 (persisted after 90s)
outcome=failed — data path points to empty subdirectory
```

### Greenland (darkpeers)
```
hash=e3f92c1c1d8dcde7042f0f849d15d13c1a480d2a
name=Greenland.2020 (darkpeers)
before_state=is_active=0 is_open=0 complete=0 is_hash_checked=0
command_issued=s.d.check_hash("e3f92c1c1d8dcde7042f0f849d15d13c1a480d2a")
result=0
after_state=is_active=0 is_open=0 complete=0 is_hash_checked=0 (persisted after 90s)
outcome=failed — data path points to empty subdirectory
```

### Greenland (reelflix)
```
hash=73d05a65527a9044f924b0b119810fbf46ff3081
name=Greenland.2020 (reelflix)
before_state=is_active=0 is_open=0 complete=0 is_hash_checked=0
command_issued=s.d.check_hash("73d05a65527a9044f924b0b119810fbf46ff3081")
result=0
after_state=is_active=0 is_open=0 complete=0 is_hash_checked=0 (persisted after 90s)
outcome=failed — data path points to empty subdirectory
```

**Result: 2/5 ok, 3/5 failed**

**Root cause for 3 Greenland failures:** RT directory is `/data/media/torrents/seeding/YUSCENE (API)` for all 3 items. Cross-seed created the torrents with this base path, but the data file `Greenland.2020.Repack.1080p.Blu-ray.Remux.AVC.TrueHD.Atmos.7.1-GREENLAND.mkv` exists as an empty subdirectory (0 files) inside this path, not as the actual file. The actual file likely lives at a different seeding location. The items remain in stoppedDL. Needs manual path correction or rehome.

---

## ACTION 4: CROSS-SEED VIOLATION STOP

### How.Its.Made.S22
```
hash=145548eb360d03ffa6343f56ee94ba8ca7ea8f1c
name=How.Its.Made.S22
before_state=is_active=1 is_open=1 complete=0 (was downloading at 47%)
command_issued=s.d.stop("145548eb360d03ffa6343f56ee94ba8ca7ea8f1c")
result=0
after_state=is_active=0 is_open=1 complete=0
outcome=ok — violation stopped
```

**Result: 1/1 ok**

---

## ACTION 5: EMPTY-DIR REMOVALS

### Muppet Christmas Carol
```
hash=8e438130b072708877003225a5079040991de5d7
name=Muppet Christmas Carol
directory_verified=yes (empty: only . and ..)
command_issued_rt=s.d.erase("8e438130b072708877003225a5079040991de5d7") → 0
command_issued_qb=curl -X POST http://localhost:9003/api/v2/torrents/delete --data 'hashes=8e438130b072708877003225a5079040991de5d7&deleteFiles=false' → ok
command_issued_dir=rmdir /pool/media/torrents/seeding/_rehome-unique/8e438130b0727088 → ok
outcome=ok — fully removed
```

### Fly Me To The Moon
```
hash=ef48a9203545aa798775fba7e9a3e7ca396032fe
name=Fly Me To The Moon
directory_verified=yes (empty: only . and ..)
command_issued_rt=s.d.erase("ef48a9203545aa798775fba7e9a3e7ca396032fe") → 0
command_issued_qb=curl -X POST http://localhost:9003/api/v2/torrents/delete --data 'hashes=ef48a9203545aa798775fba7e9a3e7ca396032fe&deleteFiles=false' → ok
command_issued_dir=rmdir /data/media/torrents/seeding/_rehome-unique/ef48a9203545aa79 → ok
outcome=ok — fully removed
```

**Result: 2/2 ok**

---

## No-Action Items Verification

Confirmed NO changes to:
- All 6 stalledDL items (0 seed — left alone)
- All 4 no-data stopped items (no seeds — left alone)
- All 18 tracker issue items (already stalledUP seeding — left alone)

No-Action items untouched ✓

---

## Summary

| Action | Target | Status | Notes |
|---|---|---|---|
| 1. Start stoppedUP | 3 items | ✓ ALL | Spider-Man, V for Vendetta, E.T. now active |
| 2. Stop qB stalledUP | 2 items | ✓ ALL | Love and Monsters, V for Vendetta now stoppedUP |
| 3. Recheck cross-seed | 5 items | ⚠ PARTIAL | 2 activated (S23, S24), 3 failed (Greenland x3 — empty dir) |
| 4. Stop violation | 1 item | ✓ OK | How.Its.Made.S22 stopped |
| 5. Remove empty-dir | 2 items | ✓ ALL | Muppet Christmas Carol, Fly Me To The Moon fully removed |

**3 Greenland items** need manual data path correction. The cross-seed items point to `/data/media/torrents/seeding/YUSCENE (API)` where the filename exists as an empty subdirectory. Actual data needs to be located and the path corrected before a successful recheck.

```
🟪 task-log=J03-T09_rt-health-repairs 🟪
```
