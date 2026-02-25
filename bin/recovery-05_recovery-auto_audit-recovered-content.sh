#!/usr/bin/env bash
set -euo pipefail

# Equivalent make command:
# make recovery-auto RECOVERY_WORKFLOW_PREFIX='<prefix>'

usage() {
  cat <<'EOF'
Usage:
  recovery-05_recovery-auto_audit-recovered-content.sh [MAKE_VAR=VALUE ...]

What it does:
  Runs recovery audit only (no deletes) and logs output with tee.

Modifiers:
  RECOVERY_PREFIX=<path>                env var override for recovery prefix
  MAKE_VAR=VALUE ...                    passed through to `make recovery-auto`
    Common:
      RECOVERY_WORKFLOW_STASH_DEVICE=49
      RECOVERY_WORKFLOW_POOL_DEVICE=44
      RECOVERY_WORKFLOW_LIMIT=20

Examples:
  RECOVERY_PREFIX=/data/media/.../recycle_snapshot_20260207 \
    recovery-05_recovery-auto_audit-recovered-content.sh
  recovery-05_recovery-auto_audit-recovered-content.sh RECOVERY_WORKFLOW_LIMIT=50
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
mkdir -p $HOME/.logs/hashall/reports/recovery-workflow
log="$HOME/.logs/hashall/reports/recovery-workflow/recovery-05-audit-${stamp}.log"

make recovery-auto RECOVERY_WORKFLOW_PREFIX="$RECOVERY_PREFIX" "$@" 2>&1 | tee "$log"
echo "log=$log"
