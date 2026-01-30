# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# Makefile for hashall

REPO_DIR := $(shell pwd)
DB_DIR := $(HOME)/.hashall
DB_FILE := $(DB_DIR)/hashall.sqlite3
HASHALL_IMG := hashall

.DEFAULT_GOAL := help

.PHONY: help bootstrap build docker-scan docker-export docker-test clean sandbox test scan export verify verify-trees diff version

bootstrap:  ## Prepare environment (clone, venv, db dir, ~/.bin link)
	@echo "🚀 Bootstrapping hashall repo setup..."
	@.setup/bootstrap-hashall.sh

build:  ## Build Docker image for hashall
	@echo "🐳 Building Docker image: $(HASHALL_IMG)"
	docker build -t $(HASHALL_IMG) .

scan:  ## Scan sandbox using hashall
	@echo "📦 Scanning sandbox with hashall..."
	@python -m src.hashall scan sandbox

export:  ## Export hashall metadata from sandbox
	@echo "📤 Exporting scan JSON..."
	@python -m src.hashall export sandbox

verify-trees:  ## Verify that dst matches src (sandbox-based test)
	@echo "🔍 Verifying two directories..."
	@python -m src.hashall verify-trees sandbox/seed sandbox/backup --force

verify:  ## Run scan in verify mode
	@echo "🧪 Verifying hashes in verify mode..."
	@python -m src.hashall scan sandbox --mode verify

diff:  ## Run diff tool (if available)
	@echo "🧾 Running treehash diff..."
	@python -m src.hashall.diff

version:  ## Show current version
	@python -c "from src.hashall import __version__; print(__version__)"

docker-scan:  ## Run scan inside Docker container
	@echo "📦 Running scan in Docker..."
	@scripts/docker_scan_and_export.sh scan

docker-export:  ## Export .json from latest scan inside Docker
	@echo "📤 Running export in Docker..."
	@scripts/docker_scan_and_export.sh export

docker-test:  ## Run full scan + export test in Docker
	@echo "🧪 Running Docker scan + export test..."
	@scripts/docker_test.sh

sandbox:  ## Regenerate local test sandbox
	@echo "🔁 Resetting test sandbox..."
	@bash tests/generate_sandbox.sh

test:  ## Run full CLI smoke test
	@echo "🧪 Running full smoke test..."
	@bash tests/smoke_test.sh

clean:  ## Remove generated files and sandbox
	@echo "🧹 Cleaning up..."
	rm -rf sandbox/ tmp/
	rm -f $(DB_FILE)

help:  ## Show this help message
	@echo "🧰 Hashall Make Targets:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
