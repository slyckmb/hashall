#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bin/rehome-05_pilot-batch_plan-and-dryrun.sh --payload-hash <sha256> [--spot-check N]
  bin/rehome-05_pilot-batch_plan-and-dryrun.sh -h|--help

Runs one rehome pilot batch end-to-end:
1) create demote plan for one payload hash
2) dry-run apply that plan
3) tee full output to $HOME/.logs/hashall/reports/rehome-pilot/
EOF
}

payload_hash=""
spot_check="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --payload-hash)
      payload_hash="${2:-}"
      shift 2
      ;;
    --spot-check)
      spot_check="${2:-1}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${payload_hash}" ]]; then
  echo "Missing --payload-hash" >&2
  usage
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

mkdir -p $HOME/.logs/hashall/reports/rehome-pilot
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
prefix="${payload_hash:0:12}"
plan="$HOME/.logs/hashall/reports/rehome-pilot/rehome-pilot-${prefix}-${stamp}.json"
log="$HOME/.logs/hashall/reports/rehome-pilot/rehome-pilot-${prefix}-${stamp}.log"

{
  echo "cmd_plan=PYTHONPATH=src python -m rehome.cli plan --demote --payload-hash ${payload_hash} --catalog /home/michael/.hashall/catalog.db --seeding-root /stash/media --seeding-root /data/media --seeding-root /pool/data --library-root /stash/media --library-root /data/media --stash-device 49 --pool-device 44 --stash-seeding-root /stash/media/torrents/seeding --pool-seeding-root /pool/data/seeds --pool-payload-root /pool/data/seeds --output ${plan}"
  PYTHONPATH=src python -m rehome.cli plan \
    --demote \
    --payload-hash "${payload_hash}" \
    --catalog /home/michael/.hashall/catalog.db \
    --seeding-root /stash/media \
    --seeding-root /data/media \
    --seeding-root /pool/data \
    --library-root /stash/media \
    --library-root /data/media \
    --stash-device 49 \
    --pool-device 44 \
    --stash-seeding-root /stash/media/torrents/seeding \
    --pool-seeding-root /pool/data/seeds \
    --pool-payload-root /pool/data/seeds \
    --output "${plan}"

  echo "cmd_dryrun=PYTHONPATH=src python -m rehome.cli apply ${plan} --dryrun --catalog /home/michael/.hashall/catalog.db --spot-check ${spot_check}"
  PYTHONPATH=src python -m rehome.cli apply "${plan}" \
    --dryrun \
    --catalog /home/michael/.hashall/catalog.db \
    --spot-check "${spot_check}"

  echo "plan=${plan}"
  echo "log=${log}"
} 2>&1 | tee "${log}"
