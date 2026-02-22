SECTION A — Current Project State (as of 17 FEB 2026)

What hashall is (one sentence)
Hashall is a catalog + hashing system that scans files across devices into a unified SQLite catalog, tracks hashes/hardlinks/payloads, and supports qBittorrent-aware workflows (and downstream orchestration like rehome). (Confirmed) [evidence: REQUIREMENTS.md :: 7. Catalog System (hashall) — “unified catalog model … one SQLite DB”] [evidence: REQUIREMENTS.md :: 7.4 Payload Tracking & qBittorrent Sync — “payloads … torrent_instances … qBittorrent API”]

Implemented capabilities (concise)
- Unified SQLite catalog at `~/.hashall/catalog.db` with device registry and scan roots/sessions. (Confirmed) [evidence: REQUIREMENTS.md :: 7.1 Unified Catalog Model — “one SQLite DB at ~/.hashall/catalog.db”]
- SHA256 is the standard hash; SHA1 is legacy/optional; tooling exists for backfill/verification per requirements. (Confirmed) [evidence: REQUIREMENTS.md :: 7.2 Hashing Standard — “SHA256 is the standard”] [evidence: REQUIREMENTS.md :: 11.1 Completed ✅ — “sha256-backfill and sha256-verify tools”]
- Incremental scanning with scoped deletion checks; supports parallel scanning and WAL mode. (Confirmed) [evidence: REQUIREMENTS.md :: 7.3 Incremental Scanning & Performance — “incremental mode … only delete … scoped … parallel scanning … WAL”]
- Payload tracking + qBittorrent sync model (payloads/torrent_instances) is part of the system design and appears implemented in repo workflows/tests. (Likely) [evidence: REQUIREMENTS.md :: 7.4 Payload Tracking & qBittorrent Sync — “payloads … torrent_instances … Sync process”] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “tests/test_cli_payload_sync.py … tests/test_qbittorrent.py” mention]
- Hardlink-aware hashing optimization with hash source tracking (avoid re-hashing identical inodes) is implemented and committed. (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “Commit created: f49f579 — ‘feat: Add hardlink-aware hashing optimization with hash source tracking’”]
- Payload collision detection + “upgrade-collisions” pass exists and is committed. (Confirmed) [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “git commit … [main 6314b1d] … ‘payload: add collisions + upgrade-collisions pass’”]
- Rehome orchestration exists in repo (planner/executor/CLI) and has evidence of producing a plan and executing a demote+MOVE with qB mapping updates. (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “Rehome details … Decision: demote + MOVE … qB mapping now … status=success”]

Current CLI surface (flags/commands) — evidenced only
- Hashall commands: scan (exact flags Unknown from attachments), payload collisions, payload upgrade-collisions, payload sync (supports dry-run + path-prefix filtering + limit, exact flag spelling Unknown). (Confirmed/Likely mix) [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “git commit … [main aee326d] payload sync: add dry-run, path-prefix, limit”] [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “payload: add collisions + upgrade-collisions pass”]
- Makefile workflows exist for payload and hardlink flows (names observed: payload-auto, payload-workflow, payload-orphan-snapshot, scan, link-path/link-paths). (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “make workflow … make link-path / make link-paths … make scan”] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “make payload-auto … make payload-orphan-snapshot”]
- The REQUIREMENTS.md lists a “hashall link analyze/plan/show-plan/execute … -dry-run” interface, but exact parity with current CLI is Unknown (not directly shown in transcripts). (Unknown) [evidence: REQUIREMENTS.md :: 6.1 Same-Device Hardlink Dedup — “hashall link analyze … execute … -dry-run”]

Project structure (key modules/scripts) — evidenced only
- Python package layout includes `src/hashall/*` modules (cli, scan, payload, device, qbittorrent, link_*), plus scripts for payload/hardlink/rehome workflows; rehome also exists as `src/rehome/*`. (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: mentions “src/hashall/device.py … src/hashall/link_executor.py … scripts/payload_auto_workflow.py … src/rehome/planner.py”]

Test status (what exists / what ran / outcomes)
- Full pytest suite reported passing: “259 passed, 2 skipped.” (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “full suite passes (259 passed, 2 skipped)”]
- Hardlink scan regression tests exist and were run (e.g., `tests/test_scan_hardlinks.py`). (Confirmed) [evidence: 20260211-092716-claude-hashall-20260210-234624.txt :: “tests/test_scan_hardlinks.py … all six tests passed”]
- Payload sync tests exist (e.g., `tests/test_cli_payload_sync.py`) and were added/used during development. (Confirmed) [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “create mode … tests/test_cli_payload_sync.py”]
- Rehome-related tests exist in repo (multiple `tests/test_rehome_*`). (Likely) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “tests/test_rehome_*” list]

