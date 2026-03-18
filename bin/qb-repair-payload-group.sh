#!/usr/bin/env bash
# qb-repair-payload-group.sh
# version: 0.2.0
# last-updated: 2026-03-10
set -euo pipefail

exec python3 -m hashall.qb_repair_payload_group "$@"
