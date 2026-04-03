#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

fmt_elapsed() {
  local total="$1"
  local h m s
  s=$((total % 60))
  m=$(((total / 60) % 60))
  h=$((total / 3600))
  if (( h > 0 )); then
    printf '%dh%02dm%02ds' "$h" "$m" "$s"
  elif (( m > 0 )); then
    printf '%dm%02ds' "$m" "$s"
  else
    printf '%ds' "$s"
  fi
}

step() {
  local label="$1"
  local started elapsed rc
  echo
  echo "== $label =="
  echo "start: $(date '+%F %T')"
  shift
  started=$(date +%s)
  if "$@"; then
    elapsed=$(( $(date +%s) - started ))
    echo "done:  $(date '+%F %T')"
    echo "elapsed: $(fmt_elapsed "$elapsed")"
    return 0
  fi
  rc=$?
  elapsed=$(( $(date +%s) - started ))
  echo "failed: $(date '+%F %T')"
  echo "elapsed: $(fmt_elapsed "$elapsed")"
  echo "command_failed: $*"
  return "$rc"
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
echo "Full refresh pipeline complete."
echo "review_logs: $HOME/.logs/hashall/reports"
