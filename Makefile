# Minimal Makefile — use hashall and rehome CLI directly.
# The original 927-line Makefile is archived at bin/archive/Makefile.archived
# Rebuild from scratch once the simplified CLI stabilizes.

TRK_WARN_SCRIPT := $(HOME)/dev/sys/docker/gluetun_qbit/rtorrent_vpn/bin/rt-tracker-manual-report.py
HASHALL_CLI := python3 -m hashall.cli
REHOME_CLI := python3 -m rehome.cli
CATALOG ?= $(HOME)/.hashall/catalog.db

.PHONY: help test db-refresh db-refresh-verbose db-refresh-fast db-refresh-maintenance db-refresh-integrity \
	db-refresh-fast-gated db-refresh-fast-parallel db-refresh-fast-gated-parallel \
        rt-qb-mirror-drift rt-qb-mirror-apply rt-qb-mirror-pause-seeding rt-qb-mirror-queue-apply \
        client-drift-audit client-drift-path-drift client-drift-selected \
        client-drift-rank \
        client-drift-rt-to-qb-dry client-drift-rt-to-qb-apply \
        client-drift-qb-to-rt-dry client-drift-qb-to-rt-apply \
        rt-repoint-dry rt-repoint-apply \
        cross-seed-normalize-dry cross-seed-normalize-apply \
        hitchhiker-audit hitchhiker-plan hitchhiker-split-dry hitchhiker-split-apply \
        save-path-audit save-path-repair-dry save-path-repair-apply save-path-recover-dry save-path-recover-apply \
        rehome-auto-dry rehome-auto-apply rehome-relocate-plan rehome-normalize-plan rehome-drift-audit \
        qb-missing-audit qb-missing-remediate-dry qb-missing-remediate-apply \
        payload-show payload-siblings \
        trk-warn trk-warn-prowlarr trk-warn-dry trk-warn-cleanup trk-warn-upgrade-packs

