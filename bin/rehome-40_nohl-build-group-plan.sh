#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-40_nohl-build-group-plan.sh [options]

Options:
  --hashes-file PATH        Ranked payload hash file (default: latest nohl-payload-hashes-ranked-*.txt)
  --db PATH                 Catalog DB path (default: /home/michael/.hashall/catalog.db)
  --stash-device ID         Stash device id (default: 49)
  --pool-device ID          Pool device id (default: 44)
  --limit N                 Limit payload groups from hashes file (default: 0 = all)
  --fast                    Fast mode (minimal per-item diagnostics)
  --debug                   Debug mode (verbose command tracing)
  --output-prefix NAME      Output prefix (default: nohl)
  -h, --help                Show help
USAGE
}

latest_hashes_file() {
  ls -1t out/reports/rehome-normalize/nohl-payload-hashes-ranked-*.txt 2>/dev/null | head -n1
}

HASHES_FILE=""
DB_PATH="/home/michael/.hashall/catalog.db"
STASH_DEVICE_ID="49"
POOL_DEVICE_ID="44"
LIMIT="0"
OUTPUT_PREFIX="nohl"
FAST_MODE=0
DEBUG_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hashes-file) HASHES_FILE="${2:-}"; shift 2 ;;
    --db) DB_PATH="${2:-}"; shift 2 ;;
    --stash-device) STASH_DEVICE_ID="${2:-}"; shift 2 ;;
    --pool-device) POOL_DEVICE_ID="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --fast) FAST_MODE=1; shift ;;
    --debug) DEBUG_MODE=1; shift ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -z "$HASHES_FILE" ]]; then
  HASHES_FILE="$(latest_hashes_file)"
fi
if [[ -z "$HASHES_FILE" || ! -f "$HASHES_FILE" ]]; then
  echo "Missing hashes file; run rehome-30 first or pass --hashes-file" >&2
  exit 3
fi

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-build-group-plan-${stamp}.log"
plan_dir="${log_dir}/${OUTPUT_PREFIX}-plans-${stamp}"
mkdir -p "$plan_dir"
manifest_json="${log_dir}/${OUTPUT_PREFIX}-plan-manifest-${stamp}.json"
plannable_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-plannable-${stamp}.txt"
blocked_hashes="${log_dir}/${OUTPUT_PREFIX}-payload-hashes-blocked-${stamp}.txt"
report_tsv="${log_dir}/${OUTPUT_PREFIX}-plan-report-${stamp}.tsv"

