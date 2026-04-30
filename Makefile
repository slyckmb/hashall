# Minimal Makefile — use hashall and rehome CLI directly.
# The original 927-line Makefile is archived at bin/archive/Makefile.archived
# Rebuild from scratch once the simplified CLI stabilizes.

.PHONY: help test db-refresh db-refresh-verbose rt-qb-mirror-drift rt-qb-mirror-apply

help:
	@echo "Use the CLI directly:"
	@echo "  rehome auto --help"
	@echo "  rehome config show"
	@echo "  hashall --help"
	@echo ""
	@echo "  make test              — run test suite"
	@echo "  make db-refresh        — incremental catalog update + dedup"
	@echo "  make db-refresh-verbose — same, with verbose output and logging"
	@echo "  make rt-qb-mirror-drift — show RT-only items safe to mirror into qB"
	@echo "  make rt-qb-mirror-apply — add safe RT-only items, recheck all, then monitor batch"
	@echo "  make rt-qb-mirror-apply NO_MONITOR=1 — fire-and-forget after starting qB rechecks"

test:
	python -m pytest tests/ -q

db-refresh:
	python3 -m hashall refresh $(REFRESH_OPTS)

db-refresh-verbose:
	python3 -m hashall refresh --verbose $(REFRESH_OPTS) 2>&1 | tee ~/.logs/hashall/refresh-$$(date +%Y%m%d-%H%M%S).log

rt-qb-mirror-drift:
	@python3 -m hashall.cli rt-qb-mirror sync --limit $${LIMIT:-0} --sleep-row 0 --journal $${JOURNAL:-/tmp/hashall-rt-qb-mirror-drift.jsonl}

rt-qb-mirror-apply:
	@MONITOR_OPTS="--monitor --monitor-timeout $${MONITOR_TIMEOUT:-900} --monitor-interval $${MONITOR_INTERVAL:-10}"; if [ "$${NO_MONITOR:-0}" = "1" ]; then MONITOR_OPTS="--no-monitor"; fi; python3 -m hashall.cli rt-qb-mirror sync --limit $${LIMIT:-0} --apply --sleep-row $${SLEEP_ROW:-5} $$MONITOR_OPTS --journal $${JOURNAL:-/tmp/hashall-rt-qb-mirror-apply.jsonl}