Known issues / risks (evidenced only)
- Versioning conflict across attachments: REQUIREMENTS claims hashall “v0.5.0+” completed, while transcripts report v0.4.3x bumps (e.g., 0.4.38). (Conflict) [evidence: REQUIREMENTS.md :: 11.1 Completed ✅ — “hashall … v0.5.0+”] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “patch-bumped to 0.4.38”]
- Payload-auto previously failed with a UNIQUE constraint on devices.device_id and required fixes (device-id collision handling, repo-local module resolution, honoring `--db`). (Confirmed) [evidence: 20260217-061709-claude-hashall-20260210-234624-payload-auto-workflow-catalog-detection.txt :: “UNIQUE constraint failed: devices.device_id … make payload-auto”] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “3cd46d6 fix(device,payload-auto): handle device-id UUID collisions and honor --db … 2c75bae fix(payload-auto): force repo-local module resolution”]
- Payload-sync can still fail if qBittorrent/auth/env is unavailable (even if logic is correct). (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “issues=payload-sync can still fail … if qBittorrent/auth/env is unavailable”]
- Conflicting transcript statements about payload-sync “no dryrun” vs a commit adding dry-run; current truth is Unknown without repo verification. (Conflict) [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “payload sync ALWAYS writes … no way to dryrun”] [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “git commit … [main aee326d] payload sync: add dry-run, path-prefix, limit”]

Requirements traceability (Rx status)
- R1 Unified Catalog Model — Met. [evidence: REQUIREMENTS.md :: 7.1 Unified Catalog Model — “one SQLite DB … device registry … scan roots/sessions”]
- R2 Hashing Standard + SHA256 migration tooling — Met. [evidence: REQUIREMENTS.md :: 7.2 Hashing Standard] [evidence: REQUIREMENTS.md :: 11.1 Completed ✅ — “sha256-backfill … sha256-verify”]
- R3 Incremental + parallel scanning + WAL — Met. [evidence: REQUIREMENTS.md :: 7.3 Incremental Scanning & Performance]
- R4 Payload tracking + qBittorrent sync — Partially Met (model + tests + workflows exist; runtime env dependency remains). [evidence: REQUIREMENTS.md :: 7.4 Payload Tracking & qBittorrent Sync] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “payload-sync can still fail … qBittorrent/auth/env”]
- R5 Payload collision handling / upgrade-collisions — Met. [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “[main 6314b1d] … collisions + upgrade-collisions pass”]
- R6 Same-device hardlink dedup system (analyze/plan/execute + safety) — Partially Met (core planner/executor exists; full safety/rollback parity with REQUIREMENTS is Unknown from transcripts). [evidence: REQUIREMENTS.md :: 6.1 Same-Device Hardlink Dedup] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “src/hashall/link_executor.py … tests/test_link_executor.py”]
- R7 Rehome orchestration (plan/apply) — Partially Met (evidence of plan + run; REQUIREMENTS still lists work “In Progress”). [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “Rehome details … status=success”] [evidence: REQUIREMENTS.md :: 11.2 In Progress 🚧 — “Move orchestration logic into rehome … Planner and Applier system”]
- R8 Operational qualities (safe by default, idempotent, auditable) — Partially Met. [evidence: REQUIREMENTS.md :: 9. Operational Requirements — “Safe by default … Auditable … Idempotent”] [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “payload sync: add dry-run … truly no-write”]
- R9 Success Criteria (functional + operational) — Partially Met pending explicit acceptance runs tied to §12. [evidence: REQUIREMENTS.md :: 12. Success Criteria — “Functional … Operational … Documentation”]


SECTION B — Key Accomplishments Toward Requirements

