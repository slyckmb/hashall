#!/usr/bin/env bash
set -euo pipefail


SCRIPT_NAME="$(basename "$0")"
SEMVER="0.1.0"
LAST_UPDATED="2026-04-09T07:05:00-04:00"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/script-metadata.sh"
script_meta_start "$@"
trap 'script_meta_end "$?"' EXIT
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

step() {
  echo
  echo "== $1 =="
  shift
  "$@"
}

step "1. Scan /stash/media (includes /data/media collection)" \
  "$repo_root/bin/db-refresh-step1-scan-stash.sh"

step "2. Scan /pool/data + /pool/media + /mnt/hotspare6tb" \
  "$repo_root/bin/db-refresh-step2-scan-pool-hotspare.sh"

step "3. SHA256 collision & upgrade" \
  "$repo_root/bin/db-refresh-step3-sha256-backfill.sh"

step "3.5. Hardlink dedup (apply)" \
  "$repo_root/bin/db-refresh-step4_5-link-dedup.sh" --apply

step "4. Payload sync (qB index refresh)" \
  "$repo_root/bin/db-refresh-step4-payload-sync.sh"

step "Bonus. QB hash-root report" \
  "$repo_root/bin/qb-hash-root-report.sh"

echo
echo "Full refresh pipeline complete. Review each log under $HOME/.logs/hashall/reports for per-step detail."
