#!/usr/bin/env bash

script_meta_now() {
  date --iso-8601=seconds
}

script_meta_name() {
  if [[ -n "${SCRIPT_NAME:-}" ]]; then
    printf '%s' "${SCRIPT_NAME}"
    return
  fi
  printf '%s' "$(basename "$0")"
}

script_meta_semver() {
  if [[ -n "${SEMVER:-}" ]]; then
    printf '%s' "${SEMVER}"
    return
  fi
  if [[ -n "${SCRIPT_VERSION:-}" ]]; then
    printf '%s' "${SCRIPT_VERSION}"
    return
  fi
  if [[ -n "${VERSION:-}" ]]; then
    printf '%s' "${VERSION}"
    return
  fi
  printf '%s' "0.1.0"
}

script_meta_last_updated() {
  if [[ -n "${LAST_UPDATED:-}" ]]; then
    printf '%s' "${LAST_UPDATED}"
    return
  fi
  if [[ -n "${SCRIPT_DATE:-}" ]]; then
    printf '%s' "${SCRIPT_DATE}"
    return
  fi
  printf '%s' "unknown"
}

script_meta_start() {
  local argv=""
  if (($#)); then
    argv="$*"
  fi
  printf 'event=start script=%s semver=%s last_updated=%s timestamp=%s' \
    "$(script_meta_name)" "$(script_meta_semver)" "$(script_meta_last_updated)" "$(script_meta_now)"
  if [[ -n "${argv}" ]]; then
    printf ' argv=%q' "${argv}"
  fi
  printf '\n'
}

script_meta_end() {
  local exit_code="${1:-0}"
  local status="ok"
  if [[ "${exit_code}" != "0" ]]; then
    status="failed"
  fi
  printf 'event=end script=%s semver=%s last_updated=%s timestamp=%s exit_code=%s status=%s\n' \
    "$(script_meta_name)" "$(script_meta_semver)" "$(script_meta_last_updated)" "$(script_meta_now)" "${exit_code}" "${status}"
}
