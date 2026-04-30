# Minimal Makefile — use hashall and rehome CLI directly.
# The original 927-line Makefile is archived at bin/archive/Makefile.archived
# Rebuild from scratch once the simplified CLI stabilizes.

TRK_WARN_SCRIPT := $(HOME)/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py

.PHONY: help test db-refresh db-refresh-verbose \
        rt-qb-mirror-drift rt-qb-mirror-apply rt-qb-mirror-pause-seeding rt-qb-mirror-queue-apply \
        trk-warn trk-warn-prowlarr trk-warn-dry trk-warn-cleanup

help:
	@echo "Use the CLI directly:"
	@echo "  rehome auto --help"
	@echo "  rehome config show"
	@echo "  hashall --help"
	@echo ""
	@echo "  make test                    — run test suite"
	@echo "  make db-refresh              — incremental catalog update + dedup"
	@echo "  make db-refresh-verbose      — same, with verbose output and logging"
	@echo ""
	@echo "  make rt-qb-mirror-drift      — show RT-only items safe to mirror into qB"
	@echo "  make rt-qb-mirror-apply      — add safe RT-only items, recheck, monitor, re-stop"
	@echo "  make rt-qb-mirror-apply NO_MONITOR=1 — fire-and-forget (no post-recheck stop)"
	@echo "  make rt-qb-mirror-pause-seeding — pause any client-drift mirror items now in seeding state"
	@echo "  make rt-qb-mirror-queue-apply — process RT-completion queue → qB (mirrors queued RT items)"
	@echo ""
	@echo "  make trk-warn                — list RT tracker-warning items (deleted/auth_err/other)"
	@echo "  make trk-warn-prowlarr       — same, with Prowlarr replacement search"
	@echo "  make trk-warn-dry            — dry-run cleanup: plan removes for deleted+other"
	@echo "  make trk-warn-cleanup        — execute cleanup: remove deleted+other, sync to qB"
	@echo ""
	@echo "  Vars: LIMIT=N BUCKET=deleted,auth_err,other HASH=<hash> SLEEP_ROW=N"

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

rt-qb-mirror-pause-seeding:
	@python3 - <<'EOF'
	import json, sys
	from pathlib import Path
	sys.path.insert(0, '.')
	from src.hashall.qbittorrent import get_qbittorrent_client
	qb = get_qbittorrent_client()
	cache = json.loads(Path.home().joinpath('.cache/hashall-qb/torrents-info.json').read_text())
	seeding_states = {'stalledUP', 'uploading', 'forcedUP', 'queuedUP'}
	targets = [t for t in cache if t.get('state') in seeding_states
	           and ('hashall-client-drift' in (t.get('tags') or '')
	                or 'hashall-rt-qb-mirror' in (t.get('tags') or ''))]
	if not targets:
	    print('No seeding mirror items found.')
	    sys.exit(0)
	print(f'Pausing {len(targets)} seeding mirror item(s)...')
	ok = err = 0
	for t in targets:
	    h = t['hash']
	    if qb.pause_torrent(h):
	        print(f'  paused  {h[:16]}: {t["name"][:55]}')
	        ok += 1
	    else:
	        print(f'  FAILED  {h[:16]}: {t["name"][:55]}')
	        err += 1
	print(f'Done: {ok} paused, {err} failed.')
	EOF

rt-qb-mirror-queue-apply:
	@MONITOR_OPTS="--monitor --monitor-timeout $${MONITOR_TIMEOUT:-900} --monitor-interval $${MONITOR_INTERVAL:-10}"; if [ "$${NO_MONITOR:-0}" = "1" ]; then MONITOR_OPTS="--no-monitor"; fi; python3 -m hashall.cli rt-qb-mirror process-queue --apply --min-age $${MIN_AGE:-120} --limit $${LIMIT:-20} --sleep-row $${SLEEP_ROW:-5} $$MONITOR_OPTS --journal $${JOURNAL:-/tmp/hashall-rt-qb-mirror-queue.jsonl}

trk-warn:
	@python3 $(TRK_WARN_SCRIPT) --bucket $${BUCKET:-deleted,auth_err,other} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}") $$([ -n "$${LIMIT:-}" ] && echo "--limit $${LIMIT}")

trk-warn-prowlarr:
	@python3 $(TRK_WARN_SCRIPT) --prowlarr --bucket $${BUCKET:-deleted,auth_err,other} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}") $$([ -n "$${LIMIT:-}" ] && echo "--limit $${LIMIT}")

trk-warn-dry:
	@python3 $(TRK_WARN_SCRIPT) --dryrun --bucket $${BUCKET:-deleted,other} --qb-sync $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}")

trk-warn-cleanup:
	@python3 $(TRK_WARN_SCRIPT) --cleanup --bucket $${BUCKET:-deleted,other} --qb-sync $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}")
