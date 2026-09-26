
# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
# Script: src/hashall/__init__.py
# Version: 0.8.80
# Last-updated: 2026-09-26T00:00:00-04:00
# v0.8.78: feat: Phase 3 single periodic add-only RT->qB reconciler (PR #10, Issue #6).
# v0.8.79: fix: reconciler safety brake stays active through verification polling,
#   and live RT fault confirmation no longer normalizes unrecognized XML-RPC
#   faults into the stale-hash skip path (PR #10 review findings).
# v0.8.80: fix: reconciler already_present path classifies a live stoppedDL/pausedDL
#   qB mirror as already_present_unhealthy (fail/alert, never auto-recheck) instead
#   of silently reporting it as a healthy already_present success (PR #10 review
#   finding, issuecomment-5849848962).
__version__ = "0.8.80"
