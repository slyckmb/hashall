# gptrail: linex-hashall-001-19Jun25-json-scan-docker-b2d406
#!/bin/bash
set -e

echo "🔁 Running Docker sandbox test: scan + export"

docker run --rm \
  -v "$PWD":/data \
  -v "$HOME/.hashall":/root/.hashall \
  -w /data \
  hashall scan sandbox/test_root --mode verify

docker run --rm \
  -v "$PWD":/data \
  -v "$HOME/.hashall":/root/.hashall \
  -w /data \
  hashall export sandbox/test_root

echo "✅ Docker scan + export complete."
