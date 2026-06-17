🟦 task-brief=J13-T02_finalize-canonical-path-spec 🟦

id=J13-T02
role=agent
task_type=implementation
goal=Produce a clean finalized canonical path spec (CANONICAL-PATH-SPEC.md) from the operator-reviewed draft, with all decisions baked in and no open questions remaining; this becomes the authoritative reference for the implementation agent

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j13
expected_branch=cr/hashall-20260530-000517-claude__j13
expected_head=cc4a9bbc68f3f7cfe81577105e829f58f18bfd2f

allowed_mutation=files-only
allowed_commands=
- Read (any file in worktree or repo)
- Write (output doc only: docs/CANONICAL-PATH-SPEC.md in the worktree)
- Bash (read-only queries only)
forbidden_commands=
- git commit, git add
- Any hashall CLI with --execute, --apply, --repair flags
- Any write to src/ or tests/
required_artifacts=
- docs/CANONICAL-PATH-SPEC.md
success_criteria=
- All operator decisions from the draft's decision table are incorporated as facts, not open questions
- Step 5 shows the full two-client diff table (RT and qB independently diffed against canonical)
- No "TBD", "open question", or "operator must decide" language remains except Q1 (migration authorization — explicitly marked HOLD)
- Doc is self-contained: an implementation agent can build the unified tool from this spec alone without reading any other doc
- Scope estimates from T01 are preserved
stop_if=
- You find a genuine policy gap not covered by the operator decisions — note it and continue writing; mark it UNRESOLVED

final_output_required=true
worktree_mirror_required=false
brief_hash="none"
brief_revision_id="r1"
agent_start_timestamp="none"
brief_freeze_violation="false"

---

## Source material

**Primary:** `docs/CANONICAL-PATH-TREE-DRAFT.md` in this worktree — the annotated draft with all operator decisions recorded in the decision table at the top.

**Supporting:** `docs/AGENT-MASTERY.md` in the CR worktree (`hashall-20260530-000517-claude`) — contains the finalized versions of all policy sections updated during T01 operator review.

## All operator decisions (incorporate as facts)

| Topic | Decision |
|---|---|
| Q1 — 2393-item repair authorization | **HOLD — TBD.** Big picture strategy must be decided first. Mark as HOLD in spec, do not list as an open question. |
| Q2 — tracker registry extension | No extension needed. `tracker-registry.yml` already tracks `prowlarr_display_name`, `tracker_key`, AND `tracker_url_pattern`. Use as one-stop source. |
| Q3 — tracker name resolution priority | qB category + tags are sufficient. RT announce URL not needed for path derivation. For Class 1 (`cross-seed/<hash>/`) items: use qB tags to resolve tracker. |
| Conflict 1 — Slice 12b vs §4.4 | §4.4 wins. `cross-seed/<tracker>/` IS canonical. 2393 items need prefix RESTORATION, not removal. Slice 12b superseded. |
| Conflict 2 — RT authority vs qB metadata | qB metadata (category + tags) → input to compute canonical target. RT save_path AND qB save_path → each diffed independently against canonical. Neither client assumed correct. Decision tree is arbiter. "RT wins" shorthand only valid after tree confirms RT is already at canonical. |
| Conflict 3 — ~noHL dry-run trust level | **Two scan modes:** default simulates using tag + catalog data (fast, may produce false positives). `--full-scan` flag triggers live filesystem hardlink check, saves results to disk for offline review and reuse. |
| Conflict 4 — ARR pre/post import | Use current save_path as evidence of which state the item is in. Post-import category is the final form. |
| Q4 — single-file formula | Torrent internal structure is authoritative. Bare-file torrent (no folder in torrent) → `<root>/<cat>/<filename>`, NO subdirectory. Torrent with internal folder → `<root>/<cat>/<folder>/<filename>`. Spurious folder around bare-file = RT artifact/bug, classify NEEDS_REPAIR. |
| Q5 — hitchhiker group check scope | Group check belongs in the planner/execution step, not in the decision tree itself. Tree computes per-item canonical target; execution tool checks full inode-sharing group before authorizing any move. |
| Q6 — Class 1 tracker resolution | Use qB category + tags. qB is sufficient. |
| Q7 — ~noHL + cross-seed placement | ~noHL is advisory only, never authoritative. Can be stale. Applies to the qB item only, not sibling payloads. Independent filesystem verification of ALL sibling payloads required before any pool rehome is authorized. qB and RT may have different save_paths for the same item — verify both. |
| Path arbiter rule | Decision tree is the arbiter. Run tree using qB metadata → canonical target. Diff RT save_path against canonical independently. Diff qB save_path against canonical independently. See five-row action table in draft Step 5. |
| Single-file torrent | See Q4 above. |
| Scan modes | See Conflict 3 above. |

## Output format for CANONICAL-PATH-SPEC.md

Structure the spec as follows. Do not include any draft annotation tables or "operator decisions" header — bake everything into the body as policy statements.

```
# Canonical Path Specification
Version: 1.0.0-draft
Status: APPROVED FOR IMPLEMENTATION (except where marked HOLD)

## 1. Overview
## 2. Input Data Sources
## 3. Decision Tree
   ### Step 0: Pre-screen (staging dirs, legacy prefixes)
   ### Step 1: Classify Item Type
   ### Step 2: Determine Seeding Root (WHERE)
   ### Step 3: Determine Category Subdirectory (WHAT PATH)
   ### Step 4: Assemble Full Canonical Path
   ### Step 5: Diff vs Actual (both clients independently)
## 4. Action Table (RT × qB combinations)
## 5. Scan Modes
## 6. Implementation Notes (hitchhiker groups, single-file rule, ~noHL verification)
## 7. Scope Estimates
## 8. Known Damage Requiring Repair (with HOLD items clearly marked)
## 9. Out of Scope (what this spec does NOT decide)
```

Keep it implementation-ready: precise enough that an agent can write the tool from this doc alone. Remove any language that hedges, investigates, or defers — that was T01's job. This doc states policy.

🟦 task-brief=J13-T02_finalize-canonical-path-spec 🟦
