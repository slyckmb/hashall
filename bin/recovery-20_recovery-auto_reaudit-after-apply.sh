#!/usr/bin/env bash
set -euo pipefail

# Equivalent make command:
# make recovery-auto RECOVERY_WORKFLOW_PREFIX='<prefix>'

usage() {
  cat <<'EOF'
Usage:
  recovery-20_recovery-auto_reaudit-after-apply.sh [MAKE_VAR=VALUE ...]

What it does:
  Re-runs recovery audit, then prints latest report summary; logs both with tee.

Modifiers:
  RECOVERY_PREFIX=<path>                env var override for recovery prefix
  MAKE_VAR=VALUE ...                    passed through to `make recovery-auto`
    Common:
      RECOVERY_WORKFLOW_STASH_DEVICE=49
      RECOVERY_WORKFLOW_POOL_DEVICE=44
      RECOVERY_WORKFLOW_LIMIT=20

Examples:
  recovery-20_recovery-auto_reaudit-after-apply.sh
  recovery-20_recovery-auto_reaudit-after-apply.sh RECOVERY_WORKFLOW_LIMIT=50
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

RECOVERY_PREFIX="${RECOVERY_PREFIX:-/data/media/torrents/seeding/recovery_20260211/recycle_snapshot_20260207}"
stamp="$(TZ=America/New_York date +%Y%m%d-%H%M%S)"
mkdir -p out/reports/recovery-workflow
log="out/reports/recovery-workflow/recovery-20-reaudit-${stamp}.log"

{
  make recovery-auto RECOVERY_WORKFLOW_PREFIX="$RECOVERY_PREFIX" "$@"
  "$REPO_DIR/bin/recovery-10_recovery-auto_show-latest-report-summary.sh"
} 2>&1 | tee "$log"
echo "log=$log"
