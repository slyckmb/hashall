---
id: J03-T04
job: 3-pending-repairs
slug: class4-audit
task_type: discovery
status: done
brief_revision_id: 1
agent_start_timestamp: 2026-06-12T14:50:32Z
agent_end_timestamp: 2026-06-12T14:52:00Z
brief_freeze_violation: "false"
---

# J03-T04 — Class 4 Audit (_rehome-unique items) — TASK LOG

## Verification

- Branch: `cr/hashall-20260530-000517-claude__j03` ✓
- HEAD: `c92d2b9530218f38db01cb91f5f649757188b4be` ✓
- Working tree: clean (untracked: `docs/project/LEAD-AGENT-PROTOCOL.md`, `jobs/`) ✓

## Enumeration Results

### Roots scanned

| Root | Path | Count |
|------|------|-------|
| data | /data/media/torrents/seeding/_rehome-unique/ | 47 dirs |
| stash | /stash/media/torrents/seeding/_rehome-unique/ | 47 dirs (mirrors data) |
| pool | /pool/media/torrents/seeding/_rehome-unique/ | 37 dirs |
| cross-seed/data | /data/media/torrents/seeding/cross-seed/ | 0 nested _rehome-unique |
| cross-seed/pool | /pool/media/torrents/seeding/cross-seed/ | 0 nested _rehome-unique |

### Unique hashes: 84 (data+stash: 47, pool: 37, zero overlap)

### Classification

| Group | Description | Count |
|-------|-------------|-------|
| A | Has real files | 50 (26 data+stash, 24 pool) |
| B | Empty dir | 34 (21 data+stash, 13 pool) |
| C | Nested under cross-seed/ | 0 |

**Total unique hashes: 84**

### Known J03-T02b hashes

| Hash | Root(s) | Group |
|------|---------|-------|
| ef48a9203545aa79 | data, stash (stoppedDL 0%) | B — empty dir |
| 8e438130b0727088 | pool (stoppedDL 0%) | B — empty dir |

### Sample paths — Group A (has files)

```
/data/.../32900054c975e0b6/The.Long.Walk.2025.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX.mkv
/pool/.../b1f5461d77581415/Twisters.2024.1080p.WEB-DL.DDP5.1.Atmos.H.264-FLUX.mkv
/data/.../f01b4a9e2f7604c0/    (has 1 file)
/data/.../8eb1869ea709f0fc/    (has 1 file)
/pool/.../ad66d500ad151393/    (has 1 file)
```

### Sample paths — Group B (empty dir)

```
/data/.../ef48a9203545aa79/    (empty, only . and ..)
/data/.../4c11952b384007cf/    (empty)
/data/.../e4a7ee7a66f78920/    (empty)
/pool/.../8e438130b0727088/    (empty)
/pool/.../0c4c7481cd3776b0/    (empty)
```

## Artifacts

```
total_class4=84
group_a_count=50
group_b_count=34
group_c_count=0
stash_count=47
pool_count=37
```

## Agent Report

```
🟪 task-log=J03-T04_class4-audit 🟪

status="done"
task_id="J03-T04"
task_type="discovery"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="84 unique _rehome-unique hashes enumerated across data/stash/pool; 50 group A (with data), 34 group B (empty), 0 group C (nested cross-seed). Known hashes ef48a920 and 8e438130 confirmed present, both Group B."
artifacts="enumeration below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="total_class4=84 exceeds expected ~64 per J02-T03 by 20 items. All within stop_if threshold (200). No other issues."
next="Lead to decide repair scope based on classification"

total_class4=84
group_a_count=50
group_b_count=34
group_c_count=0
stash_count=47
pool_count=37

--- Full enumeration (84 unique hashes) ---

Group A (50) — has real files:
  data/stash: 32900054c975e0b6, 4e76c737a19dec6c, 8eb1869ea709f0fc, 92007a35ba823a53, 962fa894aa44e86b, 9a8d4b9592274023, 9dd2d0e470f6e2f9, 9df8ac64699d28d3, a8af4f41b58bafae, ab1238a6a693ee62, b198bd13dc1f3ba1, c53daa21fa38470a, db9b629789ef3576, df66e43e258343a6, e4bd3d9868ebe3b7, e55ef154dc57e7ae, e8fc4b5580b403d4, ea06d9cc314097b7, f01b4a9e2f7604c0, f22907380c912fb4, f304508922356ad6, f3788d797f2616ef, f55b6bc4e15c328f, f6743028102a4232, fd819fd4c763bd13, ff5b86dd377a5345
  pool: 90eb57bcd3022b45, 91f2eb60225d506f, 91f94c787d172bdf, 929eca448f8f5d88, 936536e29b34efb4, 95df30b0b2598290, a5872c9b6a5c2fd6, ac3f3946c821f8ca, ad044b60776e3c1a, ad66d500ad151393, af391a9fb7b7559c, af6a474297c2e3b8, affbfaa654f330b2, b1f5461d77581415, b31d2f8398b6f573, b5bf2f6575d275c7, b8a9a812eabaa1dd, bb559cf4100e2eaf, bc27a71a63e0801d, c016528919306132, c92747e3ef914391, ceae1e91603514fa, d574c5b97d9fe56a, d9e467dcf6214115

Group B (34) — empty dir:
  data/stash: 4c11952b384007cf, 4f454ed3bdf830f0, 5c8d678c44ff4db6, 649678100037c065, 673b50c100a11abf, 72528155bc815e06, 725970107082fa5e, 7cdf8adcbf87f8de, 81bff5a107550f26, 89d308f1fbf4a143, 8b4e89f6d50be1ce, 8b8c27590b7db960, cea186ce90567fe8, dcdb0bcf78dbe083, e4a7ee7a66f78920, e6afc3604ab9e972, eb7a849344b687ea, ed27911b6a050cba, ef48a9203545aa79, f38a29c856e9510f, f54bc763c72dbacb
  pool: 0c4c7481cd3776b0, 228eca6edac19bb9, 27978e6e879a1c4a, 2efbeab815daf10f, 2f64f48d0b3e965e, 314034000f91a460, 3af5a85cf2929786, 3e7914b7b3fc4230, 3e9fdc1ae43277c0, 89d921b5d4ef1645, 8a387cf57f79dd3f, 8e438130b0727088, e7f00a034a3b1cc3

Group C (0) — nested under cross-seed/:
  (none found)

🟪 task-log=J03-T04_class4-audit 🟪
```
