#!/usr/bin/env bash
set -euo pipefail

# Equivalent command:
# python3 <query latest recovery-workflow-*.json + list files_49 active rows by unit prefix>

usage() {
  cat <<'EOF'
Usage:
  recovery-25_recovery-auto_list-files-by-unit.sh [--unit UNIT] [--limit N]

What it does:
  Lists active files (size + path) for units from the latest recovery workflow report.
  Output is logged with tee.

Options:
  --unit UNIT   only list one unit (e.g., public/RecycleBin)
  --limit N     max files per unit (default: 50)
  -h, --help    show this help

Examples:
  recovery-25_recovery-auto_list-files-by-unit.sh
  recovery-25_recovery-auto_list-files-by-unit.sh --unit public/RecycleBin --limit 200
EOF
}

unit=""
limit=50
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --unit)
      unit="${2:-}"
      if [[ -z "$unit" ]]; then
        echo "ERROR: --unit requires a value" >&2
        exit 2
      fi
      shift 2
      ;;
    --limit)
      limit="${2:-}"
      if [[ -z "$limit" ]]; then
        echo "ERROR: --limit requires a value" >&2
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
mkdir -p $HOME/.logs/hashall/reports/recovery-workflow
log="$HOME/.logs/hashall/reports/recovery-workflow/recovery-25-list-files-${stamp}.log"

UNIT_FILTER="$unit" LIMIT="$limit" python3 - <<'PY' 2>&1 | tee "$log"
import glob, json, os, sqlite3, sys

unit_filter = os.environ.get("UNIT_FILTER", "").strip()
limit = int(os.environ.get("LIMIT", "50"))

reports = sorted(glob.glob('$HOME/.logs/hashall/reports/recovery-workflow/recovery-workflow-*.json'))
if not reports:
    print('No recovery workflow report found. Run: make recovery-auto')
    sys.exit(1)

report_path = reports[-1]
report = json.load(open(report_path))
prefix = report['recovery_rel']

db_uri = 'file:/home/michael/.hashall/catalog.db?mode=ro&immutable=1'
con = sqlite3.connect(db_uri, uri=True)

print(f'report={report_path}')
print(f'prefix={prefix}')
print(f'unit_filter={unit_filter or "(all)"}')
print(f'limit={limit}')

units = report.get('units', [])
if unit_filter:
    units = [u for u in units if u.get('unit_key') == unit_filter]
    if not units:
        print(f'No unit found: {unit_filter}')
        sys.exit(2)

for u in units:
    unit = str(u.get('unit_key') or '')
    unit_prefix = f"{prefix}/{unit}" if unit else prefix
    print(f"\n=== {unit} | files={u.get('files')} bytes={u.get('bytes')} action={u.get('action')} ===")
    rows = con.execute(
        "SELECT path,size FROM files_49 WHERE status='active' AND (path=? OR path LIKE ?) ORDER BY size DESC LIMIT ?",
        (unit_prefix, unit_prefix + '/%', limit),
    ).fetchall()
    if not rows:
        print('(no active rows found)')
        continue
    for path, size in rows:
        print(f"{int(size):>12}  {path}")

con.close()
PY

echo "log=$log"
