#!/usr/bin/env bash
# qb-repair-payload-group.sh
# version: 0.2.0
# last-updated: 2026-03-10
set -euo pipefail


SCRIPT_NAME="$(basename "$0")"
SEMVER="0.1.0"
LAST_UPDATED="2026-04-09T07:05:00-04:00"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/script-metadata.sh"
script_meta_start "$@"
trap 'script_meta_end "$?"' EXIT
exec python3 -m hashall.qb_repair_payload_group "$@"
