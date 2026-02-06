# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# Makefile for hashall - Development and smart scan operations

REPO_DIR := $(shell pwd)
DB_DIR := $(HOME)/.hashall
DB_FILE := $(DB_DIR)/catalog.db
HASHALL_IMG := hashall

# Python interpreter (uses active virtualenv if available)
PYTHON := $(shell if [ -n "$$VIRTUAL_ENV" ]; then echo "$$VIRTUAL_ENV/bin/python"; else echo "python3"; fi)

# Smart scan wrapper
SMART_SCAN = $(PYTHON) ./hashall-smart-scan

# Hierarchical scanners
AUTO_SCAN = $(PYTHON) ./hashall-auto-scan
PLAN_SCAN = $(PYTHON) ./hashall-plan-scan

# Default scan path (override with PATH=/custom/path)
PATH ?= .

# Root scan defaults (override via make VAR=value)
PARALLEL ?= 1
WORKERS ?=
HASH_MODE ?= fast
SHOW_PATH ?= 1

# Root scan CLI
HASHALL_CLI := $(PYTHON) -m hashall.cli

.DEFAULT_GOAL := help

.PHONY: help
help:  ## Show this help message
	@echo "🧰 Hashall Make Targets"
	@echo ""
	@echo "Root Scan (recommended):"
	@grep -E '^scan:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Device Management:"
	@grep -E '^(devices|show-device|alias-device|stats):.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Development & Testing:"
	@grep -E '^(bootstrap|build|test|sandbox|clean):.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Other Operations:"
	@grep -E '^(export|verify|docker-):.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Examples:"
	@echo "  make scan PATH=/pool/media WORKERS=12   # Root scan (parallel)"
	@echo "  make scan PATH=/pool/media HASH_MODE=full  # Full hashes"
	@echo "  make scan PATH=/pool/media SHOW_PATH=0     # Hide current file path line"
	@echo "  make devices                             # List all registered devices"
	@echo "  make stats                               # Show catalog statistics"
	@echo ""

# ============================================================================
# Root Scan (Recommended)
# ============================================================================

SCAN_ARGS = --db "$(DB_FILE)" --hash-mode "$(HASH_MODE)"
ifeq ($(PARALLEL),1)
SCAN_ARGS += --parallel
endif
ifneq ($(WORKERS),)
SCAN_ARGS += --workers $(WORKERS)
endif
ifeq ($(SHOW_PATH),1)
SCAN_ARGS += --show-path
endif

.PHONY: scan
scan:  ## Root scan (parallel by default). Vars: PATH, WORKERS, HASH_MODE, SHOW_PATH, PARALLEL
	@echo "📦 Root scan: $(PATH)"
	@$(HASHALL_CLI) scan "$(PATH)" $(SCAN_ARGS)

# ============================================================================
# Smart Scan Targets (Auto-Tuning) - RECOMMENDED
# ============================================================================

.PHONY: scan-auto
scan-auto:  ## Auto-detect optimal scan settings (recommended)
	@echo "⚠️ Deprecated: use 'make scan PATH=...' for a single root scan."
	@echo "🔍 Auto-detecting optimal settings for: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --db "$(DB_FILE)"

.PHONY: scan-video
scan-video:  ## Scan large video files (parallel, 4 workers, optimized >50MB)
	@echo "⚠️ Deprecated: use 'make scan PATH=... HASH_MODE=full WORKERS=4'."
	@echo "🎬 Scanning video files: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --preset video --db "$(DB_FILE)"

.PHONY: scan-audio
scan-audio:  ## Scan medium audio files (parallel, 8 workers, optimized 5-50MB)
	@echo "⚠️ Deprecated: use 'make scan PATH=... WORKERS=8'."
	@echo "🎵 Scanning audio files: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --preset audio --db "$(DB_FILE)"

.PHONY: scan-books
scan-books:  ## Scan small files/books (sequential, optimized <5MB)
	@echo "⚠️ Deprecated: use 'make scan PATH=... PARALLEL=0'."
	@echo "📚 Scanning books/documents: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --preset books --db "$(DB_FILE)"

.PHONY: scan-mixed
scan-mixed:  ## Scan mixed content (balanced parallel settings)
	@echo "⚠️ Deprecated: use 'make scan PATH=...'."
	@echo "📦 Scanning mixed content: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --preset mixed --db "$(DB_FILE)"

.PHONY: scan-dry-run
scan-dry-run:  ## Show what scan would execute without running
	@echo "⚠️ Deprecated: use 'make scan PATH=...' for actual scans."
	@echo "🔍 Analyzing $(PATH) (dry-run mode)..."
	$(SMART_SCAN) "$(PATH)" --dry-run --db "$(DB_FILE)"

