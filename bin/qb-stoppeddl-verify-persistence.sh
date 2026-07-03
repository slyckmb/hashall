#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
SEMVER="0.1.0"
LAST_UPDATED="2026-07-03T00:00:00-04:00"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BUCKET_DIR="${BUCKET_DIR:-/tmp/qb-stoppeddl-bucket-live}"
QB_CONTAINER="${QB_CONTAINER:-qbittorrent_vpn}"
RESTART_TIMEOUT="${RESTART_TIMEOUT:-180}"
POLL="${POLL:-5}"
APPLY="false"
HASHES_FILE=""
REPORT_JSON=""
FASTRESUME_DIR="/dump/docker/gluetun_qbit/qbittorrent_vpn/qBittorrent/BT_backup"

ts() { date '+%Y-%m-%dT%H:%M:%S'; }

usage() {
  cat <<'USAGE'
Usage:
  bin/qb-stoppeddl-verify-persistence.sh [options]

Validate that repaired torrents survive a qB restart without reverting to stoppedDL.

Steps:
  1) Pre-flight: check docker, qB container running, take pre-restart state snapshot
  2) Restart: docker stop + docker start (only with --apply)
  3) Post-flight: take post-restart snapshot, compare pre vs post
  4) Report: flag hashes that reverted to stoppedDL, investigate fastresume qBt-downloadPath

Options:
  --bucket-dir PATH           Bucket dir for snapshot storage (default: /tmp/qb-stoppeddl-bucket-live)
  --qb-container NAME         Docker container name (default: qbittorrent_vpn)
  --restart-timeout N         Seconds to wait for qB API after restart (default: 180)
  --poll N                    Poll interval while waiting for API (default: 5)
  --apply                     Actually stop+start docker (default: dry-run)
  --hashes-file PATH          File of hashes to check (default: <bucket>/active-hashes.txt if exists, else all)
  --report-json PATH          Report path (default: <bucket>/reports/persistence-<ts>.json)
  -h, --help                  Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket-dir) BUCKET_DIR="${2:-}"; shift 2 ;;
    --qb-container) QB_CONTAINER="${2:-}"; shift 2 ;;
    --restart-timeout) RESTART_TIMEOUT="${2:-}"; shift 2 ;;
    --poll) POLL="${2:-}"; shift 2 ;;
    --apply) APPLY="true"; shift ;;
    --hashes-file) HASHES_FILE="${2:-}"; shift 2 ;;
    --report-json) REPORT_JSON="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

BUCKET_DIR="$(python3 -c 'import os,sys; print(os.path.expanduser(sys.argv[1]))' "$BUCKET_DIR")"
REPORTS_DIR="${BUCKET_DIR}/reports"
ACTIVE_HASHES_FILE="${BUCKET_DIR}/active-hashes.txt"
SNAPSHOT_DIR="${BUCKET_DIR}/snapshots"
SNAPSHOT_PRE="${SNAPSHOT_DIR}/state-pre.json"
SNAPSHOT_POST="${SNAPSHOT_DIR}/state-post.json"

echo "start ts=$(ts) script=${SCRIPT_NAME} semver=${SEMVER}"
echo "config bucket_dir=${BUCKET_DIR} qb_container=${QB_CONTAINER} restart_timeout=${RESTART_TIMEOUT}s poll=${POLL}s apply=${APPLY}"

mkdir -p "$SNAPSHOT_DIR" "$REPORTS_DIR"

REPORT_JSON="${REPORT_JSON:-${REPORTS_DIR}/persistence-$(date '+%Y%m%d-%H%M%S').json}"
HASHES_FILE="${HASHES_FILE:-${ACTIVE_HASHES_FILE}}"

# ---- Pre-flight ----
if ! command -v docker &>/dev/null; then
  echo "ERROR docker_not_found" >&2
  exit 2
fi

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qxF "$QB_CONTAINER"; then
  echo "ERROR qb_container_not_running container=${QB_CONTAINER}" >&2
  exit 2
fi

