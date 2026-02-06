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

.DEFAULT_GOAL := help

.PHONY: help
help:  ## Show this help message
	@echo "🧰 Hashall Make Targets"
	@echo ""
	@echo "Smart Scan Operations (Auto-Tuning):"
	@grep -E '^scan-(auto|video|audio|books|mixed|dry-run|presets):.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Advanced Hierarchical Scanning:"
	@grep -E '^scan-(hierarchical|plan|hier):.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Device Management:"
	@grep -E '^(devices|show-device|alias-device|stats):.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Development & Testing:"
	@grep -E '^(bootstrap|build|test|sandbox|clean):.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Legacy Operations:"
	@grep -E '^(scan|export|verify|docker-):.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Examples:"
	@echo "  make scan-auto PATH=/pool/media         # Auto-detect optimal settings"
	@echo "  make scan-hierarchical PATH=/pool       # Adaptive per-folder scan (unified)"
	@echo "  make scan-hier-per-device PATH=/pool    # Adaptive per-folder scan (per-device DBs)"
	@echo "  make scan-plan PATH=/pool               # Analyze & propose strategy"
	@echo "  make scan-video PATH=/pool/movies       # Optimize for large video files"
	@echo "  make devices                             # List all registered devices"
	@echo "  make stats                               # Show catalog statistics"
	@echo ""

# ============================================================================
# Smart Scan Targets (Auto-Tuning) - RECOMMENDED
# ============================================================================

.PHONY: scan-auto
scan-auto:  ## Auto-detect optimal scan settings (recommended)
	@echo "🔍 Auto-detecting optimal settings for: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --db "$(DB_FILE)"

.PHONY: scan-video
scan-video:  ## Scan large video files (parallel, 4 workers, optimized >50MB)
	@echo "🎬 Scanning video files: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --preset video --db "$(DB_FILE)"

.PHONY: scan-audio
scan-audio:  ## Scan medium audio files (parallel, 8 workers, optimized 5-50MB)
	@echo "🎵 Scanning audio files: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --preset audio --db "$(DB_FILE)"

.PHONY: scan-books
scan-books:  ## Scan small files/books (sequential, optimized <5MB)
	@echo "📚 Scanning books/documents: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --preset books --db "$(DB_FILE)"

.PHONY: scan-mixed
scan-mixed:  ## Scan mixed content (balanced parallel settings)
	@echo "📦 Scanning mixed content: $(PATH)"
	$(SMART_SCAN) "$(PATH)" --preset mixed --db "$(DB_FILE)"

.PHONY: scan-dry-run
scan-dry-run:  ## Show what scan would execute without running
	@echo "🔍 Analyzing $(PATH) (dry-run mode)..."
	$(SMART_SCAN) "$(PATH)" --dry-run --db "$(DB_FILE)"

.PHONY: scan-presets
scan-presets:  ## Show all available scan presets and their settings
	@$(SMART_SCAN) --show-presets

# ============================================================================
# Hierarchical & Adaptive Scanning - ADVANCED
# ============================================================================

.PHONY: scan-hierarchical
scan-hierarchical:  ## Adaptive scan - analyzes each subfolder independently (unified)
	@echo "🌳 Hierarchical scan with unified database: $(PATH)"
	$(AUTO_SCAN) "$(PATH)" --db "$(DB_FILE)"

.PHONY: scan-hier-per-device
scan-hier-per-device:  ## Adaptive scan - per-device databases (legacy)
	@echo "🌳 Hierarchical scan with device-local database: $(PATH)"
	$(AUTO_SCAN) "$(PATH)" --per-device

.PHONY: scan-plan
scan-plan:  ## Analyze tree and propose optimal scan strategy
	@echo "📊 Analyzing directory tree for optimal scan strategy: $(PATH)"
	$(PLAN_SCAN) "$(PATH)" --db "$(DB_FILE)"

.PHONY: scan-plan-execute
scan-plan-execute:  ## Analyze and execute optimal scan plan
	@echo "🚀 Planning and executing optimal scan: $(PATH)"
	$(PLAN_SCAN) "$(PATH)" --execute --db "$(DB_FILE)"

.PHONY: scan-hier-dry
scan-hier-dry:  ## Preview hierarchical scan plan without executing
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
# Legacy Operations (Pre-smart-scan)
# ============================================================================

.PHONY: scan
scan:  ## Basic scan (legacy, use scan-auto instead)
	@echo "📦 Scanning with basic settings..."
	@python -m hashall.scan "$(PATH)" --db "$(DB_FILE)"

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
