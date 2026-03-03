#!/usr/bin/env bash
set -euo pipefail

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

step "2. Scan /pool/data + /mnt/hotspare6tb" \
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