(Requirement index used below; labels derived from REQUIREMENTS.md)
- R1: Unified Catalog Model — single SQLite catalog at `~/.hashall/catalog.db`, device registry + scan roots/sessions. (Confirmed) [evidence: REQUIREMENTS.md :: 7.1 Unified Catalog Model — “one SQLite DB … device registry … scan roots/sessions”]
- R2: Hashing Standard + SHA256 migration tooling — SHA256 standard and migration support called “completed” in requirements. (Confirmed) [evidence: REQUIREMENTS.md :: 7.2 Hashing Standard] [evidence: REQUIREMENTS.md :: 11.1 Completed ✅ — “sha256-backfill … sha256-verify”]
- R3: Incremental + parallel scanning + WAL — incremental scanning and performance features marked completed in requirements. (Confirmed) [evidence: REQUIREMENTS.md :: 11.1 Completed ✅ — “Incremental scanning … parallel scanning … WAL mode”]
- R4: Payload tracking + qBittorrent sync — payload-sync improvements (dry-run/path-prefix/limit) and tests added; qB failure modes tightened (non-zero on auth/connect). (Confirmed) [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “[main aee326d] … payload sync: add dry-run, path-prefix, limit”] [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “[main bedaafb] payload sync: fail nonzero on qbit connect/auth errors”]
- R5: Payload collision handling / upgrade-collisions — collision detection + upgrade pass implemented and committed on main. (Confirmed) [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “[main 6314b1d] … collisions + upgrade-collisions pass”]
- R6: Same-device hardlink dedup system — hardlink-aware hashing optimization added (avoid redundant hashing across identical inodes) with tracked source + tests. (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “Commit created: f49f579 … hardlink-aware hashing optimization”] [evidence: 20260211-092716-claude-hashall-20260210-234624.txt :: “tests/test_scan_hardlinks.py … all six tests passed”]
- R7: Rehome orchestration — evidence of producing a plan artifact and executing demote+MOVE with catalog + qB mapping updates and recorded run status=success. (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “Plan file: out/rehome-plan-… Decision: demote + MOVE … status=success”]
- R8: Operational qualities — payload-auto crash path fixed (device collision + repo-local module resolution + honoring `--db`), plus loop-stall guard + telemetry, and the suite reported fully green. (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “3cd46d6 … handle device-id UUID collisions and honor --db … 2c75bae … repo-local module resolution”] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “b7d6ca6 … loop-stall guard … full suite passes (259 passed, 2 skipped)”]
- R9: Success Criteria / testing — full pytest run reported as passing (259 passed, 2 skipped), indicating broad automated coverage exists. (Confirmed) [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “full suite passes (259 passed, 2 skipped)”]


SECTION C — Key Gaps Remaining to Meet Requirements

R6: Same-device hardlink dedup system (analyze/plan/execute + safety)
- What’s missing: Direct evidence that the end-user CLI exactly matches REQUIREMENTS’ analyze/plan/show-plan/execute semantics and safety switches (exact flag spellings/UX Unknown). (Unknown) [evidence: REQUIREMENTS.md :: 6.1 Same-Device Hardlink Dedup — “hashall link analyze … show-plan … execute … -dry-run”]
- Why it matters: REQUIREMENTS makes the hardlink system a core dedup mechanism and specifies safety/rollback expectations. (Confirmed) [evidence: REQUIREMENTS.md :: 6.1 Same-Device Hardlink Dedup — “Safe, deterministic … backups … rollback”]

R7: Rehome orchestration (plan/apply separation; remaining “In Progress” scope)
- What’s missing: REQUIREMENTS still lists key rehome work as “In Progress” (move orchestration logic into rehome; planner/applier system; multiple action types). (Confirmed) [evidence: REQUIREMENTS.md :: 11.2 In Progress 🚧 — “Move orchestration logic into rehome … Planner and Applier system”]
- Why it matters: Meeting Success Criteria requires reliable demote/promote execution and integration across stash/pool with safety constraints. (Confirmed) [evidence: REQUIREMENTS.md :: 12. Success Criteria — “Functional … demotion/promotion … safe … auditable”]

R8: Operational qualities (safe-by-default and auditable behavior across workflows)
- What’s missing: Conflicting transcript evidence on whether payload-sync can be run in a truly non-writing mode; current truth needs repo verification and (if needed) enforcement. (Conflict) [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “payload sync ALWAYS writes … no way to dryrun”] [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “[main aee326d] … add dry-run”]
- Why it matters: REQUIREMENTS explicitly demands “Safe by default” and “Auditable,” and success criteria includes operational safety. (Confirmed) [evidence: REQUIREMENTS.md :: 9. Operational Requirements — “Safe by default … Auditable”] [evidence: REQUIREMENTS.md :: 12. Success Criteria — “Operational”]

R9: Documentation parity with actual implementation
- What’s missing: No direct transcript evidence that docs referenced in REQUIREMENTS (CLI + REHOME docs) are up to date with current CLI/workflows. (Unknown) [evidence: REQUIREMENTS.md :: 11.1 Completed ✅ — “Documentation is accurate and complete … docs/tooling/cli.md … docs/tooling/REHOME.md”]
- Why it matters: Success Criteria explicitly requires documentation accuracy/completeness. (Confirmed) [evidence: REQUIREMENTS.md :: 12. Success Criteria — “Documentation … must be accurate and complete”]

