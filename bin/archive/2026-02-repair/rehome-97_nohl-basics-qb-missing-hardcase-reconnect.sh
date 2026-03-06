#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-97_nohl-basics-qb-missing-hardcase-reconnect.sh [options]

Options:
  --audit-json PATH         qB missing audit JSON (default: latest <prefix>-qb-missing-audit-*.json)
  --plan-json PATH          qB remediation plan JSON (default: latest <prefix>-qb-missing-remediate-plan-*.json)
  --mode dryrun|apply       Remediation mode for hard cases (default: dryrun)
  --hard-cause NAME         Root-cause to treat as hard case (repeatable)
  --limit N                 Limit hard-case torrents processed (default: 0 = all)
  --refresh-audit 0|1       Re-run phase 56 before filtering plan (default: 1)
  --rebuild 0|1             Run targeted payload sync hash rebuild first (default: auto: apply=1,dryrun=0)
  --upgrade-root-limit N    Cap targeted rebuild roots (default: 0 = all)
  --workers N               Worker threads for rebuild sync (default: 3)
  --heartbeat-s N           Heartbeat seconds passed to phase 57 (default: 5)
  --output-prefix NAME      Output prefix (default: nohl)
  --fast                    Fast mode annotation
  --debug                   Debug mode annotation
  -h, --help                Show help
USAGE
}

latest_file() {
  local pattern="$1"
  ls -1t $pattern 2>/dev/null | head -n1 || true
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
AUDIT_JSON=""
PLAN_JSON=""
MODE="dryrun"
LIMIT="0"
REFRESH_AUDIT="1"
REBUILD=""
UPGRADE_ROOT_LIMIT="0"
WORKERS="${WORKERS:-3}"
HEARTBEAT_S="${HEARTBEAT_S:-5}"
FAST_MODE=0
DEBUG_MODE=0
declare -a HARD_CAUSES=("ambiguous_root_name_candidates" "db_incomplete_missing_payload")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --audit-json) AUDIT_JSON="${2:-}"; shift 2 ;;
    --plan-json) PLAN_JSON="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --hard-cause) HARD_CAUSES+=("${2:-}"); shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --refresh-audit) REFRESH_AUDIT="${2:-}"; shift 2 ;;
    --rebuild) REBUILD="${2:-}"; shift 2 ;;
    --upgrade-root-limit) UPGRADE_ROOT_LIMIT="${2:-}"; shift 2 ;;
    --workers) WORKERS="${2:-}"; shift 2 ;;
    --heartbeat-s) HEARTBEAT_S="${2:-}"; shift 2 ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
    --debug) DEBUG_MODE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$MODE" != "dryrun" && "$MODE" != "apply" ]]; then
  echo "Invalid --mode: $MODE" >&2
  exit 2
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit: $LIMIT" >&2
  exit 2
fi
if [[ "$REFRESH_AUDIT" != "0" && "$REFRESH_AUDIT" != "1" ]]; then
  echo "Invalid --refresh-audit: $REFRESH_AUDIT" >&2
  exit 2
fi
if [[ -n "$REBUILD" && "$REBUILD" != "0" && "$REBUILD" != "1" ]]; then
  echo "Invalid --rebuild: $REBUILD" >&2
  exit 2
