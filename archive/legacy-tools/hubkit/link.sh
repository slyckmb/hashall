# gptrail: gitex-hubkit-001-19Jun25-links-setup-94f31b
#!/bin/bash

# 🧰 HubKit: tools.sh
# Standardized symlink utilities for safe, idempotent linking

# Safely create or update symlinks
safelink() {
  local src="$1"
  local dest="$2"
  local force="${3:-false}"

  # Destination is a real file (not symlink) — skip
  if [[ -e "$dest" && ! -L "$dest" ]]; then
    echo "⚠️  Skipping: $dest exists and is not a symlink"
    return
  fi

  # Destination is a symlink
  if [[ -L "$dest" ]]; then
    local existing_target
    existing_target=$(readlink "$dest")
    if [[ "$existing_target" == "$src" ]]; then
      echo "✅ $dest already links to $src"
      return
    fi

    if [[ "$force" == "true" ]]; then
      echo "🔁 Updating symlink: $dest → $src"
      ln -sfn "$src" "$dest"
    else
      echo "⚠️  Skipping existing symlink: $dest → $existing_target (use force=true to override)"
    fi
  else
    echo "🔗 Creating symlink: $dest → $src"
    ln -s "$src" "$dest"
  fi
}

# Read and process symlinks from config file
setup_symlinks_from_config() {
  local config_file="$1"
  local force="${2:-false}"

  if [[ ! -f "$config_file" ]]; then
    echo "❌ Config file not found: $config_file"
    return 1
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    eval "line=\"$line\""  # Expand env vars like $GPTRAIL_HOME
    src=$(echo "$line" | awk '{print $1}')
    dest=$(echo "$line" | awk '{print $2}')
    safelink "$src" "$dest" "$force"
  done < "$config_file"
}
