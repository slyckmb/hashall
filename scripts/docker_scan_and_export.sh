#!/bin/bash
set -e

# Detect Synology DSM and use sudo if needed
if [[ -f /etc/VERSION ]] && grep -q 'os_name="DSM"' /etc/VERSION; then
  echo "🧠 Synology DSM detected — using sudo with Docker"
  DOCKER="sudo docker"
else
  DOCKER="docker"
fi

# Show help if no input
if [[ -z "$1" || "$1" == "--help" || "$1" == "-h" ]]; then
  echo "Usage: $0 /path/to/scan"
  echo "Scan and export a directory using Dockerized hashall."
  exit 1
fi

ROOT="$(realpath "$1")"
if [ ! -d "$ROOT" ]; then
  echo "❌ Directory not found: $ROOT"
  exit 1
fi

echo "📁 Scanning directory: $ROOT"

$DOCKER run --rm \
  -v "$ROOT":/target \
  -v "$HOME/.hashall":/root/.hashall \
  hashall scan /target --mode verify

echo "📤 Exporting metadata JSON..."

$DOCKER run --rm \
  -v "$ROOT":/target \
  -v "$HOME/.hashall":/root/.hashall \
  hashall export /target

echo "✅ Scan + export completed for: $ROOT"
