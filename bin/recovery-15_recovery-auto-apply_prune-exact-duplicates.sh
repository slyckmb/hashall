#!/usr/bin/env bash
set -euo pipefail

# Equivalent make command:
# make recovery-auto-apply RECOVERY_WORKFLOW_PREFIX='<prefix>' RECOVERY_WORKFLOW_LIMIT='<N>'

usage() {
  cat <<'EOF'
Usage:
  recovery-15_recovery-auto-apply_prune-exact-duplicates.sh [MAKE_VAR=VALUE ...]

What it does:
  Applies exact-duplicate prune for recovered units and logs with tee.

Modifiers:
  RECOVERY_PREFIX=<path>                env var override for recovery prefix
  RECOVERY_LIMIT=<N>                    env var override for apply limit (default: 5)
  MAKE_VAR=VALUE ...                    passed through to `make recovery-auto-apply`
    Common:
      RECOVERY_WORKFLOW_STASH_DEVICE=49
      RECOVERY_WORKFLOW_POOL_DEVICE=44
      RECOVERY_WORKFLOW_LIMIT=10

Examples:
  RECOVERY_LIMIT=10 recovery-15_recovery-auto-apply_prune-exact-duplicates.sh
  recovery-15_recovery-auto-apply_prune-exact-duplicates.sh RECOVERY_WORKFLOW_LIMIT=25
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

RECOVERY_PREFIX="${RECOVERY_PREFIX:-/data/media/torrents/seeding/recovery_20260211/recycle_snapshot_20260207}"
RECOVERY_LIMIT="${RECOVERY_LIMIT:-5}"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
mkdir -p $HOME/.logs/hashall/reports/recovery-workflow
log="$HOME/.logs/hashall/reports/recovery-workflow/recovery-15-apply-${stamp}.log"

make recovery-auto-apply \
  RECOVERY_WORKFLOW_PREFIX="$RECOVERY_PREFIX" \
  RECOVERY_WORKFLOW_LIMIT="$RECOVERY_LIMIT" \
  "$@" 2>&1 | tee "$log"

echo "log=$log"
