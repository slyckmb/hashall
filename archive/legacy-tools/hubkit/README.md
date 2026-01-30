# gptrail: gitex-hubkit-001-19Jun25-links-setup-94f31b
# 🧰 HubKit

**HubKit** is a shared developer toolkit for managing Git repository infrastructure.

Designed for solo or small-team developers, HubKit enables:
- Safe symlink installation
- Shared pre-commit dispatching (coming soon)
- Common Git setup workflows across all dev repos

---

## 🚀 Features

- ✅ `safelink`: smart symbolic linking with safety checks  
- ✅ `setup_symlinks_from_config`: install dev-only links from a config file  
- 🧪 Easy integration via `submodule` or cloning  
- 🔄 Extensible for future tooling (hooks, utilities, etc)

---

## 🔧 How to Use (In Another Repo)

1. Add HubKit as a Git submodule:
   ```bash
   git submodule add git@github.com:slyckmb/hubkit.git tools/hubkit
   ```

2. Create a symlink config (example: `.setup/symlinks.conf`)
   ```txt
   $GPTRAIL_HOME/tools/inject_staged.sh tools/inject_staged.sh
   $GPTRAIL_HOME/tools/pre-commit-gptrail.sh tools/pre-commit-gptrail.sh
   ```

3. In your bootstrap script:
   ```bash
   source tools/hubkit/link.sh
   setup_symlinks_from_config .setup/symlinks.conf
   ```

---

## 🛡 Safety

- Will **not overwrite** existing real files  
- Will **overwrite existing symlinks** only if explicitly forced  
- Designed to be **idempotent** — safe to run repeatedly

---

## 📁 Structure

```
hubkit/
├── link.sh               # Core symlink logic
├── .setup/bootstrap-hubkit.sh   # Setup logic for this repo (optional)
└── .gitignore
```

---

## 📌 Coming Soon

- `hooks/pre-commit-dispatcher`: shared pre-commit hook dispatcher  
- `utils/`: additional general-purpose shell tools

---

💡 HubKit is built to stay out of the way, but make infra setup consistent and easy across all your repos.
