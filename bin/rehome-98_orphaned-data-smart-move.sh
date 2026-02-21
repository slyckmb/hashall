#!/usr/bin/env bash
set -euo pipefail

hr() {
  printf '%s\n' "------------------------------------------------------------"
}

usage() {
  cat <<'USAGE'
Usage:
  bin/rehome-98_orphaned-data-smart-move.sh [options]

Moves orphaned data as whole leaf folders only (never splits a leaf folder).

Options:
  --source PATH         Source root (default: /pool/data/orphaned_data)
  --dest PATH           Destination root (default: /mnt/hotspare6tb/orphan_data)
  --reserve-gib N       Keep at least N GiB free on destination (default: 25)
  --order MODE          small-first | large-first | input (default: small-first)
  --limit N             Process at most N leaf folders (default: 0 = all)
  --dryrun              Print actions only (default)
  --apply               Execute moves using rsync --remove-source-files
  --output-prefix NAME  Log prefix (default: orphaned-data-smart-move)
  -h, --help            Show help
USAGE
}

SOURCE_ROOT="/pool/data/orphaned_data"
DEST_ROOT="/mnt/hotspare6tb/orphan_data"
RESERVE_GIB="25"
ORDER_MODE="small-first"
LIMIT="0"
DO_APPLY=0
OUTPUT_PREFIX="orphaned-data-smart-move"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE_ROOT="${2:-}"; shift 2 ;;
    --dest) DEST_ROOT="${2:-}"; shift 2 ;;
    --reserve-gib) RESERVE_GIB="${2:-}"; shift 2 ;;
    --order) ORDER_MODE="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-}"; shift 2 ;;
    --dryrun) DO_APPLY=0; shift ;;
    --apply) DO_APPLY=1; shift ;;
    --output-prefix) OUTPUT_PREFIX="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$RESERVE_GIB" =~ ^[0-9]+$ ]]; then
  echo "Invalid --reserve-gib: $RESERVE_GIB" >&2
  exit 2
fi
if ! [[ "$LIMIT" =~ ^[0-9]+$ ]]; then
  echo "Invalid --limit: $LIMIT" >&2
  exit 2
fi
if [[ "$ORDER_MODE" != "small-first" && "$ORDER_MODE" != "large-first" && "$ORDER_MODE" != "input" ]]; then
  echo "Invalid --order: $ORDER_MODE" >&2
  exit 2
fi

SOURCE_ROOT="$(realpath -m "$SOURCE_ROOT")"
DEST_ROOT="$(realpath -m "$DEST_ROOT")"
if [[ ! -d "$SOURCE_ROOT" ]]; then
  echo "Source directory not found: $SOURCE_ROOT" >&2
  exit 3
fi
mkdir -p "$DEST_ROOT"

log_dir="out/reports/rehome-normalize"
mkdir -p "$log_dir"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
run_log="${log_dir}/${OUTPUT_PREFIX}-${stamp}.log"
exec > >(tee "$run_log") 2>&1

reserve_bytes=$((RESERVE_GIB * 1024 * 1024 * 1024))

hr
echo "Phase 98: orphaned-data smart move"
echo "What this does: moves whole leaf folders only, with destination free-space guard."
hr
echo "run_id=${stamp} mode=$([[ "$DO_APPLY" == "1" ]] && echo apply || echo dryrun) source=${SOURCE_ROOT} dest=${DEST_ROOT} reserve_gib=${RESERVE_GIB} order=${ORDER_MODE} limit=${LIMIT}"
echo "run_log=${run_log}"

leaf_tsv="${log_dir}/${OUTPUT_PREFIX}-leaves-${stamp}.tsv"

# Build candidate leaves: dirs under source that contain files and no child dirs.
while IFS= read -r -d '' d; do
  if find "$d" -mindepth 1 -maxdepth 1 -type d -print -quit | grep -q .; then
    continue
  fi
  if ! find "$d" -mindepth 1 -maxdepth 1 -type f -print -quit | grep -q .; then
    continue
  fi
  rel="${d#"$SOURCE_ROOT"/}"
  [[ "$rel" == "$d" ]] && continue
  bytes="$(du -sB1 "$d" | awk '{print $1}')"
  printf '%s\t%s\n' "$bytes" "$rel"
