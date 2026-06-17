🟦 task-brief=J13-T01_canonical-path-decision-tree 🟦

id=J13-T01
role=agent
task_type=discovery
goal=Codify a single decision tree that determines the full canonical path for any RT item, covering both placement (stash vs pool) and path formula (category → directory structure); produce a draft spec doc for operator review

repo=hashall
worktree=/home/michael/dev/work/hashall/.agent/worktrees/hashall-20260530-000517-claude__j13
expected_branch=cr/hashall-20260530-000517-claude__j13
expected_head=cc4a9bbc68f3f7cfe81577105e829f58f18bfd2f

allowed_mutation=none
allowed_commands=
- Read (any file in repo)
- Bash (read-only: grep, find, python3 read-only queries against catalog.db, git log/diff/show)
- Write (one output doc only: docs/CANONICAL-PATH-TREE-DRAFT.md in the worktree)
forbidden_commands=
- Any hashall CLI with --execute, --apply, --repair flags
- git commit, git add
- Any write to src/ or tests/
required_artifacts=
- docs/CANONICAL-PATH-TREE-DRAFT.md
success_criteria=
- Decision tree covers all known item types without gaps or ambiguity
- Each branch is grounded in evidence from REQUIREMENTS.md, AGENT-MASTERY.md, or operator-confirmed policy
- Conflicts or ambiguities are explicitly called out rather than papered over
- Draft is reviewable by operator without reading any source code
stop_if=
- You find a policy conflict you cannot resolve from available docs — note it and continue; do not guess

final_output_required=true
worktree_mirror_required=false
brief_hash="none"
brief_revision_id="r1"
agent_start_timestamp="none"
brief_freeze_violation="false"

---

## Context (read before starting)

### Why this task exists

The hashall repo has two tools that each determine part of where a torrent should live:

1. `rehome/planner.py` — decides WHERE (stash vs pool) based on placement policy
2. `save_path_inference.py` — decides WHAT PATH (category → directory formula)

Both have been independently buggy. Running them separately has caused mass displacement at scale:
- rehome executor caused the original path chaos (Feb-2026 incident, 2103 stoppedDL torrents)
- save_path_inference line 223 policy inversion stripped `cross-seed/` prefix from ~2000 items

The operator has placed a migration moratorium: no mutations until a unified, validated decision tree is built and operator-reviewed. This task produces the draft spec for that tree.

### Files to read (in this order)

1. `docs/AGENT-MASTERY.md` — canonical path formula, two routing mechanisms, known damage, moratorium
2. `docs/REQUIREMENTS.md` — §4.4 canonical path spec, placement policy, storage topology
3. `docs/RT-QB-STATE-POLICY.md` — client state rules, path dispute resolution
4. `docs/RUNBOOK.md` — existing repair procedures (note any that conflict with §4.4)
5. `src/hashall/save_path_inference.py` — current (buggy) inference logic; understand what it does, not what it should do
6. `src/hashall/rehome/planner.py` — current placement decision logic
7. `docs/SPRINT.md` — active slices and known non-canonical item classes
8. `docs/OPS.md` — OP-16, OP-17, OP-18 for damage scope and open questions

### What the decision tree must resolve

For any RT torrent item, given inputs available from the catalog DB and client APIs:

**Step 1 — Classify item type:**
- ARR-imported (category = tv / movies / books / music, ATM ON)
- cross-seed injection (category = cross-seed, ATM OFF, explicit save_path)
- qbit_manage tracker-tagged (category = tracker name, ATM varies)
- unknown / uncategorized

**Step 2 — Determine seeding-root (WHERE):**
- stash (`/stash/media/torrents/seeding/` = `/data/media/torrents/seeding/` in container)
- pool-media (`/pool/media/torrents/seeding/`)
- Rules: hardlink to media library → stash preferred; `~noHL` + no library links → pool-media preferred; hitchhiker group rules

**Step 3 — Determine category subdirectory (WHAT PATH):**
- ARR: `tv/` | `movies/` | `books/` | `music/`
- cross-seed: `cross-seed/<prowlarr-tracker-name>/` (Prowlarr display name, NOT short key)
- qbit_manage: `<tracker-key>/` per tracker-registry.yml
- unknown: flag for human review

**Step 4 — Assemble full canonical path:**
`<seeding-root>/<category-subdir>/<item-payload-name>/`

**Step 5 — Diff vs actual:**
Compare computed target against RT's reported save_path (translated from container to host path). Classify mismatch type: wrong root only, wrong category subdir, both, or item-name drift.

### Known complications to address in the draft

1. **cross-seed tracker name resolution**: qB tracker tag is first choice; traktor registry is fallback; Prowlarr display name is what cross-seed actually used on disk. These may differ — the draft must specify which wins for directory naming.

2. **`~noHL` is advisory**: a tag applied at a point in time; a new ARR import can create a library hardlink after the tag was applied. The tree must specify: re-verify at plan time, not trust the tag alone.

3. **Inode-sharing groups (hitchhikers)**: if torrent A's files share inodes with torrent B's files on the same filesystem, they must move together. The tree must flag when a placement decision is group-scoped, not item-scoped.

4. **`cross-seed-link/` legacy paths**: `normalize_cross_seed_refactor_path` already handles these; the tree should note they are pre-normalized before classification.

5. **`_rehome-unique/<hash>/` staging dirs**: Class 4 items; not canonical; tree should classify these as "needs repair to canonical" regardless of other attributes.

6. **`cross-seed/<hash>/` items**: Class 1; tracker name not resolved at injection time; tree should specify resolution procedure (traktor registry lookup by announce URL).

7. **Container vs host path translation**: RT and qB report `/data/media/...`; host path is `/stash/media/...`. The tree must be explicit about which coordinate system is used at each step.

### Output format

Write `docs/CANONICAL-PATH-TREE-DRAFT.md` with:

1. **Decision tree** — a clear flowchart in text/table form, one branch per item type, showing inputs → outputs at each step
2. **Input data sources** — what fields from catalog DB / RT API / qB API feed each decision
3. **Known conflicts** — any policy gaps, ambiguities, or contradictions found during research; do not resolve them, just document clearly for operator
4. **Scope estimate** — from catalog DB, how many items fall into each branch of the tree
5. **Open questions** — anything that requires operator decision before the tree can be finalized

Keep the draft operator-readable: no raw code, no file-line citations in the main body (put those in an appendix if needed).

🟦 task-brief=J13-T01_canonical-path-decision-tree 🟦