help:
	@echo "Use the CLI directly:"
	@echo "  rehome auto --help"
	@echo "  rehome config show"
	@echo "  hashall --help"
	@echo ""
	@echo "  make test                    — run test suite"
	@echo "  make db-refresh              — maintenance refresh (scan + dedup + payload SHA256 upgrade)"
	@echo "  make db-refresh-fast         — fast freshness refresh for client-repair evidence"
	@echo "  make db-refresh-fast-gated   — fast refresh + skip dedup if no changes (Phase 3B)"
	@echo "  make db-refresh-fast-parallel — fast refresh with parallel 4-root scanning (Phase 4A)"
	@echo "  make db-refresh-fast-gated-parallel — fast refresh with both optimizations (recommended)"
	@echo "  make db-refresh-maintenance  — explicit maintenance refresh"
	@echo "  make db-refresh-integrity    — slow full rehash integrity refresh"
	@echo "  make db-refresh-verbose      — maintenance refresh with verbose output and logging"
	@echo ""
	@echo "  make rt-qb-mirror-drift      — show RT-only items safe to mirror into qB"
	@echo "  make rt-qb-mirror-apply      — add safe RT-only items, recheck, monitor, re-stop"
	@echo "  make rt-qb-mirror-apply NO_MONITOR=1 — fire-and-forget (no post-recheck stop)"
	@echo "  make rt-qb-mirror-pause-seeding — pause any client-drift mirror items now in seeding state"
	@echo "  make rt-qb-mirror-queue-apply — process RT-completion queue → qB (mirrors queued RT items)"
	@echo ""
	@echo "  make client-drift-audit        — classify qB/RT membership + path drift from caches"
	@echo "  make client-drift-path-drift   — show only same-hash qB/RT path drift"
	@echo "  make client-drift-rank         — group path drift easy→hard with ARR/noHL/payload evidence"
	@echo "  make client-drift-selected HASH=<hash> ANCHOR_SCAN=200000 — selected drift evidence"
	@echo "  make client-drift-rt-to-qb-dry HASH=<hash> — dry-run RT repoint to qB path"
	@echo "  make client-drift-rt-to-qb-apply HASH=<hash> — apply RT repoint to qB path"
	@echo "  make client-drift-qb-to-rt-dry HASH=<hash> — dry-run qB savepath change to RT path"
	@echo "  make client-drift-qb-to-rt-apply HASH=<hash> — apply qB savepath change to RT path"
	@echo ""
	@echo "  make hitchhiker-audit          — find N→1 payload groups and split safety"
	@echo "  make hitchhiker-plan HASH=<hash>|PAYLOAD_ID=<id> — selected de-hitchhiker evidence"
	@echo "  make hitchhiker-split-dry HASH=<hash>|PAYLOAD_ID=<id> — dry-run unique payload hardlink split"
	@echo "  make hitchhiker-split-apply HASH=<hash>|PAYLOAD_ID=<id> — apply selected hardlink split + repoints"
	@echo ""
	@echo "  make cross-seed-normalize-dry HASH=<hash> — dry-run cross-seed-link → tracker savepath"
	@echo "  make cross-seed-normalize-apply HASH=<hash> — apply cross-seed-link normalization"
	@echo "  make save-path-audit           — audit inferred canonical save path drift"
	@echo "  make save-path-repair-dry      — dry-run _rehome-unique → canonical savepath repair"
	@echo "  make save-path-recover-dry     — dry-run missingFiles recovery from prior bad savepath moves"
	@echo ""
	@echo "  make rehome-auto-dry PLAN=<path>       — dry-run a rehome plan"
	@echo "  make rehome-auto-apply PLAN=<path>     — apply a rehome plan"
	@echo "  make rehome-relocate-plan SOURCE_ROOT=<path> TARGET_ROOT=<path> SOURCE_DEVICE=<dev> TARGET_DEVICE=<dev>"
	@echo "  make rehome-normalize-plan POOL_DEVICE=<dev> POOL_ROOT=<path> STASH_ROOT=<path>"
	@echo "  make qb-missing-audit SOURCE_ROOT=<old> TARGET_ROOT=<new> — audit missingFiles root drift"
	@echo "  make qb-missing-remediate-dry SOURCE_ROOT=<old> TARGET_ROOT=<new> — dry-run qB missing remediation"
	@echo ""
	@echo "  make trk-warn                — list RT tracker-warning items (deleted/auth_err/other)"
	@echo "  make trk-warn-prowlarr       — same, with Prowlarr replacement search"
	@echo "  make trk-warn-dry            — dry-run: plan removes + season-pack upgrades for deleted+other"
	@echo "  make trk-warn-cleanup        — execute cleanup: remove deleted+other (no upgrades), sync to qB"
	@echo "  make trk-warn-upgrade-packs  — season pack upgrades: erase individual eps, add pack, sync to qB"
	@echo ""
	@echo "  Vars: LIMIT=N HASH=<hash> PAYLOAD_ID=<id> JSON=1 ANCHOR_SCAN=N CATALOG=<db> JOURNAL=<path> SLEEP_ROW=N"

test:
	python -m pytest tests/ -q

db-refresh:
	python3 -m hashall refresh --profile maintenance $(REFRESH_OPTS)

db-refresh-fast:
	python3 -m hashall refresh --profile freshness $(REFRESH_OPTS)

db-refresh-fast-gated:
	python3 -m hashall refresh --profile freshness --gate-dedup-on-unchanged $(REFRESH_OPTS)

db-refresh-fast-parallel:
	python3 -m hashall refresh --profile freshness --parallel-scans 4 $(REFRESH_OPTS)

db-refresh-fast-gated-parallel:
	python3 -m hashall refresh --profile freshness --gate-dedup-on-unchanged --parallel-scans 4 $(REFRESH_OPTS)

db-refresh-maintenance:
	python3 -m hashall refresh --profile maintenance $(REFRESH_OPTS)

db-refresh-integrity:
	python3 -m hashall refresh --profile integrity $(REFRESH_OPTS)

db-refresh-verbose:
	python3 -m hashall refresh --profile maintenance --verbose $(REFRESH_OPTS) 2>&1 | tee ~/.logs/hashall/refresh-$$(date +%Y%m%d-%H%M%S).log

rt-qb-mirror-drift:
	@python3 -m hashall.cli rt-qb-mirror sync --limit $${LIMIT:-0} --sleep-row 0 --journal $${JOURNAL:-/tmp/hashall-rt-qb-mirror-drift.jsonl}