fi
if ! [[ "$UPGRADE_ROOT_LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --upgrade-root-limit: $UPGRADE_ROOT_LIMIT" >&2
  exit 2
fi
if ! [[ "$HEARTBEAT_S" =~ ^[0-9]+$ ]] || [[ "$HEARTBEAT_S" -lt 1 ]]; then
  echo "Invalid --heartbeat-s: $HEARTBEAT_S" >&2
  exit 2
fi

if [[ -z "$REBUILD" ]]; then
  if [[ "$MODE" == "apply" ]]; then
    REBUILD="1"
  else
    REBUILD="0"
  fi
fi

if [[ -z "$AUDIT_JSON" ]]; then
  AUDIT_JSON="$(latest_file "$HOME/.logs/hashall/reports/rehome-normalize/${OUTPUT_PREFIX}-qb-missing-audit-*.json")"
fi
if [[ -z "$PLAN_JSON" ]]; then
  PLAN_JSON="$(latest_file "$HOME/.logs/hashall/reports/rehome-normalize/${OUTPUT_PREFIX}-qb-missing-remediate-plan-*.json")"
fi
if [[ -z "$AUDIT_JSON" || ! -f "$AUDIT_JSON" ]]; then
  echo "Missing audit JSON; run bin/rehome-95_nohl-basics-qb-missing-audit.sh first." >&2
  exit 3
fi
if [[ -z "$PLAN_JSON" || ! -f "$PLAN_JSON" ]]; then
  echo "Missing remediation plan JSON; run bin/rehome-95_nohl-basics-qb-missing-audit.sh first." >&2
  exit 3
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-missing-hardcase-reconnect-${stamp}.log"
hard_hashes_txt="${log_dir}/${OUTPUT_PREFIX}-qb-missing-hardcase-hashes-${stamp}.txt"
hard_prefixes_txt="${log_dir}/${OUTPUT_PREFIX}-qb-missing-hardcase-prefixes-${stamp}.txt"
filtered_plan_json="${log_dir}/${OUTPUT_PREFIX}-qb-missing-hardcase-plan-${stamp}.json"
summary_json="${log_dir}/${OUTPUT_PREFIX}-qb-missing-hardcase-summary-${stamp}.json"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 97: qB missingFiles hard-case reconnect"
echo "What this does: isolate hard missing torrents, rebuild catalog hashes, then run targeted reconnect."
hr
echo "run_id=${stamp} step=basics-qb-missing-hardcase-reconnect"
echo "config mode=${MODE} output_prefix=${OUTPUT_PREFIX} limit=${LIMIT} refresh_audit=${REFRESH_AUDIT} rebuild=${REBUILD} upgrade_root_limit=${UPGRADE_ROOT_LIMIT} workers=${WORKERS} heartbeat_s=${HEARTBEAT_S} fast=${FAST_MODE} debug=${DEBUG_MODE}"
echo "inputs audit_json=${AUDIT_JSON} plan_json=${PLAN_JSON}"

audit_for_filter="$AUDIT_JSON"
plan_for_filter="$PLAN_JSON"

HARD_CAUSES_CSV="$(IFS=,; echo "${HARD_CAUSES[*]}")"
PYTHONPATH=src \
HARD_AUDIT_JSON="$audit_for_filter" \
HARD_LIMIT="$LIMIT" \
HARD_CAUSES_CSV="$HARD_CAUSES_CSV" \
HARD_HASHES_TXT="$hard_hashes_txt" \
HARD_PREFIXES_TXT="$hard_prefixes_txt" \
HARD_SUMMARY_JSON="$summary_json" \
python - <<'PY'
import json
import os
from collections import Counter
from pathlib import Path

audit_json = Path(os.environ["HARD_AUDIT_JSON"])
limit = int(os.environ.get("HARD_LIMIT", "0") or 0)
causes = {c.strip() for c in os.environ.get("HARD_CAUSES_CSV", "").split(",") if c.strip()}
hashes_out = Path(os.environ["HARD_HASHES_TXT"])
prefix_out = Path(os.environ["HARD_PREFIXES_TXT"])
summary_out = Path(os.environ["HARD_SUMMARY_JSON"])

obj = json.loads(audit_json.read_text(encoding="utf-8"))
entries = list(obj.get("entries", []))
selected = []
for e in entries:
    root_cause = str(e.get("root_cause") or "")
    if causes and root_cause not in causes:
        continue
    selected.append(e)

if limit > 0:
    selected = selected[:limit]

hashes = []
prefixes = set()
root_cause_counts: Counter[str] = Counter()
for e in selected:
    torrent_hash = str(e.get("torrent_hash") or "").lower().strip()
    if torrent_hash:
        hashes.append(torrent_hash)
    root_cause = str(e.get("root_cause") or "unknown")
    root_cause_counts[root_cause] += 1
    for key in ("save_path", "content_path", "db_root_path"):
        value = str(e.get(key) or "").strip()
        if value.startswith("/"):
            prefixes.add(value)

hashes = sorted(set(hashes))
prefix_list = sorted(prefixes)

hashes_out.write_text("\n".join(hashes) + ("\n" if hashes else ""), encoding="utf-8")
prefix_out.write_text("\n".join(prefix_list) + ("\n" if prefix_list else ""), encoding="utf-8")

summary = {
    "hard_total": len(hashes),
    "hard_root_causes": dict(root_cause_counts),
    "prefix_count": len(prefix_list),
    "source_audit": str(audit_json),
}
summary_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

print(f"hard_cases={len(hashes)} prefix_count={len(prefix_list)}")
for root_cause, total in sorted(root_cause_counts.items(), key=lambda item: (-item[1], item[0])):
    print(f"hard_cause_count cause={root_cause} total={total}")
print(f"hard_hashes={hashes_out}")
print(f"hard_prefixes={prefix_out}")
print(f"hard_summary_json={summary_out}")
PY

hard_total="$(wc -l < "$hard_hashes_txt" | tr -d ' ')"
if [[ "$hard_total" == "0" ]]; then
  hr
  echo "result=ok step=basics-qb-missing-hardcase-reconnect hard_cases=0 message=no-hard-cases-found"
  hr
  exit 0
fi

if [[ "$REBUILD" == "1" ]]; then
  hr
  echo "phase=hardcase-targeted-payload-sync status=start"
  hr
  sync_cmd=(
    python -m hashall.cli payload sync
    --db /home/michael/.hashall/catalog.db
    --qbit-url "${QBIT_URL:-http://localhost:9003}"
    --qbit-user "${QBIT_USER:-admin}"
    --qbit-pass "${QBIT_PASS:-adminpass}"
    --path-prefix /stash/media
    --path-prefix /data/media
    --path-prefix /pool/data
    --path-prefix-file "$hard_prefixes_txt"
    --upgrade-missing
    --upgrade-order small-first
    --upgrade-root-limit "$UPGRADE_ROOT_LIMIT"
    --workers "$WORKERS"
    --hash-progress full
    --low-priority
  )
  echo "cmd=PYTHONPATH=src ${sync_cmd[*]}"
  PYTHONPATH=src "${sync_cmd[@]}"
  hr
  echo "phase=hardcase-targeted-payload-sync status=done"
  hr
fi

if [[ "$REFRESH_AUDIT" == "1" ]]; then
  refresh_prefix="${OUTPUT_PREFIX}-hardcase"
  audit_cmd=(
    bin/rehome-56_qb-missing-audit.sh
    --output-prefix "$refresh_prefix"
  )
  if [[ "$FAST_MODE" == "1" ]]; then
    audit_cmd+=(--fast)
  fi
  if [[ "$DEBUG_MODE" == "1" ]]; then
    audit_cmd+=(--debug)
  fi
  echo "cmd=${audit_cmd[*]}"
  "${audit_cmd[@]}"
  audit_for_filter="$(latest_file "$HOME/.logs/hashall/reports/rehome-normalize/${refresh_prefix}-qb-missing-audit-*.json")"
  plan_for_filter="$(latest_file "$HOME/.logs/hashall/reports/rehome-normalize/${refresh_prefix}-qb-missing-remediate-plan-*.json")"
  if [[ -z "$audit_for_filter" || -z "$plan_for_filter" ]]; then
    echo "Failed to refresh hardcase audit/plan artifacts." >&2
    exit 4
  fi
fi

PYTHONPATH=src \
HARD_HASHES_TXT="$hard_hashes_txt" \
PLAN_JSON="$plan_for_filter" \
FILTERED_PLAN_JSON="$filtered_plan_json" \
python - <<'PY'
import json
import os
from pathlib import Path

hard_hashes = {
    line.strip().lower()
    for line in Path(os.environ["HARD_HASHES_TXT"]).read_text(encoding="utf-8").splitlines()
    if line.strip()
}
plan_json = Path(os.environ["PLAN_JSON"])
out_json = Path(os.environ["FILTERED_PLAN_JSON"])

plan = json.loads(plan_json.read_text(encoding="utf-8"))
actions = list(plan.get("actions", []))
selected = [a for a in actions if str(a.get("torrent_hash", "")).lower() in hard_hashes]
obj = {
    "generated_at": plan.get("generated_at"),
    "source_plan": str(plan_json),
    "hard_hashes_total": len(hard_hashes),
    "actions_total": len(selected),
    "summary": {
        "actionable": len(selected),
        "hard_hashes_total": len(hard_hashes),
    },
    "actions": selected,
}
out_json.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
print(f"filtered_actions={len(selected)}")
print(f"filtered_plan_json={out_json}")
PY

action_total="$(FILTERED_PLAN_JSON="$filtered_plan_json" python - <<'PY'
import json
import os
from pathlib import Path
p = Path(os.environ["FILTERED_PLAN_JSON"])
obj = json.loads(p.read_text(encoding='utf-8'))
print(int(obj.get('actions_total', 0) or 0))
PY
)"

if [[ "$action_total" == "0" ]]; then
  hr
  echo "result=ok step=basics-qb-missing-hardcase-reconnect hard_cases=${hard_total} actions=0 message=no-safe-actions-for-hard-cases"
  echo "artifacts hard_hashes=${hard_hashes_txt} filtered_plan=${filtered_plan_json} summary=${summary_json}"
  hr
  exit 0
fi

remediate_cmd=(
  bin/rehome-57_qb-missing-remediate.sh
  --plan "$filtered_plan_json"
  --mode "$MODE"
  --limit 0
  --heartbeat-s "$HEARTBEAT_S"
  --output-prefix "${OUTPUT_PREFIX}-hardcase"
)
if [[ "$FAST_MODE" == "1" ]]; then
  remediate_cmd+=(--fast)
fi
if [[ "$DEBUG_MODE" == "1" ]]; then
  remediate_cmd+=(--debug)
fi

hr
echo "phase=hardcase-remediate status=start mode=${MODE} actions=${action_total}"
hr
echo "cmd=${remediate_cmd[*]}"
"${remediate_cmd[@]}"

hr
echo "result=ok step=basics-qb-missing-hardcase-reconnect hard_cases=${hard_total} actions=${action_total} mode=${MODE} run_log=${run_log}"
echo "artifacts hard_hashes=${hard_hashes_txt} hard_prefixes=${hard_prefixes_txt} filtered_plan=${filtered_plan_json} summary=${summary_json}"
hr
