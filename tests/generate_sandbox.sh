#!/bin/bash
# Create test sandbox under sandbox/

set -e

ROOT_DIR="sandbox/test_root"

echo "🧹 Cleaning sandbox..."
rm -rf sandbox
mkdir -p "$ROOT_DIR"/{alpha,beta,gamma}

echo "📁 Generating dummy test files..."
for dir in alpha beta gamma; do
  for i in {1..5}; do
    echo "This is test file $i in $dir" > "$ROOT_DIR/$dir/file_$i.txt"
  done
done

echo "✅ Sandbox ready at: $ROOT_DIR"
