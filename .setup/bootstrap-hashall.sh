# gptrail: linex-hashall-001-19Jun25-json-scan-docker-b2d406
#!/bin/bash
set -euo pipefail

REPO_URL="https://github.com/slyckmb/hashall.git"
CLONE_DIR="$HOME/dev/work/hashall"
HASHALL_DIR="$HOME/.hashall"
DOCKER_IMAGE="hashall"

echo "🚀 Hashall Bootstrap Starting..."

# 1. Clone Repo (if needed)
if [ ! -d "$CLONE_DIR" ]; then
  echo "📥 Cloning repo to: $CLONE_DIR"
  git clone "$REPO_URL" "$CLONE_DIR"
else
  echo "✅ Repo already cloned: $CLONE_DIR"
fi

cd "$CLONE_DIR"

# 2. Ensure ~/.hashall exists
if [ ! -d "$HASHALL_DIR" ]; then
  echo "📁 Creating persistent DB directory at: $HASHALL_DIR"
  mkdir -p "$HASHALL_DIR"
else
  echo "✅ DB directory already exists: $HASHALL_DIR"
fi

# 3. Build Docker image
if ! docker image inspect "$DOCKER_IMAGE" >/dev/null 2>&1; then
  echo "🐳 Building Docker image: $DOCKER_IMAGE"
  docker build -t "$DOCKER_IMAGE" .
else
  echo "✅ Docker image '$DOCKER_IMAGE' already exists"
fi

# 4. Run sandbox test if supported
if [ -x "./tests/generate_sandbox.sh" ]; then
  echo "🧪 Running sandbox test..."
  ./tests/generate_sandbox.sh
  ./scripts/docker_test.sh
else
  echo "⚠️ No sandbox test available to run."
fi

echo "🎉 Bootstrap complete. Ready for: make, docker_run.sh, or scan/export."