.PHONY: scan-presets
scan-presets:  ## Show all available scan presets and their settings
	@echo "⚠️ Deprecated: use 'make scan PATH=...'."
	@$(SMART_SCAN) --show-presets

# ============================================================================
# Hierarchical & Adaptive Scanning - ADVANCED
# ============================================================================

.PHONY: scan-hierarchical
scan-hierarchical:  ## Adaptive scan - analyzes each subfolder independently (unified)
	@if [ "$(ALLOW_HIER)" != "1" ]; then \
		echo "❌ Disabled. Set ALLOW_HIER=1 to run hierarchical scans (may overscan)."; \
		exit 1; \
	fi
	@echo "⚠️ Deprecated: hierarchical scans may overscan. Use 'make scan PATH=...'."
	@echo "🌳 Hierarchical scan with unified database: $(PATH)"
	$(AUTO_SCAN) "$(PATH)" --db "$(DB_FILE)"

.PHONY: scan-hier-per-device
scan-hier-per-device:  ## Adaptive scan - per-device databases (legacy)
	@if [ "$(ALLOW_HIER)" != "1" ]; then \
		echo "❌ Disabled. Set ALLOW_HIER=1 to run hierarchical scans (may overscan)."; \
		exit 1; \
	fi
	@echo "⚠️ Deprecated: hierarchical scans may overscan. Use 'make scan PATH=...'."
	@echo "🌳 Hierarchical scan with device-local database: $(PATH)"
	$(AUTO_SCAN) "$(PATH)" --per-device

.PHONY: scan-plan
scan-plan:  ## Analyze tree and propose optimal scan strategy
	@if [ "$(ALLOW_HIER)" != "1" ]; then \
		echo "❌ Disabled. Set ALLOW_HIER=1 to run hierarchical planning (may overscan)."; \
		exit 1; \
	fi
	@echo "⚠️ Deprecated: hierarchical planning may overscan. Use 'make scan PATH=...'."
	@echo "📊 Analyzing directory tree for optimal scan strategy: $(PATH)"
	$(PLAN_SCAN) "$(PATH)" --db "$(DB_FILE)"

.PHONY: scan-plan-execute
scan-plan-execute:  ## Analyze and execute optimal scan plan
	@if [ "$(ALLOW_HIER)" != "1" ]; then \
		echo "❌ Disabled. Set ALLOW_HIER=1 to run hierarchical planning (may overscan)."; \
		exit 1; \
	fi
	@echo "⚠️ Deprecated: hierarchical planning may overscan. Use 'make scan PATH=...'."
	@echo "🚀 Planning and executing optimal scan: $(PATH)"
	$(PLAN_SCAN) "$(PATH)" --execute --db "$(DB_FILE)"

.PHONY: scan-hier-dry
scan-hier-dry:  ## Preview hierarchical scan plan without executing
	@if [ "$(ALLOW_HIER)" != "1" ]; then \
		echo "❌ Disabled. Set ALLOW_HIER=1 to run hierarchical scans (may overscan)."; \
		exit 1; \
	fi
	@echo "⚠️ Deprecated: hierarchical scans may overscan. Use 'make scan PATH=...'."
	@echo "🔍 Previewing hierarchical scan plan: $(PATH)"
	$(AUTO_SCAN) "$(PATH)" --dry-run --db "$(DB_FILE)"

# ============================================================================
# Device Management
# ============================================================================

.PHONY: devices
devices:  ## List all registered devices
	@hashall devices list

.PHONY: show-device
show-device:  ## Show detailed device info (usage: make show-device DEVICE=pool)
ifndef DEVICE
	@echo "❌ Error: DEVICE not specified"
	@echo "Usage: make show-device DEVICE=<device_id_or_alias>"
	@echo ""
	@echo "Available devices:"
	@hashall devices list
	@exit 1
endif
	@hashall devices show "$(DEVICE)"

.PHONY: alias-device
alias-device:  ## Set device alias (usage: make alias-device DEVICE=49 ALIAS=pool)
ifndef DEVICE
	@echo "❌ Error: DEVICE not specified"
	@echo "Usage: make alias-device DEVICE=<current> ALIAS=<new>"
	@exit 1
endif
ifndef ALIAS
	@echo "❌ Error: ALIAS not specified"
	@echo "Usage: make alias-device DEVICE=<current> ALIAS=<new>"
	@exit 1
endif
	@hashall devices alias "$(DEVICE)" "$(ALIAS)"

