# Requirements Traceability Matrix (RTM)
**Project:** hashall / rehome
**Version:** 1.0
**Date:** 2026-02-06
**Scope:** `docs/REQUIREMENTS.md`

## Legend
- **Method:** T = Test, A = Analysis, I = Inspection
- **Status:** PASS / FAIL / NOT RUN

## Matrix
| ID | Requirement (Ref) | Method | Evidence | Status |
|---|---|---|---|---|
| REQ-2.2-1 | Bind-mount path mapping canonicalized (2.2) | T | `out/te/phase1/logs/pytest_phase1_scan.txt` | PASS |
| REQ-4.2-1 | Payload hash deterministic + computed from file tuples (4.2) | T | `out/te/phase1/logs/pytest_phase1_payload.txt` | PASS |
| REQ-7.1-1 | Unified catalog per-device tables supported (7.1) | T | `out/te/phase1/logs/pytest_phase1_scan.txt` | PASS |
| REQ-7.2-1 | Incremental scan faster than initial (7.2) | T | `out/te/phase1/logs/scan_incremental_stash.txt` | PASS |
| REQ-7.2-2 | Scan records canonical paths (7.2) | A | `out/te/phase1/logs/scan_initial_stash.txt` | PASS |
| REQ-7.3-1 | Export JSON available (7.3) | I | Not run in Phase 0-1 | NOT RUN |
| REQ-4.3-1 | External consumer detection blocks demotion (4.3) | T | `out/te/phase2/logs/pytest_phase2_external_consumers.txt` | PASS |
| REQ-5.1-1 | Demotion decision REUSE/MOVE/BLOCK (5.1) | T | `out/te/phase3/logs/pytest_phase3_planning.txt` | PASS |
| REQ-5.1-2 | REUSE flow builds views + relocates siblings (5.1) | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| REQ-5.1-3 | MOVE flow verifies + relocates siblings (5.1) | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| REQ-5.2-1 | Promotion reuse-only (5.2) | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| REQ-5.3-1 | Payload-group rehome (5.3) | T | `out/te/phase3/logs/pytest_phase3_planning.txt` | PASS |
| REQ-6.1-1 | Same-device dedupe analysis/plan/execute (6.1) | T | Phase 5 | NOT RUN |
| REQ-6.2-1 | Cross-device duplicate detection (6.2) | T | Phase 5 | NOT RUN |
| REQ-6.3-1 | Sibling torrent views (6.3) | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| REQ-9.1-1 | Safe defaults (dry-run, fail-fast) (9.x) | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| REQ-9.2-1 | Audit trail persisted (9.x) | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |

## Success Criteria Mapping (Section 12)
| ID | Success Criterion | Method | Evidence | Status |
|---|---|---|---|---|
| SC-F-1 | Media-linked data stays on `/stash` | T | `out/te/phase2/logs/pytest_phase2_external_consumers.txt` | PASS |
| SC-F-2 | Seed-only data can live on `/pool` | T | `out/te/phase3/logs/pytest_phase3_planning.txt` | PASS |
| SC-F-3 | REUSE prevents duplication | T | `out/te/phase3/logs/pytest_phase3_planning.txt` | PASS |
| SC-F-4 | Sibling torrents as hardlink views | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| SC-F-5 | Incremental scans 10-100x faster | T | `out/te/phase1/logs/scan_incremental_stash.txt` | NOT RUN |
| SC-F-6 | Dedup saves measurable space | T | Phase 5 | NOT RUN |
| SC-O-1 | Safe by default | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| SC-O-2 | Audit trail understandable | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| SC-O-3 | Recoverable from failure | T | `out/te/phase4/logs/pytest_phase4_execution.txt` | PASS |
| SC-U-1 | CLI workflows clear and repeatable | I | Phase 6 | NOT RUN |
| SC-U-2 | Documentation accurate/complete | I | Phase 6 | NOT RUN |

## Notes
- Phase 1 scan timings are from a micro dataset and do not validate the 10–100x performance claim; full-scale benchmark pending.