R10: Versioning alignment (internal consistency across artifacts)
- What’s missing: A single, non-conflicting “current version” across REQUIREMENTS vs transcripts. (Conflict) [evidence: REQUIREMENTS.md :: 11.1 Completed ✅ — “hashall … v0.5.0+”] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “patch-bumped to 0.4.38”]
- Why it matters: Operational clarity and reproducibility (users/tests/docs need a consistent baseline). (Likely) [evidence: REQUIREMENTS.md :: 9. Operational Requirements — “Auditable … understandable … seamless”]


SECTION D — Finish Plan (Dev + Test) to Meet Requirements

Assumptions
None; plan is evidence-driven. [evidence: REQUIREMENTS.md :: 12. Success Criteria — establishes what must be proven]

M1 — Evidence baseline + repo verification gate
- Scope: In a fresh worktree, verify (not assume) the current CLI surface and versions, and reconcile conflicts (REQUIREMENTS vs transcripts) by inspecting the repo and CLI help output. [evidence: REQUIREMENTS.md :: 11.1 Completed ✅ — contains version claim] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: contains 0.4.38 bump claim]
- Validation: Run full test suite (`pytest -q`) and capture output; run CLI `--help` for hashall and any rehome entrypoint to enumerate commands/flags. [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “full suite passes (259 passed, 2 skipped)”]
- Exit criteria: A short “repo-facts” note with exact observed version(s), exact subcommands/flags, and the test summary pasted verbatim. (Observable)
- Risk/rollback: Read-only verification only; no destructive actions; no db writes unless explicitly in dry-run mode. [evidence: REQUIREMENTS.md :: 9. Operational Requirements — “Safe by default”]

M2 — Payload sync safety + determinism gate
- Scope: Verify payload-sync dry-run semantics and failure modes; if behavior contradicts requirements or transcripts, fix to enforce “no-write” dry-run and predictable exits. [evidence: REQUIREMENTS.md :: 9. Operational Requirements — “Safe by default … Auditable”] [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “[main aee326d] … dry-run …”] [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: conflicting “no way to dryrun”]
- Validation: Run the existing payload-sync tests; add/adjust regression tests only if M1 reveals mismatch. [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “create mode … tests/test_cli_payload_sync.py”]
- Exit criteria: (a) tests pass, (b) a dry-run run produces zero db writes (prove via logs or db timestamp evidence), (c) auth/connect failures are surfaced as non-zero. [evidence: 20260209-095928-codex-20260208-103625-hashall-payload-dev-stalled-until-2-11-2300.txt :: “[main bedaafb] … fail nonzero on … auth errors”]
- Risk/rollback: Always run with dry-run first; isolate DB via temp DB path during testing. [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: notes temp DB harness used when real DB not writable]

M3 — Hardlink dedup UX parity gate
- Scope: Confirm the end-user interface for hardlink analyze/plan/execute matches REQUIREMENTS (or update docs/UX to match the actual implementation, preferring REQUIREMENTS as source of truth). [evidence: REQUIREMENTS.md :: 6.1 Same-Device Hardlink Dedup — defines required commands/behavior]
- Validation: Identify and run the hardlink workflow entrypoints referenced in transcripts (scan → link-paths → execute) and ensure a dry-run path exists; run link executor tests. [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “make scan … make link-paths … tests/test_link_executor.py”]
- Exit criteria: A reproducible command sequence (copy/paste) that produces: candidate analysis, a plan artifact, and an execution dry-run that matches safety expectations. (Observable) [evidence: REQUIREMENTS.md :: 6.1 Same-Device Hardlink Dedup — “Safe … dry-run … backups … rollback”]
- Risk/rollback: Never run destructive hardlink execution without explicit user approval; keep backups/plan artifacts. [evidence: REQUIREMENTS.md :: 6.1 Same-Device Hardlink Dedup — safety + rollback language]

