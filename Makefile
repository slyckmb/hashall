# Minimal Makefile — use hashall and rehome CLI directly.
# The original 927-line Makefile is archived at bin/archive/Makefile.archived
# Rebuild from scratch once the simplified CLI stabilizes.

.PHONY: help test db-refresh db-refresh-verbose

help:
	@echo "Use the CLI directly:"
	@echo "  rehome auto --help"
	@echo "  rehome config show"
	@echo "  hashall --help"
	@echo ""
	@echo "  make test              — run test suite"
	@echo "  make db-refresh        — incremental catalog update + dedup"
	@echo "  make db-refresh-verbose — same, with verbose output and logging"

test:
	python -m pytest tests/ -q

db-refresh:
	python3 -m hashall refresh $(REFRESH_OPTS)

db-refresh-verbose:
	python3 -m hashall refresh --verbose $(REFRESH_OPTS) 2>&1 | tee ~/.logs/hashall/refresh-$$(date +%Y%m%d-%H%M%S).log