.PHONY: stats
stats:  ## Show catalog statistics (file counts, sizes, devices)
	@hashall stats

# ============================================================================
# Development & Testing
# ============================================================================

.PHONY: bootstrap
bootstrap:  ## Prepare environment (clone, venv, db dir, ~/.bin link)
	@echo "🚀 Bootstrapping hashall repo setup..."
	@.setup/bootstrap-hashall.sh

.PHONY: build
build:  ## Build Docker image for hashall
	@echo "🐳 Building Docker image: $(HASHALL_IMG)"
	docker build -t $(HASHALL_IMG) .

.PHONY: test
test:  ## Run full test suite
	@echo "🧪 Running tests..."
	@python -m pytest tests/ -v

.PHONY: test-fast
test-fast:  ## Run tests without integration tests
	@python -m pytest tests/ -v -m "not integration"

.PHONY: test-integration
test-integration:  ## Run only integration tests
	@python -m pytest tests/ -v -m integration

.PHONY: test-smoke
test-smoke:  ## Run full CLI smoke test
	@echo "🧪 Running smoke test..."
	@bash tests/smoke_test.sh

.PHONY: bench
bench:  ## Run performance benchmarks
	@python benchmarks/bench_incremental.py

.PHONY: sandbox
sandbox:  ## Regenerate local test sandbox
	@echo "🔁 Resetting test sandbox..."
	@bash tests/generate_sandbox.sh

.PHONY: targets-table
targets-table:  ## Generate summarized Markdown table of Makefile targets and CLI equivalents
	@python3 scripts/generate_target_table.py

.PHONY: targets-full
targets-full:  ## Generate table with full untruncated CLI commands (hides description)
	@python3 scripts/generate_target_table.py --full

.PHONY: prompts-remote
prompts-remote:  ## Prepend remote Codex preamble to prompts under out/
	@scripts/prepend_remote_preamble.sh

.PHONY: clean
clean:  ## Remove generated files and caches
	@echo "🧹 Cleaning up..."
	rm -rf sandbox/ tmp/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .pytest_cache/ .coverage

.PHONY: clean-db
clean-db:  ## Remove catalog database (DESTRUCTIVE!)
	@echo "⚠️  WARNING: This will delete your entire catalog!"
	@echo "Database: $(DB_FILE)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -f "$(DB_FILE)" "$(DB_FILE)-wal" "$(DB_FILE)-shm"; \
		echo "✅ Database deleted"; \
	else \
		echo "❌ Cancelled"; \
	fi

.PHONY: install
install:  ## Install hashall in development mode
	pip install -e .

.PHONY: install-dev
install-dev:  ## Install with development dependencies
	pip install -e ".[dev]"

# ============================================================================
# Other Operations
# ============================================================================

.PHONY: export
export:  ## Export hashall metadata to JSON
	@echo "📤 Exporting scan JSON..."
	@python -m hashall.export "$(DB_FILE)"

.PHONY: verify-trees
verify-trees:  ## Verify that dst matches src
	@echo "🔍 Verifying two directories..."
	@python -m hashall.verify-trees sandbox/seed sandbox/backup --force

.PHONY: verify
verify:  ## Run scan in verify mode
	@echo "🧪 Verifying hashes..."
	@python -m hashall.scan sandbox --mode verify

.PHONY: diff
diff:  ## Run diff tool
	@echo "🧾 Running treehash diff..."
	@python -m hashall.diff

.PHONY: version
version:  ## Show current version
	@python -c "from hashall import __version__; print(__version__)"

.PHONY: docker-scan
docker-scan:  ## Run scan inside Docker container
	@echo "📦 Running scan in Docker..."
	@scripts/docker_scan_and_export.sh scan

.PHONY: docker-export
docker-export:  ## Export .json from latest scan inside Docker
	@echo "📤 Running export in Docker..."
	@scripts/docker_scan_and_export.sh export

.PHONY: docker-test
docker-test:  ## Run full scan + export test in Docker
	@echo "🧪 Running Docker scan + export test..."
	@scripts/docker_test.sh

# ============================================================================
# Batch Operations
# ============================================================================

.PHONY: backup-db
backup-db:  ## Backup catalog database with timestamp
	@BACKUP_FILE="$(DB_FILE).backup-$$(date +%Y%m%d-%H%M%S)"; \
	cp "$(DB_FILE)" "$$BACKUP_FILE" 2>/dev/null && \
	echo "✅ Database backed up to: $$BACKUP_FILE" || \
	echo "⚠️  No database found to backup"
