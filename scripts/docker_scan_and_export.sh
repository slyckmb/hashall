# gptrail: linex-hashall-001-19Jun25-json-scan-docker-b2d406
#!/bin/bash
set -e

ROOT="${1:-/mnt/media}"

if [[ "$1" == "--help" || "$1" == "-h" ]]; then
  echo "Usage: $0 /path/to/scan"
  echo "Scan and export a directory using Dockerized hashall."
  exit 0
fi

if [ ! -d "$ROOT" ]; then
  echo "❌ Directory not found: $ROOT"
  exit 1
fi

echo "📁 Scanning directory: $ROOT"

docker-compose run --rm hashall scan "$ROOT" --mode verify

echo "📤 Exporting metadata JSON..."
docker-compose run --rm hashall export "$ROOT"

echo "✅ Scan + export completed for: $ROOT"