{
  echo "run_id=${stamp} step=nohl-build-group-plan"
  echo "config hashes_file=${HASHES_FILE} db=${DB_PATH} stash_device=${STASH_DEVICE_ID} pool_device=${POOL_DEVICE_ID} limit=${LIMIT} fast=${FAST_MODE} debug=${DEBUG_MODE}"
  PYTHONPATH=src python -u - <<'PY' \
    "$HASHES_FILE" "$DB_PATH" "$STASH_DEVICE_ID" "$POOL_DEVICE_ID" "$LIMIT" "$plan_dir" "$manifest_json" "$plannable_hashes" "$blocked_hashes" "$report_tsv" "$FAST_MODE" "$DEBUG_MODE"
import json
import time
import subprocess
import sys
from pathlib import Path

(
    hashes_file,
    db_path,
    stash_device_id,
    pool_device_id,
    limit_raw,
    plan_dir,
    manifest_json,
    plannable_hashes,
    blocked_hashes,
    report_tsv,
    fast_mode_raw,
    debug_mode_raw,
) = sys.argv[1:13]

limit = max(0, int(limit_raw))
fast_mode = str(fast_mode_raw).strip() == "1"
debug_mode = str(debug_mode_raw).strip() == "1"
heartbeat_seconds = max(2.0, float(__import__("os").environ.get("REHOME_NOHL_STEP40_HEARTBEAT_SECONDS", "5")))
plan_timeout_seconds = max(30.0, float(__import__("os").environ.get("REHOME_NOHL_STEP40_PLAN_TIMEOUT_SECONDS", "300")))
hashes = []
for line in Path(hashes_file).read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    hashes.append(line)
if limit > 0:
    hashes = hashes[:limit]

manifest = []
plannable = []
blocked = []
with Path(report_tsv).open("w", encoding="utf-8") as tsv:
    tsv.write("idx\tpayload_hash\tdecision\tsource_path\ttarget_path\tstatus\tplan_path\terror\n")
    total = len(hashes)
    start_all = time.monotonic()
    for idx, payload_hash in enumerate(hashes, start=1):
        prefix = payload_hash[:12]
        plan_path = Path(plan_dir) / f"nohl-plan-{idx:04d}-{prefix}.json"
        cmd = [
            "python",
            "-m",
            "rehome.cli",
            "plan",
            "--demote",
            "--payload-hash",
            payload_hash,
            "--catalog",
            db_path,
            "--seeding-root",
            "/stash/media",
            "--seeding-root",
            "/data/media",
            "--seeding-root",
            "/pool/data",
            "--library-root",
            "/stash/media",
            "--library-root",
            "/data/media",
            "--stash-device",
            str(stash_device_id),
            "--pool-device",
            str(pool_device_id),
            "--stash-seeding-root",
            "/stash/media/torrents/seeding",
            "--pool-seeding-root",
            "/pool/data/seeds",
            "--pool-payload-root",
            "/pool/data/seeds",
            "--output",
            str(plan_path),
        ]
        status = "ok"
        error = ""
        decision = ""
        source_path = ""
        target_path = ""
        item_start = time.monotonic()
        try:
            if debug_mode:
                print(f"debug idx={idx}/{total} cmd={' '.join(cmd)}", flush=True)

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PYTHONPATH": "src", **__import__("os").environ},
            )
            last_heartbeat = item_start
            while proc.poll() is None:
                now = time.monotonic()
                elapsed = now - item_start
                if elapsed >= plan_timeout_seconds:
                    proc.kill()
                    raise RuntimeError(f"plan_timeout_s={int(elapsed)}")
                if now - last_heartbeat >= heartbeat_seconds:
                    overall_elapsed = now - start_all
                    avg = overall_elapsed / idx
                    eta = max(0.0, (total - idx) * avg)
                    print(
                        f"plan_wait idx={idx}/{total} payload={payload_hash[:16]} "
                        f"elapsed_s={int(elapsed)} eta_s={int(eta)}",
                        flush=True,
                    )
                    last_heartbeat = now
                time.sleep(0.5)

            out, err = proc.communicate()
            if proc.returncode != 0:
                if debug_mode and out.strip():
                    print(f"debug_stdout idx={idx}/{total} lines={len(out.splitlines())}", flush=True)
                if err.strip():
                    preview = "\\n".join(err.splitlines()[:6])
                    raise RuntimeError(f"plan_failed_rc={proc.returncode} stderr_preview={preview}")
                raise RuntimeError(f"plan_failed_rc={proc.returncode}")

            data = json.loads(plan_path.read_text(encoding="utf-8"))
            decision = str(data.get("decision") or "").upper()
            source_path = str(data.get("source_path") or "")
            target_path = str(data.get("target_path") or "")
            if decision == "BLOCK":
                blocked.append(payload_hash)
            elif decision in {"MOVE", "REUSE"}:
                plannable.append(payload_hash)
            else:
                status = "error"
                error = f"unexpected_decision:{decision}"
        except Exception as exc:  # pragma: no cover - defensive
            status = "error"
            error = str(exc)

        manifest.append(
            {
                "idx": idx,
                "total": total,
                "payload_hash": payload_hash,
                "plan_path": str(plan_path),
                "status": status,
                "decision": decision,
                "source_path": source_path,
                "target_path": target_path,
                "error": error,
            }
        )
        tsv.write(
            f"{idx}\t{payload_hash}\t{decision}\t{source_path}\t{target_path}\t{status}\t{plan_path}\t{error}\n"
        )
        elapsed_item = int(time.monotonic() - item_start)
        if fast_mode and status == "ok":
            print(
                f"plan idx={idx}/{total} payload={payload_hash[:16]} decision={decision} status=ok elapsed_s={elapsed_item}",
                flush=True,
            )
        else:
            print(
                f"plan idx={idx}/{total} payload={payload_hash[:16]} decision={decision or '-'} "
                f"status={status} from={source_path or '-'} to={target_path or '-'} error={error or 'none'} "
                f"elapsed_s={elapsed_item}",
                flush=True,
            )

        if idx == 1 or idx % 25 == 0 or idx == total:
            elapsed_all = time.monotonic() - start_all
            avg = elapsed_all / idx
            eta = max(0.0, (total - idx) * avg)
            print(
                f"progress idx={idx}/{total} ok={len(plannable)} blocked={len(blocked)} "
                f"errors={len([m for m in manifest if m['status'] == 'error'])} "
                f"avg_s={avg:.2f} eta_s={int(eta)}",
                flush=True,
            )

Path(plannable_hashes).write_text("\n".join(plannable) + ("\n" if plannable else ""), encoding="utf-8")
Path(blocked_hashes).write_text("\n".join(blocked) + ("\n" if blocked else ""), encoding="utf-8")
payload = {
    "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
    "hashes_input_file": hashes_file,
    "summary": {
        "input_hashes": len(hashes),
        "plannable": len(plannable),
        "blocked": len(blocked),
        "errors": len([m for m in manifest if m["status"] == "error"]),
    },
    "entries": manifest,
}
Path(manifest_json).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(
    f"summary input_hashes={payload['summary']['input_hashes']} plannable={payload['summary']['plannable']} "
    f"blocked={payload['summary']['blocked']} errors={payload['summary']['errors']}"
)
print(f"manifest_json={manifest_json}")
print(f"plannable_hashes={plannable_hashes}")
print(f"blocked_hashes={blocked_hashes}")
print(f"report_tsv={report_tsv}")
PY
} 2>&1 | tee "$run_log"

echo "run_log=${run_log}"
echo "manifest_json=${manifest_json}"
echo "plannable_hashes=${plannable_hashes}"
echo "blocked_hashes=${blocked_hashes}"
echo "report_tsv=${report_tsv}"
