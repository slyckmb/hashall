# gptrail: linex-hashall-001-19Jun25-json-scan-docker-b2d406

# Makefile for hashall
# Place in root of repo

REPO_DIR := $(shell pwd)
DB_DIR := $(HOME)/.hashall
DB_FILE := $(DB_DIR)/hashall.sqlite3
HASHALL_IMG := hashall

.DEFAULT_GOAL := help

.PHONY: help bootstrap build docker-scan docker-export docker-test clean sandbox test

## bootstrap         Prepare environment (clone, venv, db dir, ~/.bin link)
bootstrap:
	@echo "🚀 Bootstrapping hashall repo setup..."
	@.setup/bootstrap-hashall.sh

## build             Build Docker image for hashall
build:
	@echo "🐳 Building Docker image: $(HASHALL_IMG)"
	docker build -t $(HASHALL_IMG) .

## docker-scan       Run scan inside Docker container
docker-scan:
	@echo "📦 Running scan in Docker..."
	@scripts/docker_scan_and_export.sh scan

## docker-export     Export .json from latest scan inside Docker
docker-export:
	@echo "📤 Running export in Docker..."
	@scripts/docker_scan_and_export.sh export

## docker-test       Run full scan + export test in Docker
docker-test:
	@echo "🧪 Running Docker scan + export test..."
	@scripts/docker_test.sh

## sandbox           Regenerate local test sandbox
sandbox:
	@echo "🔁 Resetting test sandbox..."
	@bash tests/generate_sandbox.sh

## test              Run full CLI smoke test
test:
	@echo "🧪 Running full smoke test..."
	@bash tests/smoke_test.sh

## clean             Remove generated files and sandbox
clean:
	@echo "🧹 Cleaning up..."
	rm -rf sandbox/ tmp/
	rm -f $(DB_FILE)

## help              Show this help message
help:
	@echo "🧰 Hashall Make Targets:"
	@awk '/^[a-zA-Z\-\_]+:/ {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$NF}' $(MAKEFILE_LIST) | sed 's/://'