M4 — Rehome “In Progress” closure gate (minimum required for Success Criteria)
- Scope: Use REQUIREMENTS §11.2 as the authoritative list; close remaining planner/applier and orchestration items needed for demote/promote flows, including safety constraints and consumer detection robustness as specified. [evidence: REQUIREMENTS.md :: 11.2 In Progress 🚧 — enumerates remaining work] [evidence: REQUIREMENTS.md :: 5.2 Demotion Workflow / 5.3 Promotion Workflow — defines safety rules]
- Validation: Run existing rehome tests; add one focused end-to-end test only if a §12 Success Criteria item cannot be demonstrated otherwise. [evidence: REQUIREMENTS.md :: 12. Success Criteria — “Functional … Operational”] [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: evidence of successful rehome run]
- Exit criteria: Demonstrate at least one demotion and one promotion scenario satisfying §5 constraints, with auditable plan/run records. (Observable) [evidence: REQUIREMENTS.md :: 5.2 / 5.3] [evidence: REQUIREMENTS.md :: 12. Success Criteria]
- Risk/rollback: Apply-phase remains gated behind dry-run/plan review and explicit approval; run in sandbox dataset if possible. [evidence: REQUIREMENTS.md :: 9. Operational Requirements — “Safe by default”]

M5 — Documentation + acceptance sign-off gate
- Scope: Update any docs referenced by REQUIREMENTS to match verified CLI and workflows; ensure the repo can “prove” §12 Success Criteria via tests or a short acceptance runbook. [evidence: REQUIREMENTS.md :: 12. Success Criteria — documentation requirement]
- Validation: Re-run full pytest; run the acceptance runbook steps and attach outputs. [evidence: 20260217-062241-codex-hashall-20260211-093155-timed-out-until-feb-18.txt :: “full suite passes …”]
- Exit criteria: (a) docs align with verified CLI, (b) acceptance checklist mapped to §12 is fully checked with concrete outputs. (Observable) [evidence: REQUIREMENTS.md :: 12. Success Criteria]
- Risk/rollback: Documentation-only changes are low risk; keep behavioral changes minimal and test-backed. [evidence: REQUIREMENTS.md :: 9. Operational Requirements]


SECTION E — Codex CLI Agent Kickoff Prompt (succinct, actionable)

````text
Objective: Finish hashall dev+test to meet REQUIREMENTS.md §12 Success Criteria by verifying and closing only evidenced gaps (no drift). Work in a git worktree. Do not assume anything; prove with repo facts.

Constraints:
- Source of truth: REQUIREMENTS.md. If transcripts conflict, prefer REQUIREMENTS; otherwise report as CONFLICT with citations.
- Use ONLY the local repo + REQUIREMENTS.md + the 8 transcript attachments. No web.
- Every factual claim you make must include concrete evidence: exact file paths, commands run, and pasted outputs (short). If you can’t prove it, say “Unknown”.
- Non-destructive by default: use dry-run modes / temp DB paths where applicable; do not execute destructive hardlinking or rehome apply without an explicit stop+ask.
- Do not change CLI UX/flags unless the plan explicitly requires it; preserve behavior.
- Do not commit unless asked. If a commit is appropriate, propose ONE commit message + files_changed and STOP.

Plan (milestones; STOP and report after each):
M1 Baseline: In repo root, capture: current version(s), `--help` for hashall/rehome entrypoints, and run `pytest -q`. Report exact outputs. Identify any REQUIREMENTS vs transcript conflicts (esp. version).
STOP → report M1 facts + conflicts.

M2 Payload-sync safety: Verify payload-sync dry-run semantics and exit codes using existing tests (e.g., payload-sync test file(s) you find). If behavior contradicts REQUIREMENTS or transcript claims, implement the minimal fix + add/adjust a regression test. Prove “no-write in dry-run” with evidence (temp DB / timestamps / logs).
STOP → report M2 results + evidence.

M3 Hardlink UX parity: Locate the hardlink workflow commands/targets (scan → link candidates → plan/execute). Compare against REQUIREMENTS §6.1. If mismatch, prefer REQUIREMENTS: either adjust implementation minimally OR adjust docs to match reality (only if REQUIREMENTS allows). Run link executor tests.
STOP → report M3 command sequence + outputs.

M4 Rehome “In Progress” minimum closure: Using REQUIREMENTS §11.2 + §5, verify planner/applier behaviors for demote/promote constraints (consumer blocking, reuse-only promotion, etc.). Run existing rehome tests; add one focused E2E test only if needed to demonstrate §12.
STOP → report M4 proof vs §12.

M5 Docs + acceptance: Update docs referenced by REQUIREMENTS to match verified CLI/workflows. Produce an acceptance checklist mapped to REQUIREMENTS §12 with concrete outputs. Re-run `pytest -q`.
STOP → final report + (optional) single commit suggestion.
````
