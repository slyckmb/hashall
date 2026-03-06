# Minimal Makefile — use hashall and rehome CLI directly.
# The original 927-line Makefile is archived at bin/archive/Makefile.archived
# Rebuild from scratch once the simplified CLI stabilizes.

.PHONY: help test

help:
	@echo "Use the CLI directly:"
	@echo "  rehome auto --help"
	@echo "  rehome config show"
	@echo "  hashall --help"
	@echo ""
	@echo "  make test   — run test suite"

test:
	python -m pytest tests/ -q
