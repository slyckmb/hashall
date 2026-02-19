#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC_DIR="$ROOT_DIR/ops/systemd/user"
UNIT_DST_DIR="$HOME/.config/systemd/user"
ENV_FILE="$HOME/.config/hashall/payload-orphan-snapshot.env"

units=(
  hashall-payload-orphan-snapshot.service
  hashall-payload-orphan-snapshot.timer
)

mkdir -p "$UNIT_DST_DIR"
mkdir -p "$HOME/.config/hashall"
mkdir -p "$HOME/.logs/hashall"

for unit in "${units[@]}"; do
  src="$UNIT_SRC_DIR/$unit"
  dst="$UNIT_DST_DIR/$unit"
  if [[ ! -f "$src" ]]; then
    echo "missing source unit: $src" >&2
    exit 1
  fi
  ln -sfn "$src" "$dst"
  echo "linked: $dst -> $src"
done

if [[ ! -f "$ENV_FILE" ]]; then
  printf "# hashall payload orphan snapshot timer overrides\n" > "$ENV_FILE"
fi
if ! grep -q '^HASHALL_REPO_DIR=' "$ENV_FILE"; then
  printf 'HASHALL_REPO_DIR=%s\n' "$ROOT_DIR" >> "$ENV_FILE"
  echo "set HASHALL_REPO_DIR in $ENV_FILE"
fi
if ! grep -q '^HASHALL_PYTHON=' "$ENV_FILE"; then
  printf 'HASHALL_PYTHON=%s\n' "$HOME/.venvs/hashall/bin/python" >> "$ENV_FILE"
  echo "set HASHALL_PYTHON in $ENV_FILE"
fi

systemctl --user daemon-reload
systemctl --user enable --now hashall-payload-orphan-snapshot.timer
systemctl --user status hashall-payload-orphan-snapshot.timer --no-pager
