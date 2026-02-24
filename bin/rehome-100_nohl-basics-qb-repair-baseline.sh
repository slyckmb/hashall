#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-100_nohl-basics-qb-repair-baseline.sh [options]

Options:
  --output-prefix NAME     Output prefix (default: nohl)
  --limit N                Limit queue rows (default: 0 = all)
  --include-state STATE    Include additional state (repeatable)
  --fast                   Fast mode annotation
  --debug                  Debug mode annotation
  -h, --help               Show help
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

OUTPUT_PREFIX="${OUTPUT_PREFIX:-nohl}"
LIMIT="${LIMIT:-0}"
FAST="${FAST:-1}"
DEBUG="${DEBUG:-1}"
QBIT_URL="${QBIT_URL:-http://localhost:9003}"
QBIT_USER="${QBIT_USER:-admin}"
QBIT_PASS="${QBIT_PASS:-adminpass}"
declare -a EXTRA_STATES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --include-state) EXTRA_STATES+=("${2:-}"); shift 2 ;;
    --fast) FAST=1; shift ;;
    --debug) DEBUG=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit: $LIMIT" >&2
  exit 2
fi

log_dir="$HOME/.logs/hashall/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-basics-qb-repair-baseline-${stamp}.log"
json_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-baseline-${stamp}.json"
tsv_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-baseline-${stamp}.tsv"
hashes_out="${log_dir}/${OUTPUT_PREFIX}-qb-repair-queue-hashes-${stamp}.txt"

exec > >(tee "$run_log") 2>&1

hr
echo "Phase 100: qB repair baseline snapshot"
echo "What this does: freeze stoppedDL/error queue with path existence checks."
hr
echo "run_id=${stamp} step=basics-qb-repair-baseline output_prefix=${OUTPUT_PREFIX} limit=${LIMIT} fast=${FAST} debug=${DEBUG} qbit_url=${QBIT_URL}"

extra_states_csv="$(IFS=,; echo "${EXTRA_STATES[*]}")"

PYTHONPATH=src \
BASELINE_LIMIT="$LIMIT" \
BASELINE_EXTRA_STATES="$extra_states_csv" \
BASELINE_JSON_OUT="$json_out" \
BASELINE_TSV_OUT="$tsv_out" \
BASELINE_HASHES_OUT="$hashes_out" \
python - <<'PY'
import csv
import json
import os
from datetime import datetime
from pathlib import Path

from hashall.qbittorrent import get_qbittorrent_client

limit = int(os.environ.get("BASELINE_LIMIT", "0") or 0)
extra_states = {
    s.strip().lower()
    for s in os.environ.get("BASELINE_EXTRA_STATES", "").split(",")
    if s.strip()
}
json_out = Path(os.environ["BASELINE_JSON_OUT"])
tsv_out = Path(os.environ["BASELINE_TSV_OUT"])
hashes_out = Path(os.environ["BASELINE_HASHES_OUT"])

target_states = {"stoppeddl", "missingfiles"} | extra_states

qb = get_qbittorrent_client(
    base_url=os.getenv("QBIT_URL", "http://localhost:9003"),
    username=os.getenv("QBIT_USER", "admin"),
    password=os.getenv("QBIT_PASS", "adminpass"),
)
rows = qb.get_torrents()

queue = []
for t in rows:
    state = str(t.state or "")
    state_l = state.lower()
    if state_l in target_states or "error" in state_l:
        save_path = str(t.save_path or "")
        content_path = str(t.content_path or "")
        save_exists = Path(save_path).exists() if save_path else False
        content_exists = Path(content_path).exists() if content_path else False
        queue.append(
            {
                "hash": str(t.hash).lower(),
                "name": str(t.name or ""),
                "state": state,
                "progress": float(t.progress or 0.0),
                "amount_left": int(t.amount_left or 0),
                "save_path": save_path,
                "content_path": content_path,
                "save_exists": bool(save_exists),
                "content_exists": bool(content_exists),
                "tags": str(t.tags or ""),
                "category": str(t.category or ""),
                "size": int(t.size or 0),
            }
        )

queue.sort(
    key=lambda r: (
        0 if r["state"].lower() == "missingfiles" else 1,
        -int(r["amount_left"]),
        r["hash"],
    )
)
if limit > 0:
    queue = queue[:limit]

summary = {
    "generated_at": datetime.now().isoformat(timespec="seconds"),
    "queue_total": len(queue),
    "state_counts": {},
    "save_missing": 0,
    "content_missing": 0,
    "target_states": sorted(target_states),
}
for r in queue:
    summary["state_counts"][r["state"]] = summary["state_counts"].get(r["state"], 0) + 1
    if not r["save_exists"]:
        summary["save_missing"] += 1
    if not r["content_exists"]:
        summary["content_missing"] += 1

payload = {"summary": summary, "entries": queue}
json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

fieldnames = [
    "hash",
    "state",
    "progress",
    "amount_left",
    "save_exists",
    "content_exists",
    "save_path",
    "content_path",
    "category",
    "tags",
    "name",
]
with tsv_out.open("w", encoding="utf-8", newline="") as fh:
    writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    for r in queue:
        writer.writerow({k: r.get(k, "") for k in fieldnames})

hashes_out.write_text(
    "\n".join(sorted({str(r["hash"]).lower() for r in queue if r.get("hash")})) + "\n",
    encoding="utf-8",
)

print(
    "summary "
    f"queue_total={summary['queue_total']} "
    f"states={summary['state_counts']} "
    f"save_missing={summary['save_missing']} "
    f"content_missing={summary['content_missing']}"
)
print(f"json_output={json_out}")
print(f"tsv_output={tsv_out}")
print(f"hashes_output={hashes_out}")
PY

hr
echo "result=ok step=basics-qb-repair-baseline run_log=${run_log}"
echo "json_output=${json_out}"
echo "tsv_output=${tsv_out}"
echo "hashes_output=${hashes_out}"
hr
