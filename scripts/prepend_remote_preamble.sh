#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREAMBLE_FILE="$ROOT_DIR/docs/REMOTE-PREAMBLE.md"
OUT_DIR="$ROOT_DIR/out"

if [[ ! -f "$PREAMBLE_FILE" ]]; then
  echo "Missing preamble: $PREAMBLE_FILE" >&2
  exit 1
fi

if [[ ! -d "$OUT_DIR" ]]; then
  echo "Missing out dir: $OUT_DIR" >&2
  exit 1
fi

shopt -s nullglob
files=("$OUT_DIR"/*.md)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "No prompts found under $OUT_DIR"
  exit 0
fi

for f in "${files[@]}"; do
  if head -n 1 "$f" | grep -q "^# Remote Codex Adaptation (Preamble)$"; then
    echo "Preamble already present: $f"
    continue
  fi

  tmp="${f}.tmp"
  {
    cat "$PREAMBLE_FILE"
    echo ""
    cat "$f"
  } > "$tmp"
  mv "$tmp" "$f"
  echo "Prepended preamble: $f"
  done