# ---- Pre-restart snapshot ----
echo "phase=pre_snapshot ts=$(ts)"
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('$repo_root').resolve() / 'src'))
from hashall.qbittorrent import get_qbittorrent_client

qb = get_qbittorrent_client()
if not qb.test_connection() or not qb.login():
    print('QB_OFFLINE')
    raise SystemExit(1)

rows = qb.get_torrents()
snapshot = {}
for r in rows:
    h = str(r.hash or '').lower()
    if h:
        snapshot[h] = {
            'state': str(r.state or ''),
            'name': str(r.name or ''),
            'save_path': str(r.save_path or ''),
        }
print(json.dumps(snapshot, indent=2))
" > "$SNAPSHOT_PRE"
echo "pre_snapshot path=${SNAPSHOT_PRE} ts=$(ts)"

if [[ "$APPLY" != "true" ]]; then
  hashes_total=$(python3 -c "import json; d=json.load(open('$SNAPSHOT_PRE')); print(len(d))")
  echo "dry_run ts=$(ts) action=dry_run hashes_in_snapshot=${hashes_total}"
  echo "dry_run plan=apply:$QB_CONTAINER stop+start wait_for_api:${RESTART_TIMEOUT}s post_snapshot+compare+investigate"
  echo "dry_run report=${REPORT_JSON}"
  exit 0
fi

# ---- Apply: restart qB ----
echo "phase=restart ts=$(ts) action=docker_stop container=${QB_CONTAINER}"
if ! docker stop "$QB_CONTAINER"; then
  echo "ERROR docker_stop_failed container=${QB_CONTAINER}" >&2
  exit 2
fi

echo "phase=restart ts=$(ts) action=docker_start container=${QB_CONTAINER}"
if ! docker start "$QB_CONTAINER"; then
  echo "ERROR docker_start_failed container=${QB_CONTAINER}" >&2
  exit 2
fi

# ---- Wait for qB API ----
echo "phase=wait_qb ts=$(ts) timeout=${RESTART_TIMEOUT}s poll=${POLL}s"
deadline=$(( $(date +%s) + RESTART_TIMEOUT ))
qb_ok="false"
while [[ $(date +%s) -lt $deadline ]]; do
  if python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('$repo_root').resolve() / 'src'))
from hashall.qbittorrent import get_qbittorrent_client
qb = get_qbittorrent_client()
if qb.test_connection() and qb.login():
    raise SystemExit(0)
raise SystemExit(1)
" 2>/dev/null; then
    qb_ok="true"
    break
  fi
  echo "  wait_qb ts=$(ts) api=offline"
  sleep "$POLL"
done

if [[ "$qb_ok" != "true" ]]; then
  echo "ERROR qb_api_not_online timeout=${RESTART_TIMEOUT}s" >&2
  exit 2
fi
echo "phase=wait_qb ts=$(ts) api=online"

# ---- Post-restart snapshot ----
echo "phase=post_snapshot ts=$(ts)"
python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('$repo_root').resolve() / 'src'))
from hashall.qbittorrent import get_qbittorrent_client

qb = get_qbittorrent_client()
if not qb.test_connection() or not qb.login():
    print('QB_OFFLINE')
    raise SystemExit(1)

rows = qb.get_torrents()
snapshot = {}
for r in rows:
    h = str(r.hash or '').lower()
    if h:
        snapshot[h] = {
            'state': str(r.state or ''),
            'name': str(r.name or ''),
            'save_path': str(r.save_path or ''),
        }
print(json.dumps(snapshot, indent=2))
" > "$SNAPSHOT_POST"
echo "post_snapshot path=${SNAPSHOT_POST} ts=$(ts)"

# ---- Compare snapshots ----
echo "phase=compare ts=$(ts)"
python3 -c "
import json, sys

pre = json.loads(open('$SNAPSHOT_PRE').read())
post = json.loads(open('$SNAPSHOT_POST').read())

reverted = []
for h, pre_info in pre.items():
    post_info = post.get(h, {})
    pre_state = str(pre_info.get('state','')).lower()
    post_state = str(post_info.get('state','')).lower()
    if pre_state != 'stoppeddl' and post_state == 'stoppeddl':
        reverted.append({
            'hash': h,
            'name': pre_info.get('name',''),
            'pre_state': pre_state,
            'post_state': post_state,
        })

