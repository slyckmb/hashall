#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-104_nohl-basics-qb-build-clean-mapping.sh [options]

What this does:
  - Reads Phase 101 mapping JSON
  - Reads Phase 103 ownership-audit JSON
  - Removes all hashes present in audit conflicts
  - Writes a conflict-free mapping JSON for safe pilot runs

Options:
  --mapping-json PATH   Phase 101 mapping JSON (default: latest nohl file)
  --audit-json PATH     Phase 103 audit JSON (default: latest nohl file)
  --baseline-json PATH  Phase 100 baseline JSON (default: latest nohl file)
  --block-conflict-types CSV
                        Conflict types that should be removed from mapping.
                        Default: all conflict types (legacy behavior).
                        Example: shared_target_payload,target_owned_by_other_hash
  --list-conflict-types Print conflict types found in audit JSON and exit
  --clean-map PATH      Output clean mapping JSON (default: /tmp/nohl-qb-candidate-mapping-clean-<stamp>.json)
  -h, --help            Show help
USAGE
}

latest_mapping() {
  ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/nohl-qb-candidate-mapping-*.json 2>/dev/null | head -n1 || true
}

latest_audit() {
  ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/nohl-qb-payload-ownership-audit-*.json 2>/dev/null | head -n1 || true
}

latest_baseline() {
  ls -1t "$HOME"/.logs/hashall/reports/rehome-normalize/nohl-qb-repair-baseline-*.json 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

MAPPING_JSON=""
AUDIT_JSON=""
BASELINE_JSON=""
CLEAN_MAP=""
BLOCK_CONFLICT_TYPES="${BLOCK_CONFLICT_TYPES:-}"
LIST_CONFLICT_TYPES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mapping-json) MAPPING_JSON="${2:-}"; shift 2 ;;
    --audit-json) AUDIT_JSON="${2:-}"; shift 2 ;;
    --baseline-json) BASELINE_JSON="${2:-}"; shift 2 ;;
    --block-conflict-types) BLOCK_CONFLICT_TYPES="${2:-}"; shift 2 ;;
    --list-conflict-types) LIST_CONFLICT_TYPES=1; shift ;;
    --clean-map) CLEAN_MAP="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$MAPPING_JSON" ]]; then
  MAPPING_JSON="$(latest_mapping)"
fi
if [[ -z "$AUDIT_JSON" ]]; then
  AUDIT_JSON="$(latest_audit)"
fi
if [[ -z "$BASELINE_JSON" ]]; then
  BASELINE_JSON="$(latest_baseline)"
fi

if [[ -z "$MAPPING_JSON" || ! -f "$MAPPING_JSON" ]]; then
  echo "Missing/invalid --mapping-json" >&2
  exit 3
fi
if [[ -z "$AUDIT_JSON" || ! -f "$AUDIT_JSON" ]]; then
  echo "Missing/invalid --audit-json" >&2
  exit 3
fi
if [[ -z "$BASELINE_JSON" || ! -f "$BASELINE_JSON" ]]; then
  echo "Missing/invalid --baseline-json" >&2
  exit 3
fi

if [[ -z "$CLEAN_MAP" ]]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  CLEAN_MAP="/tmp/nohl-qb-candidate-mapping-clean-${STAMP}.json"
fi

python3 - "$MAPPING_JSON" "$AUDIT_JSON" "$CLEAN_MAP" "$BLOCK_CONFLICT_TYPES" "$LIST_CONFLICT_TYPES" <<'PY'
import json
import sys
from pathlib import Path

mapping_path = Path(sys.argv[1])
audit_path = Path(sys.argv[2])
clean_path = Path(sys.argv[3])
block_csv = str(sys.argv[4] or "").strip()
list_only = str(sys.argv[5] or "0").strip().lower() in {"1", "true", "yes", "on"}

mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
audit = json.loads(audit_path.read_text(encoding="utf-8"))

all_types = set()
conflicts_by_hash = {}
for row in audit.get("conflicts", []):
    h = str(row.get("hash", "")).lower().strip()
    if not h:
        continue
    types = {
        str(c).strip()
        for c in (row.get("conflicts") or [])
        if str(c).strip()
    }
    if not types:
        continue
    conflicts_by_hash[h] = types
    all_types.update(types)

if list_only:
    for item in sorted(all_types):
        print(item)
    raise SystemExit(0)

if not block_csv or block_csv.lower() == "all":
    blocked_types = set(all_types)
else:
    blocked_types = {
        part.strip()
        for part in block_csv.split(",")
        if part.strip()
    }

conflict_hashes = {
    h for h, types in conflicts_by_hash.items()
    if types & blocked_types
}

matched_type_counts = {}
for blocked in sorted(blocked_types):
    matched_type_counts[blocked] = sum(
        1 for types in conflicts_by_hash.values() if blocked in types
    )

entries = list(mapping.get("entries", []))
clean_entries = [
    row
    for row in entries
    if str(row.get("hash", "")).lower() not in conflict_hashes
]

out = dict(mapping)
out["entries"] = clean_entries
out["_filtered_from_mapping_json"] = str(mapping_path)
out["_filtered_from_audit_json"] = str(audit_path)
out["_filtered_conflict_hash_count"] = len(conflict_hashes)
out["_filtered_entry_count"] = len(clean_entries)
out["_filtered_block_conflict_types"] = sorted(blocked_types)
out["_filtered_available_conflict_types"] = sorted(all_types)
out["_filtered_matched_conflict_type_counts"] = matched_type_counts

clean_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

print(f"mapping_entries={len(entries)}")
print(f"conflict_hashes={len(conflict_hashes)}")
print(f"clean_entries={len(clean_entries)}")
print(
    "block_conflict_types="
    + (",".join(sorted(blocked_types)) if blocked_types else "none")
)
print(f"clean_map={clean_path}")
PY

if [[ "$LIST_CONFLICT_TYPES" -eq 1 ]]; then
  exit 0
fi

echo "baseline_json=${BASELINE_JSON}"
echo "next_1=bin/rehome-103_nohl-basics-qb-payload-ownership-audit.sh --mapping-json ${CLEAN_MAP} --baseline-json ${BASELINE_JSON}"
echo "next_2=bin/rehome-102_nohl-basics-qb-repair-pilot.sh --mode dryrun --limit 10 --candidate-top-n 3 --candidate-fallback --mapping-json ${CLEAN_MAP} --baseline-json ${BASELINE_JSON}"
