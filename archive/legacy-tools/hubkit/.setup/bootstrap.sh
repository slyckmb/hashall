# gptrail: gitex-hubkit-001-19Jun25-links-setup-94f31b
#!/bin/bash

# 🚀 HubKit Bootstrap Script

set -e

HUBKIT_REPO="git@github.com:slyckmb/hubkit.git"
HUBKIT_PATH="tools/hubkit"

# Only add submodule if not disabled (e.g., in sandbox)
if [[ -z "${SKIP_SUBMODULE_ADD:-}" ]]; then
  echo "📦 Adding hubkit submodule to $HUBKIT_PATH ..."
  git submodule add "$HUBKIT_REPO" "$HUBKIT_PATH" || {
    echo "❌ Submodule add failed. Already present?"
  }

  echo "🔄 Initializing and updating submodules..."
  git submodule update --init --recursive
else
  echo "⚠️ Skipping submodule add (sandbox or manual override)"
fi

echo "✅ Hubkit installed at $HUBKIT_PATH"
echo ""
echo "📘 Next Steps:"
echo "  - Source HubKit in your install script like:"
echo "      source $HUBKIT_PATH/link.sh"