if reverted:
    print(f'REVERTED_COUNT={len(reverted)}')
    for r in reverted:
        print(f'REVERTED hash={r[\"hash\"][:12]} name={r[\"name\"][:80]} pre={r[\"pre_state\"]} post={r[\"post_state\"]}')
else:
    print('REVERTED_COUNT=0')
    print('PERSISTENCE_VERIFIED=ok')
"

# ---- Investigate fastresume qBt-downloadPath for reverted hashes ----
echo "phase=investigate ts=$(ts)"
reverted_hashes="$(python3 -c "
import json
pre = json.loads(open('$SNAPSHOT_PRE').read())
post = json.loads(open('$SNAPSHOT_POST').read())
for h, pre_info in pre.items():
    post_state = str(post.get(h, {}).get('state','')).lower()
    pre_state = str(pre_info.get('state','')).lower()
    if pre_state != 'stoppeddl' and post_state == 'stoppeddl':
        print(h)
")"

reverted_count="$(echo "$reverted_hashes" | wc -w)"

if [[ "$reverted_count" -gt 0 ]]; then
  echo "investigate count=${reverted_count}"
  for h in $reverted_hashes; do
    echo "  investigating hash=${h:0:12}"
    python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('$repo_root').resolve() / 'src'))
from hashall.fastresume import read_fastresume
from hashall.bencode import as_text

h = '$h'
fr_path = Path('$FASTRESUME_DIR') / f'{h}.fastresume'
if fr_path.exists():
    doc = read_fastresume(fr_path)
    dl = as_text(doc.get(b'qBt-downloadPath', b'')).strip()
    save = as_text(doc.get(b'save_path', b'')).strip()
    qbt_save = as_text(doc.get(b'qBt-savePath', b'')).strip()
    if dl:
        print(f'  qBt-downloadPath_FOUND hash={h[:12]} downloadPath={dl} save_path={save} qBt-savePath={qbt_save}')
    else:
        print(f'  qBt-downloadPath_ABSENT hash={h[:12]} save_path={save} qBt-savePath={qbt_save}')
else:
    print(f'  fastresume_MISSING hash={h[:12]}')
"
  done
fi

# ---- Build report ----
exit_code=0
if [[ "$reverted_count" -gt 0 ]]; then
  exit_code=1
  echo "summary ts=$(ts) verdict=FAIL reason=new_stoppedDL_found count=${reverted_count}"
else
  echo "summary ts=$(ts) verdict=PASS reason=persistence_verified"
fi

# Write JSON report
python3 -c "
import json
from datetime import datetime

pre = json.loads(open('$SNAPSHOT_PRE').read())
post = json.loads(open('$SNAPSHOT_POST').read())

reverted = []
for h, pre_info in pre.items():
    post_info = post.get(h, {})
    pre_state = str(pre_info.get('state','')).lower()
    post_state = str(post_info.get('state','')).lower()
    if pre_state != 'stoppeddl' and post_state == 'stoppeddl':
        reverted.append({
            'hash': h,
            'name': pre_info.get('name',''),
            'pre_state': pre_state,
            'post_state': post_state,
        })

report = {
    'tool': 'qb-stoppeddl-verify-persistence',
    'script': '$SCRIPT_NAME',
    'semver': '$SEMVER',
    'generated_at': datetime.now().isoformat(timespec='seconds'),
    'bucket_dir': '$BUCKET_DIR',
    'qb_container': '$QB_CONTAINER',
    'apply': $APPLY,
    'exit_code': $exit_code,
    'summary': {
        'pre_count': len(pre),
        'post_count': len(post),
        'reverted_count': len(reverted),
        'persistence_verified': len(reverted) == 0,
    },
    'reverted': reverted,
}
print(json.dumps(report, indent=2))
" > "$REPORT_JSON"
echo "report path=${REPORT_JSON}"

exit "$exit_code"
