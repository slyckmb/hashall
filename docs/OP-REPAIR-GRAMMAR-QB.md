# OP-REPAIR-GRAMMAR-QB — Recover English Grammar Boot Camp stoppedDL in qB

**Date:** 2026-06-20  
**Hash:** `4bf5c39fea1a33415c47170fdbc4e4da41bdb383`  
**Status:** stoppedDL, 99.88% complete  
**qB save_path:** `/pool/media/torrents/seeding/cross-seed/DocsPedia/`  
**RT state:** SU, 100%, same path — data confirmed present on disk  

---

## Preconditions

- Mutation lock active — no other hashall mutations during this OP
- This is a manual qB-only repair (RT is healthy, no RT writes)

---

## Step 1 — Confirm disk state

```bash
du -sh "/pool/media/torrents/seeding/cross-seed/DocsPedia/English Grammar Boot Camp/"
ls  "/pool/media/torrents/seeding/cross-seed/DocsPedia/English Grammar Boot Camp/"
```

Expected: ~2.5 GB, files present.

## Step 2 — Check old path (pre-rename)

```bash
ls /pool/media/torrents/seeding/DocsPedia/ 2>&1
```

Expected: directory no longer exists (renamed to cross-seed/DocsPedia/ by lane1). If it DOES exist, stop and escalate — data integrity issue.

## Step 3 — Force recheck with correct full hash

```bash
python3 -c "
import requests, time
h = '4bf5c39fea1a33415c47170fdbc4e4da41bdb383'
auth = ('admin','adminadmin')
base = 'http://localhost:9003/api/v2'
r = requests.post(f'{base}/torrents/recheck', data={'hashes': h}, auth=auth)
print('recheck:', r.status_code)
for i in range(60):
    time.sleep(2)
    items = requests.get(f'{base}/torrents/info', params={'hashes': h}, auth=auth).json()
    if not items: continue
    t = items[0]
    print(f'[{i*2}s] {t[\"state\"]} {t[\"progress\"]:.4f}')
    if 'checking' not in t['state']: break
"
```

**If result is stoppedUP or progress=1.0:** pause it, done — proceed to Step 5.  
**If result is stoppedDL at 99.88% again:** proceed to Step 4.

## Step 4 — Resume to allow peer download of missing pieces

> Only do this if Step 3 confirms 99.88% — not a false stoppedDL.

```bash
python3 -c "
import requests, time
h = '4bf5c39fea1a33415c47170fdbc4e4da41bdb383'
auth = ('admin','adminadmin')
base = 'http://localhost:9003/api/v2'

# Resume (will connect to peers and download missing ~3 MB)
r = requests.post(f'{base}/torrents/resume', data={'hashes': h}, auth=auth)
print('resume:', r.status_code)

# Poll until complete or timeout (10 min)
for i in range(300):
    time.sleep(2)
    items = requests.get(f'{base}/torrents/info', params={'hashes': h}, auth=auth).json()
    if not items: continue
    t = items[0]
    if i % 5 == 0:
        print(f'[{i*2}s] {t[\"state\"]} {t[\"progress\"]:.4f} dlspeed={t.get(\"dlspeed\",0)}')
    if t['progress'] >= 1.0 or t['state'] == 'stoppedUP':
        print('COMPLETE')
        break
    if t['state'] == 'stoppedDL' and t['progress'] < 0.999:
        print('STUCK stoppedDL — no peers? Escalate.')
        break
"
```

After completing: pause immediately.
```bash
python3 -c "
import requests
h = '4bf5c39fea1a33415c47170fdbc4e4da41bdb383'
requests.post('http://localhost:9003/api/v2/torrents/pause', data={'hashes': h}, auth=('admin','adminadmin'))
print('paused')
"
```

## Step 5 — Verify final state

```bash
python3 -c "
import requests
r = requests.get('http://localhost:9003/api/v2/torrents/info', params={'limit':5000}, auth=('admin','adminadmin'))
items = [t for t in r.json() if t['state']=='stoppedDL']
print(f'stoppedDL total: {len(items)}')
for t in items: print(t['hash'][:16], t['name'][:50])
"
```

Expected: `4bf5c39f` no longer in stoppedDL list. Total stoppedDL = 5 (the pre-existing RT_INCOMPLETE items).

---

## Escalate if

- Step 2: old path `/pool/media/torrents/seeding/DocsPedia/` still exists with data
- Step 4: torrent stuck stoppedDL, no peers, progress not advancing after 5 min
- New stoppedDL items appear during this OP
