#!/usr/bin/env bash
set -euo pipefail

# Equivalent make command (to generate/refresh report first):
# make recovery-auto RECOVERY_WORKFLOW_PREFIX='<prefix>'

usage() {
  cat <<'EOF'
Usage:
  recovery-10_recovery-auto_show-latest-report-summary.sh [--all] [--top N]

What it does:
  Prints summary/details from latest recovery report JSON and logs with tee.

Modifiers:
  --all        show all units
  --top N      show first N units (default: 30)

Examples:
  recovery-10_recovery-auto_show-latest-report-summary.sh
  recovery-10_recovery-auto_show-latest-report-summary.sh --top 100
  recovery-10_recovery-auto_show-latest-report-summary.sh --all
EOF
}

show_top=30
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --all)
      show_top=0
      shift
      ;;
    --top)
      show_top="${2:-}"
      if [[ -z "$show_top" ]]; then
        echo "ERROR: --top requires a value" >&2
        exit 2
      fi
      shift 2
      ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      echo "Use --help for usage." >&2
      exit 2
      ;;
  esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
mkdir -p out/reports/recovery-workflow
log="out/reports/recovery-workflow/recovery-10-summary-${stamp}.log"

SHOW_TOP="$show_top" python3 - <<'PY' 2>&1 | tee "$log"
import glob, json, sys
import os

show_top = int(os.environ.get("SHOW_TOP", "30"))
paths = sorted(glob.glob('out/reports/recovery-workflow/recovery-workflow-*.json'))
if not paths:
    print('No recovery workflow report found. Run: make recovery-auto')
    sys.exit(1)
p = paths[-1]
d = json.load(open(p))
s = d.get('summary', {})
print(f'report={p}')
print('summary=' +
      f"units:{s.get('unit_count',0)} files:{s.get('file_count',0)} bytes:{s.get('bytes',0)} " +
      f"delete_exact_units:{s.get('delete_exact_units',0)} delete_exact_bytes:{s.get('delete_exact_bytes',0)} " +
      f"pool_supported_units:{s.get('pool_supported_units',0)} review_units:{s.get('review_units',0)}")
units = d.get('units', [])
if show_top > 0:
    units = units[:show_top]
for u in units:
    print(f"{u.get('action')} files={u.get('files')} bytes={u.get('bytes')} live_refs={u.get('live_refs')} unit={u.get('unit_key')}")
PY
echo "log=$log"