rt-qb-mirror-apply:
	@MONITOR_OPTS="--monitor --monitor-timeout $${MONITOR_TIMEOUT:-900} --monitor-interval $${MONITOR_INTERVAL:-10}"; if [ "$${NO_MONITOR:-0}" = "1" ]; then MONITOR_OPTS="--no-monitor"; fi; python3 -m hashall.cli rt-qb-mirror sync --limit $${LIMIT:-0} --apply --sleep-row $${SLEEP_ROW:-5} $$MONITOR_OPTS --journal $${JOURNAL:-/tmp/hashall-rt-qb-mirror-apply.jsonl}

rt-qb-mirror-pause-seeding:
	@python3 scripts/pause_mirror_seeders.py

rt-qb-mirror-queue-apply:
	@MONITOR_OPTS="--monitor --monitor-timeout $${MONITOR_TIMEOUT:-900} --monitor-interval $${MONITOR_INTERVAL:-10}"; if [ "$${NO_MONITOR:-0}" = "1" ]; then MONITOR_OPTS="--no-monitor"; fi; python3 -m hashall.cli rt-qb-mirror process-queue --queue-dir /dump/docker/gluetun_qbit/rtorrent_vpn/rt-qb-mirror-queue --apply --min-age $${MIN_AGE:-120} --limit $${LIMIT:-20} --sleep-row $${SLEEP_ROW:-5} $$MONITOR_OPTS --journal $${JOURNAL:-/tmp/hashall-rt-qb-mirror-queue.jsonl}

client-drift-audit:
	@$(HASHALL_CLI) client-drift audit --catalog "$(CATALOG)" --anchor-scan-max-files $${ANCHOR_SCAN:-0} --limit $${LIMIT:-0} $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

client-drift-path-drift:
	@$(HASHALL_CLI) client-drift audit --catalog "$(CATALOG)" --side path_drift --anchor-scan-max-files $${ANCHOR_SCAN:-0} --limit $${LIMIT:-0} $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

client-drift-rank:
	@$(HASHALL_CLI) client-drift rank --catalog "$(CATALOG)" --anchor-scan-max-files $${ANCHOR_SCAN:-200000} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}") $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

client-drift-selected:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) client-drift audit --catalog "$(CATALOG)" --hash "$${HASH}" --anchor-scan-max-files $${ANCHOR_SCAN:-200000} --limit $${LIMIT:-0} $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

client-drift-rt-to-qb-dry:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) client-drift apply --action repoint_rt_to_qb_path --catalog "$(CATALOG)" --hash "$${HASH}" --anchor-scan-max-files $${ANCHOR_SCAN:-200000} --sleep-row $${SLEEP_ROW:-0} --journal "$${JOURNAL:-out/client-drift/path-drift-rt-to-qb.jsonl}"

client-drift-rt-to-qb-apply:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) client-drift apply --action repoint_rt_to_qb_path --catalog "$(CATALOG)" --hash "$${HASH}" --anchor-scan-max-files $${ANCHOR_SCAN:-200000} --sleep-row $${SLEEP_ROW:-5} --journal "$${JOURNAL:-out/client-drift/path-drift-rt-to-qb.jsonl}" --apply

client-drift-qb-to-rt-dry:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) client-drift apply --action repoint_qb_to_rt_path --catalog "$(CATALOG)" --hash "$${HASH}" --anchor-scan-max-files $${ANCHOR_SCAN:-200000} --sleep-row $${SLEEP_ROW:-0} --journal "$${JOURNAL:-out/client-drift/path-drift-qb-to-rt.jsonl}"

client-drift-qb-to-rt-apply:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) client-drift apply --action repoint_qb_to_rt_path --catalog "$(CATALOG)" --hash "$${HASH}" --anchor-scan-max-files $${ANCHOR_SCAN:-200000} --sleep-row $${SLEEP_ROW:-5} --journal "$${JOURNAL:-out/client-drift/path-drift-qb-to-rt.jsonl}" --apply

rt-repoint-dry:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; [ -n "$${TARGET:-}" ] || { echo "TARGET is required"; exit 2; }; $(HASHALL_CLI) rt repoint --hash "$${HASH}" --target-directory "$${TARGET}"

rt-repoint-apply:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; [ -n "$${TARGET:-}" ] || { echo "TARGET is required"; exit 2; }; $(HASHALL_CLI) rt repoint --hash "$${HASH}" --target-directory "$${TARGET}" --apply

