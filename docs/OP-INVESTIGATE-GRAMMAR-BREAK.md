# OP-INVESTIGATE-GRAMMAR-BREAK — Root Cause: English Grammar Boot Camp stoppedDL

**Date:** 2026-06-20  
**Hash:** `4bf5c39fea1a33415c47170fdbc4e4da41bdb383` (DocsPedia cross-seed)  
**Symptom:** qB stoppedDL 99.88% at `/pool/media/torrents/seeding/cross-seed/DocsPedia/`  
**RT state:** SU 100% from same path — data present  
**Mutation lock:** Active until investigation + fix + 4-stage validation complete  

---

## Known Context

From lane1-plan reports (earliest: 2026-06-18 06:41):

| Field | Value |
|-------|-------|
| `item_type` | `cross_seed` |
| `source_dir` | `/pool/media/torrents/seeding/DocsPedia` ← **wrong category (no cross-seed/ prefix)** |
| `target_dir` | `/pool/media/torrents/seeding/cross-seed/DocsPedia/English Grammar Boot Camp` |
| `same_device` | `true` |
| `safe` | `true` |
| Drift type | CATEGORY_DRIFT (same root, wrong category subdir) |

This item was queued for a same-device rename: `DocsPedia/` → `cross-seed/DocsPedia/`.

---

## Investigation Steps

### T01 — Determine which job/commit touched this item

```bash
# Search all execution logs and reports for this hash
grep -r "4bf5c39fea1a" /home/michael/.hashall/reports/ 2>/dev/null
grep -r "4bf5c39fea1a" /home/michael/.hashall/ 2>/dev/null | grep -v reports

# Check git log for lane1 execution commits
git log --oneline --all | grep -i "lane1\|execute\|merge\|j22\|j21\|j20\|j19\|j18\|j17"

# Check which commits touched lane1_execute.py and qbittorrent.py
git log --oneline -- src/hashall/lane1_execute.py src/hashall/qbittorrent.py
```

### T02 — Determine qB save_path BEFORE the rename

The lane1 plan shows `source_dir=/pool/media/torrents/seeding/DocsPedia`. But:
- qB may have been reporting `/data/media/torrents/seeding/DocsPedia` (container path) internally
- If so, `set_location()` would have triggered the FNF bypass bug (j23 root cause)

```bash
# Check if any plan report captures the qB save_path separately from source_dir
python3 -c "
import json, glob
files = sorted(glob.glob('/home/michael/.hashall/reports/lane1-plan-*.json'))
for f in files:
    txt = open(f).read()
    if '4bf5c39fea1a' in txt:
        data = json.load(open(f))
        for item in data:
            if '4bf5c3' in item.get('hash',''):
                print(f'FILE: {f}')
                print(json.dumps(item, indent=2))
                break
"

# Also check the catalog DB for save_path history
hashall payload canonical-path --hash 4bf5c39fea1a33415c47170fdbc4e4da41bdb383
```

### T03 — Trace the exact code path that ran

Identify which executor function was called and what parameters:

1. Was it `execute_lane1_group_atomic()` (whole-dir rename)?
2. Or `execute_lane1b_merge_group()` (per-item merge)?
3. Or the cross-seed dup repoint path in j22?

```bash
# Check lane1_execute.py for cross-seed handling
grep -n "cross_seed\|DocsPedia\|source_dir\|set_location" \
    src/hashall/lane1_execute.py | head -40

# Check j22-specific cross-seed dup repoint code
git show HEAD~3..HEAD -- src/hashall/lane1_execute.py | grep -A 10 -B 5 "cross.seed\|dup"
```

### T04 — Determine why qB shows 99.88% when RT shows 100%

Possible causes (rank by likelihood):

1. **FNF bypass triggered unauthorized cross-device move**: qB executed a container-side copy from `/data/media/.../DocsPedia/` to `/pool/media/.../cross-seed/DocsPedia/`, but the copy was interrupted or partial → 99.88%

2. **Lane1 rename succeeded but qB recheck ran on incomplete file**: Some other process deleted/truncated part of the file between rename and recheck

3. **Torrent piece boundary mismatch**: qB's torrent `4bf5c3` and the actual file on disk have a genuine 0.12% piece mismatch that exists independently of our work (pre-existing but previously masked by downloading from a peer)

4. **qB save_path was `/data/media/...`** (container path): After `set_location` moved it to `/pool/...`, the FNF bypass allowed qB to attempt a cross-device copy internally in the container. RT's `/data/media/DocsPedia/` files were hardlinked to the pool path, so RT still shows 100%. qB's copy was ~99.88% complete when it hit stoppedDL.

```bash
# Check nlinks on the actual files to detect copy vs hardlink
find "/pool/media/torrents/seeding/cross-seed/DocsPedia/English Grammar Boot Camp/" \
    -type f -exec stat --format="%h %s %n" {} \;

# Compare with stash path (if it still exists via RT's data path)
find "/stash/media/torrents/seeding/DocsPedia/" -type f \
    -exec stat --format="%h %i %s %n" {} \; 2>/dev/null
```

### T05 — Check all other cross-seed items for same damage pattern

```bash
# Are there other cross-seed items now at stoppedDL that should be stoppedUP?
python3 -c "
import requests
r = requests.get('http://localhost:9003/api/v2/torrents/info', params={'limit':5000}, auth=('admin','adminadmin'))
items = [t for t in r.json() if t['state']=='stoppedDL']
print(f'{len(items)} stoppedDL items')
for t in items:
    print(t['hash'][:16], t.get('save_path','')[:60], t['name'][:40])
"

# Cross-check: how many cross-seed items are at pool paths (should be stoppedUP)
hashall payload canonical-path --hash 4bf5c39fea1a33415c47170fdbc4e4da41bdb383
```

### T06 — Identify the bug

Based on T01-T05 findings, document:
- Which function/line caused the damage
- What the pre-condition was (qB save_path format at time of call)
- What invariant was violated

Expected finding: one of
- `set_location()` FNF bypass (j23 fixed this — but was this item hit BEFORE j23?)
- `execute_lane1_group_atomic()` didn't verify qB state post-rename
- Cross-seed dup repoint in j22 ran `set_location` on an item where qB had container-format path

---

## Fix Requirements

Once root cause confirmed:

1. If FNF bypass (pre-j23 damage): j23 fix is already in place — the fix is correct. No code change needed. The damage to this one item predates the fix.

2. If new bug found: open new job (j24), apply fix, 4-stage validation before any mutations.

---

## 4-Stage Validation (if new code fix required)

| Gate | What to verify |
|------|---------------|
| Gate 1 | Unit tests pass for fixed function; new test covers the exact failure scenario |
| Gate 2 | Dry-run on English Grammar Boot Camp confirms correct behavior |
| Gate 3 | 5-item pilot on cross-seed CATEGORY_DRIFT items — all reach stoppedUP |
| Gate 4 | Full stoppedDL count = 5 (pre-existing only); no new stoppedDL introduced |

---

## Completion Criteria

- [ ] Root cause documented (which job, which function, which line)
- [ ] Bug fixed (or confirmed pre-j23 damage with no new bug)
- [ ] 4-stage validation passed (if new fix)
- [ ] English Grammar Boot Camp repaired to stoppedUP (via OP-REPAIR-GRAMMAR-QB)
- [ ] No other cross-seed items damaged (T05 clear)
- [ ] Mutation lock lifted
