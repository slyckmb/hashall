#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-103_nohl-basics-qb-repair-continue.sh [options]

What this does:
  - Reads a Phase 102 result JSON
  - Extracts failed hashes
  - Filters those hashes from a Phase 101 mapping JSON
  - Runs Phase 102 again with the filtered mapping

Options:
  --result-json PATH    Required: nohl-qb-repair-pilot-result-*.json
  --mapping-json PATH   Required: nohl-qb-candidate-mapping-*.json
  --mode MODE           dryrun | apply (default: dryrun)
  --limit N             Passed to phase 102 (default: 100)
  -h, --help            Show help
USAGE
}

RESULT_JSON=""
MAPPING_JSON=""
MODE="${MODE:-dryrun}"
LIMIT="${LIMIT:-100}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --result-json) RESULT_JSON="${2:-}"; shift 2 ;;
    --mapping-json) MAPPING_JSON="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$RESULT_JSON" || ! -f "$RESULT_JSON" ]]; then
  echo "Missing/invalid --result-json" >&2
  exit 3
fi
if [[ -z "$MAPPING_JSON" || ! -f "$MAPPING_JSON" ]]; then
  echo "Missing/invalid --mapping-json" >&2
  exit 3
fi
if [[ "$MODE" != "dryrun" && "$MODE" != "apply" ]]; then
  echo "Invalid --mode: $MODE" >&2
  exit 2
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit: $LIMIT" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(date +%Y%m%d-%H%M%S)"

failed_txt="${log_dir}/nohl-qb-repair-failed-hashes-${stamp}.txt"
filtered_map="${log_dir}/nohl-qb-candidate-mapping-filtered-${stamp}.json"

python3 - "$RESULT_JSON" "$MAPPING_JSON" "$failed_txt" "$filtered_map" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
mapping_path = Path(sys.argv[2])
failed_txt = Path(sys.argv[3])
filtered_path = Path(sys.argv[4])

result = json.loads(result_path.read_text(encoding="utf-8"))
mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

failed = sorted({
    str(item.get("hash", "")).lower()
    for item in result.get("results", [])
    if str(item.get("status", "")).lower() == "error" and str(item.get("hash", "")).strip()
})

entries = list(mapping.get("entries", []))
filtered_entries = [
    e for e in entries
    if str(e.get("hash", "")).lower() not in set(failed)
]

failed_txt.write_text("\n".join(failed) + ("\n" if failed else ""), encoding="utf-8")

out = dict(mapping)
out["entries"] = filtered_entries
out["_filtered_from"] = str(mapping_path)
out["_filtered_at"] = filtered_path.stem.rsplit("-", 1)[-1]
out["_failed_hash_count"] = len(failed)
out["_filtered_entry_count"] = len(filtered_entries)

filtered_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

print(f"failed_hashes={len(failed)}")
print(f"original_entries={len(entries)}")
print(f"filtered_entries={len(filtered_entries)}")
print(f"failed_hashes_path={failed_txt}")
print(f"filtered_mapping_path={filtered_path}")
PY

echo "Running phase 102 with filtered mapping..."
cmd=(bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode "$MODE" --limit "$LIMIT" --mapping-json "$filtered_map")
printf 'cmd=%q ' "${cmd[@]}"; echo
"${cmd[@]}"