cross-seed-normalize-dry:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) payload normalize-cross-seed-link --hash "$${HASH}" $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

cross-seed-normalize-apply:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) payload normalize-cross-seed-link --hash "$${HASH}" --apply $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

hitchhiker-audit:
	@$(HASHALL_CLI) payload hitchhiker-audit --limit $${LIMIT:-0} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}") $$([ -n "$${PAYLOAD_ID:-}" ] && echo "--payload-id $${PAYLOAD_ID}") $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

hitchhiker-plan:
	@SEL_OPTS=""; if [ -n "$${HASH:-}" ]; then SEL_OPTS="$$SEL_OPTS --hash $${HASH}"; fi; if [ -n "$${PAYLOAD_ID:-}" ]; then SEL_OPTS="$$SEL_OPTS --payload-id $${PAYLOAD_ID}"; fi; [ -n "$$SEL_OPTS" ] || { echo "HASH or PAYLOAD_ID is required"; exit 2; }; $(HASHALL_CLI) payload hitchhiker-plan $$SEL_OPTS $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

hitchhiker-split-dry:
	@SEL_OPTS=""; if [ -n "$${HASH:-}" ]; then SEL_OPTS="$$SEL_OPTS --hash $${HASH}"; fi; if [ -n "$${PAYLOAD_ID:-}" ]; then SEL_OPTS="$$SEL_OPTS --payload-id $${PAYLOAD_ID}"; fi; [ -n "$$SEL_OPTS" ] || { echo "HASH or PAYLOAD_ID is required"; exit 2; }; $(HASHALL_CLI) payload hitchhiker-split $$SEL_OPTS --dry-run $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

hitchhiker-split-apply:
	@SEL_OPTS=""; if [ -n "$${HASH:-}" ]; then SEL_OPTS="$$SEL_OPTS --hash $${HASH}"; fi; if [ -n "$${PAYLOAD_ID:-}" ]; then SEL_OPTS="$$SEL_OPTS --payload-id $${PAYLOAD_ID}"; fi; [ -n "$$SEL_OPTS" ] || { echo "HASH or PAYLOAD_ID is required"; exit 2; }; $(HASHALL_CLI) payload hitchhiker-split $$SEL_OPTS --execute $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

save-path-audit:
	@$(HASHALL_CLI) payload save-path-audit --limit $${LIMIT:-0} $$([ "$${DRIFTED_ONLY:-1}" = "1" ] && echo "--drifted-only") $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

save-path-repair-dry:
	@$(HASHALL_CLI) payload save-path-repair --dry-run --limit $${LIMIT:-0} $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

save-path-repair-apply:
	@$(HASHALL_CLI) payload save-path-repair --execute --limit $${LIMIT:-0} $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

save-path-recover-dry:
	@$(HASHALL_CLI) payload save-path-recover --dry-run --limit $${LIMIT:-0} $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

save-path-recover-apply:
	@$(HASHALL_CLI) payload save-path-recover --execute --limit $${LIMIT:-0} $$([ "$${JSON:-0}" = "1" ] && echo "--json-output")

payload-show:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) payload show "$${HASH}"

payload-siblings:
	@[ -n "$${HASH:-}" ] || { echo "HASH is required"; exit 2; }; $(HASHALL_CLI) payload siblings "$${HASH}"

rehome-auto-dry:
	@[ -n "$${PLAN:-}" ] || { echo "PLAN is required"; exit 2; }; $(REHOME_CLI) apply "$${PLAN}" --dryrun

rehome-auto-apply:
	@[ -n "$${PLAN:-}" ] || { echo "PLAN is required"; exit 2; }; $(REHOME_CLI) apply "$${PLAN}" --force

rehome-relocate-plan:
	@[ -n "$${SOURCE_ROOT:-}" ] || { echo "SOURCE_ROOT is required"; exit 2; }; [ -n "$${TARGET_ROOT:-}" ] || { echo "TARGET_ROOT is required"; exit 2; }; [ -n "$${SOURCE_DEVICE:-}" ] || { echo "SOURCE_DEVICE is required"; exit 2; }; [ -n "$${TARGET_DEVICE:-}" ] || { echo "TARGET_DEVICE is required"; exit 2; }; $(REHOME_CLI) relocate-plan --catalog "$(CATALOG)" --source-device "$${SOURCE_DEVICE}" --source-root "$${SOURCE_ROOT}" --target-device "$${TARGET_DEVICE}" --target-root "$${TARGET_ROOT}" --limit $${LIMIT:-0} $$([ -n "$${REFERENCE_ROOT:-}" ] && echo "--reference-root $${REFERENCE_ROOT}") $$([ -n "$${OUTPUT:-}" ] && echo "--output $${OUTPUT}")