done < <(find "$SOURCE_ROOT" -mindepth 1 -type d -print0) > "$leaf_tsv"

if [[ ! -s "$leaf_tsv" ]]; then
  echo "summary leaves_total=0 selected=0 moved=0 skipped_space=0 skipped_error=0"
  hr
  echo "result=ok step=orphaned-data-smart-move mode=$([[ "$DO_APPLY" == "1" ]] && echo apply || echo dryrun) run_log=${run_log}"
  hr
  exit 0
fi

sorted_tsv="${log_dir}/${OUTPUT_PREFIX}-leaves-sorted-${stamp}.tsv"
case "$ORDER_MODE" in
  small-first) sort -n -k1,1 "$leaf_tsv" > "$sorted_tsv" ;;
  large-first) sort -nr -k1,1 "$leaf_tsv" > "$sorted_tsv" ;;
  input) cat "$leaf_tsv" > "$sorted_tsv" ;;
esac

mapfile -t rows < "$sorted_tsv"
if [[ "$LIMIT" -gt 0 && "$LIMIT" -lt "${#rows[@]}" ]]; then
  rows=("${rows[@]:0:LIMIT}")
fi

total="${#rows[@]}"
moved=0
skipped_space=0
skipped_error=0
bytes_planned=0
bytes_moved=0

for row in "${rows[@]}"; do
  bytes="${row%%$'\t'*}"
  rel="${row#*$'\t'}"
  bytes_planned=$((bytes_planned + bytes))
done

echo "summary_preflight leaves_total=${#rows[@]} bytes_planned=${bytes_planned}"

idx=0
for row in "${rows[@]}"; do
  idx=$((idx + 1))
  bytes="${row%%$'\t'*}"
  rel="${row#*$'\t'}"
  src_dir="${SOURCE_ROOT}/${rel}"
  dst_dir="${DEST_ROOT}/${rel}"

  avail_bytes="$(df -B1 --output=avail "$DEST_ROOT" | tail -n1 | tr -d ' ')"
  budget_bytes=$((avail_bytes - reserve_bytes))
  if [[ "$budget_bytes" -lt 0 ]]; then
    budget_bytes=0
  fi

  if [[ "$bytes" -gt "$budget_bytes" ]]; then
    skipped_space=$((skipped_space + 1))
    echo "item idx=${idx}/${total} rel=${rel} bytes=${bytes} avail=${avail_bytes} budget=${budget_bytes} action=skip_space"
    continue
  fi

  if [[ "$DO_APPLY" != "1" ]]; then
    echo "item idx=${idx}/${total} rel=${rel} bytes=${bytes} avail=${avail_bytes} budget=${budget_bytes} action=dryrun_move"
    continue
  fi

  mkdir -p "$dst_dir"
  echo "item idx=${idx}/${total} rel=${rel} bytes=${bytes} avail=${avail_bytes} budget=${budget_bytes} action=move"
  if rsync -aH --info=progress2 --remove-source-files "$src_dir"/ "$dst_dir"/; then
    moved=$((moved + 1))
    bytes_moved=$((bytes_moved + bytes))
    find "$src_dir" -type d -empty -delete 2>/dev/null || true
  else
    skipped_error=$((skipped_error + 1))
    echo "item idx=${idx}/${total} rel=${rel} action=move_error"
  fi

done

if [[ "$DO_APPLY" == "1" ]]; then
  find "$SOURCE_ROOT" -depth -type d -empty -delete 2>/dev/null || true
fi

echo "summary leaves_total=${total} moved=${moved} skipped_space=${skipped_space} skipped_error=${skipped_error} bytes_planned=${bytes_planned} bytes_moved=${bytes_moved}"
hr
echo "result=ok step=orphaned-data-smart-move mode=$([[ "$DO_APPLY" == "1" ]] && echo apply || echo dryrun) run_log=${run_log}"
hr
