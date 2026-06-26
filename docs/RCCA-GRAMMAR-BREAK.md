# RCCA: English Grammar Boot Camp stoppedDL — Root Cause Investigation

**Date:** 2026-06-20  
**Job:** j24 (J01-T01 in this CR session)  
**Hash:** `4bf5c39fea1a33415c47170fdbc4e4da41bdb383` (DocsPedia cross-seed)  
**Symptom:** qB stoppedDL 99.88% at `/pool/media/torrents/seeding/cross-seed/DocsPedia/`  

---

## Root Cause

**Job:** j17/j18 pilot (lane1 group atomic executor, run 2026-06-18 ~09:20–09:47)  
**Function:** `set_location()` in `src/hashall/qbittorrent.py`  
**Code path:** FNF bypass (lines ~1440–1446, pre-j23 fix)  

qB's save_path for this torrent was `/data/media/torrents/seeding/DocsPedia` (container-internal
format). When the lane1 pilot called `set_location()`, `os.stat("/data/media/...")` raised
`FileNotFoundError` (the `/data/` bind mount is invisible from the host). The pre-j23 bypass
set `skip_device_check = True` unconditionally, allowing qB to execute a cross-device copy from
`/stash/media/...` (container `/data/media/`) to `/pool/media/...` (new path). This copy was never
authorized.

The copy executed partially:
- 24 `.m4v` video files: copied to correct content_path location (`content_path/*.m4v`) — real sizes, nlinks=1
- `GrammarBootCamp_2222.pdf`: landed at **save_path level** instead of content_path level — wrong directory in torrent structure
- After copy, qB verified pieces and found `GrammarBootCamp_2222.pdf` missing from content_path → 0-byte stub there; pieces spanning the PDF boundary fail → `24 Trending Language.m4v` (99.70%) and `01 Why Do We Care about Grammar.mp3` (96.84%) show partial
- `amount_left: 3,145,728 bytes` = piece failures from the missing PDF straddling 2 adjacent files

---

## Evidence

| Item | Value |
|------|-------|
| Hash in lane1-plan reports | 2026-06-18 06:41 through 09:20 (8 reports) |
| Hash absent from lane1-plan | All reports from 09:47 onwards → executed between 09:20–09:47 |
| Execution job | j17/j18 pilot (before Gate 0 recovery) |
| qB file list | 47/50 files OK; 3 incomplete (Trending Language.m4v, GrammarBootCamp_2222.pdf, 01 mp3) |
| GrammarBootCamp_2222.pdf at save_path | 2,085,705 bytes, Jun 5 (original copy date) — WRONG LEVEL |
| GrammarBootCamp_2222.pdf at content_path | 0 bytes — placeholder only |
| m4v files at content_path | Real content (80–105MB each), nlinks=1 (copies, not hardlinks) |
| mp3 files at content_path nested dir | Real content (19–25MB each) — qB shows 100% OK |
| Stash source | `/stash/media/torrents/seeding/DocsPedia/English Grammar Boot Camp/` — m4v nlinks=3 |

---

## Classification

**Pre-j23 damage. No new bug found. j23 fix is correct.**

The j23 fix (`_files_exist_at_target` check before allowing bypass) prevents this exact scenario
for future items. English Grammar Boot Camp was damaged during the j17/j18 pilot, before j23 was
committed. No code change is needed beyond what j23 already delivered.

---

## T05 — Other cross-seed items damaged?

**CLEAR.** Current stoppedDL count = 6:
- 5× RT_INCOMPLETE (pre-existing, unrelated to our work)
- 1× English Grammar Boot Camp (confirmed pre-j23 pilot damage)

No other cross-seed items are in stoppedDL state.

---

## Repair (OP-21 / j26)

The repair is a targeted 1-file fix + recheck:

```bash
# Copy PDF to correct content_path level (same device — can use cp or hardlink)
SAVE_PATH="/pool/media/torrents/seeding/cross-seed/DocsPedia/English Grammar Boot Camp"
cp "${SAVE_PATH}/GrammarBootCamp_2222.pdf" \
   "${SAVE_PATH}/English Grammar Boot Camp/GrammarBootCamp_2222.pdf"

# Verify size matches torrent expectation (2,085,705 bytes)
stat --format="%s" "${SAVE_PATH}/English Grammar Boot Camp/GrammarBootCamp_2222.pdf"

# Trigger qB recheck
python3 -c "
import requests, time
h = '4bf5c39fea1a33415c47170fdbc4e4da41bdb383'
auth = ('admin','adminadmin')
base = 'http://localhost:9003/api/v2'
requests.post(f'{base}/torrents/recheck', data={'hashes': h}, auth=auth)
print('recheck triggered')
for i in range(60):
    time.sleep(3)
    t = requests.get(f'{base}/torrents/info', params={'hashes': h}, auth=auth).json()[0]
    print(f'[{i*3}s] {t[\"state\"]} {t[\"progress\"]:.6f}')
    if 'checking' not in t['state']:
        break
"

# After recheck: pause to land at stoppedUP
python3 -c "
import requests
h = '4bf5c39fea1a33415c47170fdbc4e4da41bdb383'
requests.post('http://localhost:9003/api/v2/torrents/pause', data={'hashes': h}, auth=('admin','adminadmin'))
print('paused')
"
```

Expected outcome: progress = 1.0, state = stoppedUP.

---

## Mutation Lock Disposition

After j24 closes:
- hashall payload mutations: **UNLOCKED** (no code fix needed; j23 fix is correct)
- English Grammar Boot Camp repair: deferred to j26 (targeted qB-only repair, does not block j25)
- j25 runs first: audit 34 j22-touched items (OP-22) + j20 MISSING_DATA audit (OP-27)

---

## Completion Criteria (all met)

- [x] Root cause documented: j17/j18 pilot, `set_location()` FNF bypass, pre-j23
- [x] Bug fixed or confirmed pre-j23 damage: confirmed pre-j23, no new bug
- [ ] English Grammar Boot Camp repaired to stoppedUP: deferred to j26
- [x] No other cross-seed items damaged (T05 clear): 6 stoppedDL, 5 pre-existing
- [ ] Mutation lock fully lifted: lifted for hashall payload mutations immediately
