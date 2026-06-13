---
id: J03-T07
job: 3-pending-repairs
slug: state-policy-doc-audit
task_type: discovery
status: staged
brief_revision_id: 1
created_by: lead
created_at: 2026-06-12
agent_start_timestamp: none
brief_freeze_violation: "false"
---

# J03-T07 — RT/qB State Policy Doc Audit

## Context

The Lead has written a new authoritative policy document:
  docs/RT-QB-STATE-POLICY.md

This document consolidates RT/qB acceptable state rules, decision trees for
violations, cross-seed handling, and tracker issue protocol — derived from
operator Q&A on 2026-06-12.

This task is a pure document audit: read every doc in the repo that touches
RT/qB state, client health, acceptable states, or repair procedures.
Find gaps and contradictions between those docs and the new policy.
Report findings to Lead for discussion. No edits.

## Documents to scan (minimum)

Primary policy sources:
  docs/RT-QB-STATE-POLICY.md    ← new authoritative doc (just written)
  docs/USER-NOTES.md            ← original operator target state definition
  docs/REQUIREMENTS.md          ← §8.4 qB integration, §4.1 residency rules
  docs/RUNBOOK.md               ← operational procedures
  docs/SPRINT.md                ← current sprint state + Slice 13 trk_warn history
  docs/BACKLOG.md               ← known gaps
  docs/RECOVERY.md              ← recovery procedures
  docs/ARCHITECTURE.md          ← system architecture
  docs/operations/RUN-STATE.md  ← live evidence baseline

Secondary (check if they contain state guidance):
  docs/ops-log.md
  docs/REFRESH_GUIDE.md
  Any file matching docs/**/*.md

Code that encodes state assumptions (scan for hardcoded state lists):
  src/hashall/cli.py             ← BROKEN_EXPECTED_STATES and similar
  src/hashall/qb_repair_payload_group.py
  src/hashall/client_drift.py
  src/rehome/executor.py
  src/rehome/auto.py

## Bootstrap Context

```
chat_id=hashall-20260530-000517-claude
repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03
branch=cr/hashall-20260530-000517-claude__j03
head=c92d2b9530218f38db01cb91f5f649757188b4be
goal=Pending repairs: resolve drift, recheck missingFiles, clean staging paths
```

Verify before starting:
- `git branch --show-current` → `cr/hashall-20260530-000517-claude__j03`
- `git status --short` → clean

## Brief

```
🟦 task-brief=J03-T07_state-policy-doc-audit 🟦

id=J03-T07
role=agent
task_type=discovery
goal=Scan all repo documents and relevant source files for RT/qB state guidance.
     Find every gap and contradiction between those sources and the new
     docs/RT-QB-STATE-POLICY.md. Report findings for Lead discussion.

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03

expected_branch=cr/hashall-20260530-000517-claude__j03
expected_head=c92d2b9530218f38db01cb91f5f649757188b4be

allowed_mutation=none

allowed_commands=
- cat / Read any file under docs/ or src/
- grep -rn "<pattern>" docs/ src/
- find docs/ -name "*.md"
- git branch --show-current
- git rev-parse HEAD
- git status --short
- tmux send-keys -t %14 "<summary>"
- tmux send-keys -t %14 "" Enter

forbidden_commands=
- Any file edit or write
- git add / git commit
- Any --execute or --apply flag
- hashall / rehome commands

required_artifacts=
Report findings in these categories:

CATEGORY 1 — CONTRADICTIONS
  Statements in existing docs that directly conflict with RT-QB-STATE-POLICY.md.
  For each: document + line, the conflicting text, what policy says instead.

CATEGORY 2 — GAPS IN EXISTING DOCS
  Topics covered in RT-QB-STATE-POLICY.md that are absent or incomplete
  in the other docs. For each: what's missing, which doc should have it.

CATEGORY 3 — GAPS IN RT-QB-STATE-POLICY.md
  Topics the other docs address that are not covered in RT-QB-STATE-POLICY.md.
  For each: what's missing from the policy doc, source location.

CATEGORY 4 — CODE/DOC MISMATCHES
  Places where source code encodes state assumptions that differ from policy.
  For each: file + line, what the code does, what policy requires.

CATEGORY 5 — STALE DATA
  Documents with evidence baselines or repair queues that are clearly outdated.
  For each: document, what's stale, estimated age.

success_criteria=
- All listed documents scanned
- All 5 categories reported (empty category is OK — say "none found")
- Every finding includes: document, location (line or section), specific text, assessment

stop_if=
- Cannot read a key document (permission error)
- File not found for a listed document (report as missing, continue)

final_output_required=true
worktree_mirror_required=false
agent_start_timestamp=none
brief_freeze_violation=false

🟦 task-brief=J03-T07_state-policy-doc-audit 🟦
```

## Expected Agent Report Format

```
🟪 task-log=J03-T07_state-policy-doc-audit 🟪

status="done|blocked"
task_id="J03-T07"
task_type="discovery"
branch="cr/hashall-20260530-000517-claude__j03"
head="c92d2b9530218f38db01cb91f5f649757188b4be"
changed="none"
mutations="none"
validation="<one-line summary>"
artifacts="findings below"
worktree_mirror_status="not_configured"
worktree_mirror_path="none"
worktree_mirror_head="none"
worktree_mirror_delete_used="false"
issues="none|<describe any>"
next="future TBD by lead after current task log"

docs_scanned=
findings_contradictions=
findings_gaps_in_existing=
findings_gaps_in_policy=
findings_code_mismatches=
findings_stale=

=== CATEGORY 1: CONTRADICTIONS ===
<findings or "none found">

=== CATEGORY 2: GAPS IN EXISTING DOCS ===
<findings or "none found">

=== CATEGORY 3: GAPS IN RT-QB-STATE-POLICY.md ===
<findings or "none found">

=== CATEGORY 4: CODE/DOC MISMATCHES ===
<findings or "none found">

=== CATEGORY 5: STALE DATA ===
<findings or "none found">

🟪 task-log=J03-T07_state-policy-doc-audit 🟪
```

## After completing this task

1. Write TASK-LOG.md to:
   /home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j03/jobs/3-pending-repairs/tasks/J03-T07--state-policy-doc-audit/TASK-LOG.md

2. Mirror to GDrive:
   /mnt/gdrive/chatrap/repos/hashall/jobs/3-pending-repairs/tasks/J03-T07--state-policy-doc-audit/TASK-LOG.md

3. Notify Lead (two sends):
   tmux send-keys -t %14 "🟪 J03-T07 done | contradictions=<N> gaps_existing=<N> gaps_policy=<N> code_mismatches=<N> stale=<N>"
   tmux send-keys -t %14 "" Enter
