#!/usr/bin/env bash
#
# qb-zfs-migrate-tail-log.sh
# Version: 0.1.0
# Last Updated: 2026-03-08
#
# Tail a qB ZFS relocate log with simple colorized key=value highlighting.

set -euo pipefail

SCRIPT_NAME="qb-zfs-migrate-tail-log.sh"
SEMVER="0.1.0"
LAST_UPDATED="2026-03-08"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/script-metadata.sh"
script_meta_start "$@"
trap 'script_meta_end "$?"' EXIT
SCRIPT_VERSION="0.1.0"
DEFAULT_LOG_DIR="${HOME}/.logs/qb-zfs-relocate"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [--log PATH] [--log-dir PATH]

Tail a qB ZFS relocate log with colorized output.

Options:
  --log PATH       Tail a specific log file.
  --log-dir PATH   Select the newest *.log file from this directory.
  -h, --help       Show this help text.

Default:
  --log-dir ${DEFAULT_LOG_DIR}

Notes:
  - Without --log, the script chooses the newest log file at startup.
  - tail -F follows the selected file path; it does not switch to newer files
    created later unless you rerun the script.
EOF
}

die() {
  echo "error: $*" >&2
  exit 2
}

log_path=""
log_dir="${DEFAULT_LOG_DIR}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --log)
      [[ $# -ge 2 ]] || die "--log requires a path"
      log_path="$2"
      shift 2
      ;;
    --log-dir)
      [[ $# -ge 2 ]] || die "--log-dir requires a path"
      log_dir="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

if [[ -n "${log_path}" ]]; then
  [[ -f "${log_path}" ]] || die "log file not found: ${log_path}"
else
  [[ -d "${log_dir}" ]] || die "log directory not found: ${log_dir}"
  mapfile -t candidates < <(find "${log_dir}" -maxdepth 1 -type f -name '*.log' -printf '%T@ %p\n' | sort -nr)
  [[ ${#candidates[@]} -gt 0 ]] || die "no .log files found in: ${log_dir}"
  log_path="${candidates[0]#* }"
fi

echo "event=start script=${SCRIPT_NAME} version=${SCRIPT_VERSION} last_updated=${LAST_UPDATED} log=${log_path}" >&2

tail -F "${log_path}" | perl -pe '
  s/(event=[^ ]+)/\e[1;36m$1\e[0m/g;
  s/(phase=[^ ]+)/\e[1;33m$1\e[0m/g;
  s/(status=[^ ]+)/\e[1;32m$1\e[0m/g;
  s/(reason=[^ ]+)/\e[1;31m$1\e[0m/g;
  s/(text_log=[^ ]+|jsonl_log=[^ ]+|log=[^ ]+)/\e[0;36m$1\e[0m/g;
  s/(\[📊 Summary\])/\e[1;35m$1\e[0m/g;
  s/(warning:|⚠️ |error:|Traceback)/\e[1;31m$1\e[0m/g;
'