rehome-normalize-plan:
	@[ -n "$${POOL_DEVICE:-}" ] || { echo "POOL_DEVICE is required"; exit 2; }; [ -n "$${POOL_ROOT:-}" ] || { echo "POOL_ROOT is required"; exit 2; }; $(REHOME_CLI) normalize-plan --catalog "$(CATALOG)" --pool-device "$${POOL_DEVICE}" --pool-seeding-root "$${POOL_ROOT}" --limit $${LIMIT:-0} $$([ -n "$${STASH_ROOT:-}" ] && echo "--stash-seeding-root $${STASH_ROOT}") $$([ -n "$${OUTPUT:-}" ] && echo "--output $${OUTPUT}")

rehome-drift-audit:
	@[ -n "$${PLAN:-}" ] || { echo "PLAN is required"; exit 2; }; $(REHOME_CLI) drift-audit "$${PLAN}" --catalog "$(CATALOG)" $$([ -n "$${OUTPUT:-}" ] && echo "--output $${OUTPUT}")

qb-missing-audit:
	@[ -n "$${SOURCE_ROOT:-}" ] || { echo "SOURCE_ROOT is required"; exit 2; }; [ -n "$${TARGET_ROOT:-}" ] || { echo "TARGET_ROOT is required"; exit 2; }; $(REHOME_CLI) qb-missing-audit --catalog "$(CATALOG)" --source-root "$${SOURCE_ROOT}" --target-root "$${TARGET_ROOT}" $$([ -n "$${OUTPUT:-}" ] && echo "--output $${OUTPUT}")

qb-missing-remediate-dry:
	@[ -n "$${SOURCE_ROOT:-}" ] || { echo "SOURCE_ROOT is required"; exit 2; }; [ -n "$${TARGET_ROOT:-}" ] || { echo "TARGET_ROOT is required"; exit 2; }; $(REHOME_CLI) qb-missing-remediate --catalog "$(CATALOG)" --source-root "$${SOURCE_ROOT}" --target-root "$${TARGET_ROOT}" --dryrun --limit $${LIMIT:-0} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}") $$([ -n "$${OUTPUT:-}" ] && echo "--output $${OUTPUT}")

qb-missing-remediate-apply:
	@[ -n "$${SOURCE_ROOT:-}" ] || { echo "SOURCE_ROOT is required"; exit 2; }; [ -n "$${TARGET_ROOT:-}" ] || { echo "TARGET_ROOT is required"; exit 2; }; $(REHOME_CLI) qb-missing-remediate --catalog "$(CATALOG)" --source-root "$${SOURCE_ROOT}" --target-root "$${TARGET_ROOT}" --apply --limit $${LIMIT:-0} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}") $$([ -n "$${OUTPUT:-}" ] && echo "--output $${OUTPUT}")

trk-warn:
	@python3 $(TRK_WARN_SCRIPT) --bucket $${BUCKET:-deleted,auth_err,other} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}") $$([ -n "$${LIMIT:-}" ] && echo "--limit $${LIMIT}")

trk-warn-prowlarr:
	@python3 $(TRK_WARN_SCRIPT) --prowlarr --bucket $${BUCKET:-deleted,auth_err,other} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}") $$([ -n "$${LIMIT:-}" ] && echo "--limit $${LIMIT}")

trk-warn-dry:
	@python3 $(TRK_WARN_SCRIPT) --dryrun --prowlarr --bucket $${BUCKET:-deleted,other} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}")

trk-warn-cleanup:
	@python3 $(TRK_WARN_SCRIPT) --cleanup --bucket $${BUCKET:-deleted,other} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}")

trk-warn-upgrade-packs:
	@python3 $(TRK_WARN_SCRIPT) --cleanup --repair --prowlarr --bucket $${BUCKET:-deleted} $$([ -n "$${HASH:-}" ] && echo "--hash $${HASH}")
