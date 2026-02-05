# Gap Analysis Plan - Requirements vs Codebase

**Version:** 1.0
**Date:** 2026-02-02
**Purpose:** Identify gaps between REQUIREMENTS.md and actual implementation to plan next development cycle

---

## Executive Summary

This document provides a systematic approach to conduct a gap analysis between the requirements specification (`docs/REQUIREMENTS.md`) and the current codebase implementation. The analysis will produce a prioritized development roadmap for the next development cycle.

---

## 1. Analysis Methodology

### 1.1 Analysis Approach

**Three-Phase Process:**

1. **Discovery Phase** - Inventory what exists
   - Map requirements sections to codebase modules
   - Document implemented features
   - Identify CLI commands and their capabilities

2. **Gap Identification Phase** - Find what's missing
   - Compare requirements against implementation
   - Classify gaps by severity and impact
   - Document workarounds or partial implementations

3. **Prioritization Phase** - Plan what to build next
   - Rank gaps by user impact
   - Consider dependencies and prerequisites
   - Estimate effort and complexity
   - Generate development roadmap

### 1.2 Gap Classification

**Categories:**

- **✅ Complete** - Fully implemented and tested
- **🟢 Mostly Complete** - Core functionality exists, minor refinements needed
- **🟡 Partial** - Some implementation exists, significant work remains
- **🔴 Missing** - Not implemented, required for core functionality
- **⚪ Not Started** - Planned but no code exists
- **🔵 Out of Scope** - Intentionally deferred or not needed

**Severity Levels:**

- **Critical** - Blocks core workflows, must implement
- **High** - Important for usability, should implement soon
- **Medium** - Nice to have, can be deferred
- **Low** - Future enhancement, not urgent

---

## 2. Requirements Mapping Matrix

### 2.1 Core Functionality Mapping

| Requirement Section | Primary Module(s) | CLI Command(s) | Status Estimate |
|---------------------|-------------------|----------------|-----------------|
| **Storage Architecture** | | | |
| - Bind mount handling | `fs_utils.py` | `scan` | 🟢 |
| - Canonical path resolution | `fs_utils.py` | `scan` | 🟢 |
| - Device ID detection | `device.py`, `model.py` | `devices list/show` | ✅ |
| - Filesystem UUID tracking | `device.py` | `devices list/show` | ✅ |
| **Catalog System** | | | |
| - Unified catalog model | `model.py` | `scan`, `stats` | ✅ |
| - Per-device tables | `model.py` | `scan` | ✅ |
| - Incremental scanning | `scan.py` | `scan` | ✅ |
| - Parallel scanning | `scan.py` | `scan --parallel` | ✅ |
| - SHA1 file hashing | `scan.py` | `scan` | ✅ |
| - SHA256 migration | `scan.py` | `scan` | 🔴 |
| - Payload tracking | `payload.py` | `payload sync/show/siblings` | ✅ |
| - qBittorrent sync | `qbittorrent.py`, `payload.py` | `payload sync` | ✅ |
| **Deduplication** | | | |
| - Same-device duplicate detection | Unknown | `dupes` | 🟡 |
| - Link analysis (per-device) | Unknown | ❌ `link analyze` | 🔴 |
| - Link planning | `scripts/link_plan.py` | ❌ `link plan` | 🔴 |
| - Link execution | Unknown | ❌ `link execute` | 🔴 |
| - Cross-device duplicate detection | Unknown | `dupes --cross-device` | 🟡 |
| **Rehoming** | | | |
| - Demotion planning | `rehome/planner.py` | `rehome plan --demote` | ✅ |
| - Demotion execution | `rehome/executor.py` | `rehome apply` | ✅ |
| - Promotion planning | `rehome/planner.py` | `rehome plan --promote` | ✅ |
| - Promotion execution | `rehome/executor.py` | `rehome apply` | ✅ |
| - External consumer detection | `rehome/planner.py` | (automatic in plan) | ✅ |
| - Batch by payload-hash | `rehome/planner.py` | `rehome plan --payload-hash` | ✅ |
| - Batch by tag | `rehome/planner.py` | `rehome plan --tag` | ✅ |
| - qBittorrent API integration | `qbittorrent.py`, `rehome/executor.py` | (automatic in apply) | ✅ |
| **Operational** | | | |
| - Dry-run support | `rehome/executor.py` | `rehome apply --dryrun` | ✅ |
| - Verification checks | `rehome/executor.py` | (automatic in apply) | ✅ |
| - Audit trail | `model.py` | `stats` | 🟢 |
| - Progress indicators | `scan.py`, others | (automatic with tqdm) | 🟢 |

### 2.2 Quick Assessment Summary

**✅ Complete (14 items):**
- Device management (UUID tracking, aliases)
- Unified catalog with per-device tables
- Incremental and parallel scanning
- Payload tracking and qBittorrent sync
- Rehoming (demotion + promotion, all modes)
- External consumer detection
- Basic statistics

**🟢 Mostly Complete (3 items):**
- Bind mount/canonical path handling (works but may need edge case testing)
- Audit trail (exists but could be enhanced)
- Progress indicators (present but could be standardized)

**🟡 Partial (2 items):**
- Duplicate detection (some implementation in `dupes` command, unclear scope)
- Cross-device duplicate detection (command exists, functionality unclear)

**🔴 Missing (3 critical items):**
- SHA256 migration (SHA1 → SHA256 conversion tool)
- Link analysis command (identify deduplication opportunities)
- Link plan/execute commands (create and apply deduplication plans)

---

## 3. Detailed Gap Analysis Tasks

### 3.1 Phase 1: Discovery (Inventory Existing Implementation)

**Task 1.1: CLI Command Audit**
```bash
# Generate comprehensive CLI command tree
python3 -m hashall --help > cli-audit-hashall.txt
python3 -m hashall devices --help >> cli-audit-hashall.txt
python3 -m hashall payload --help >> cli-audit-hashall.txt
python3 -c "import rehome.cli; rehome.cli.cli.main(['--help'])" > cli-audit-rehome.txt

# Document all commands, options, and behaviors
```

**Deliverable:** `CLI-COMMAND-INVENTORY.md` listing all commands with:
- Command name and path
- Options and arguments
- Brief description
- Implementation status (works, buggy, incomplete)

**Task 1.2: Module Capability Mapping**
```bash
# For each Python module in src/hashall/ and src/rehome/:
# - Read module docstring
# - List public functions/classes
# - Map to requirements sections
# - Note test coverage
```

**Deliverable:** `MODULE-CAPABILITY-MAP.md` with:
- Module name → Requirements section mapping
- Public API surface
- Test coverage percentage (from pytest --cov)
- Known issues or TODOs in code

**Task 1.3: Database Schema Validation**
```bash
# Compare actual schema against docs/architecture/schema.md
sqlite3 ~/.hashall/catalog.db ".schema" > schema-actual.sql
diff docs/architecture/schema.md schema-actual.sql

# Check for undocumented tables or columns
```

**Deliverable:** Schema discrepancy report

**Task 1.4: Test Coverage Analysis**
```bash
# Run test suite with coverage
pytest --cov=src/hashall --cov=src/rehome --cov-report=html tests/

# Identify untested requirements
```

**Deliverable:** `TEST-COVERAGE-REPORT.md` with:
- Overall coverage percentage
- Modules with <80% coverage
- Critical paths without tests
- Integration test gaps

**Estimated Effort:** 4-6 hours (can be automated with CLI agent)

---

### 3.2 Phase 2: Gap Identification (Compare Requirements vs Implementation)

**Task 2.1: Feature-by-Feature Comparison**

For each requirement in REQUIREMENTS.md Sections 4-9, document:

1. **Requirement ID** (e.g., REQ-DEDUPE-001)
2. **Description** (from requirements)
3. **Implementation Status**:
   - ✅ Complete
   - 🟢 Mostly Complete
   - 🟡 Partial
   - 🔴 Missing
   - ⚪ Not Started
4. **Implementation Location** (module/file)
5. **Test Coverage** (Y/N/Partial)
6. **Gap Description** (what's missing or broken)
7. **Impact** (Critical/High/Medium/Low)
8. **Workaround** (if any exists)

**Deliverable:** `FEATURE-GAP-MATRIX.csv` and `FEATURE-GAP-REPORT.md`

**Example Entry:**
```markdown
### REQ-DEDUPE-002: Link Analysis Command

**Requirement:**
> Users must be able to analyze deduplication opportunities with:
> `hashall link analyze --device /stash`
> Output should show number of opportunities and potential space savings.

**Status:** 🔴 Missing

**Current State:**
- `dupes` command exists but functionality differs from requirements
- No `link analyze` command in CLI
- Some logic in `scripts/link_plan.py` (not integrated)

**Gap:**
- No CLI command implemented
- No per-device opportunity analysis
- No space savings calculation
- Output format not specified

**Impact:** High - Users cannot identify deduplication opportunities without this

**Workaround:** Manual SQL queries against catalog.db (not user-friendly)

**Dependencies:** None (can implement independently)

**Estimated Effort:** Medium (2-3 days)
- Design output format
- Implement analysis logic
- Add CLI command
- Write tests
```

**Task 2.2: SHA256 Migration Analysis**

**Specific focus on SHA1 → SHA256 transition:**

1. **Current State:**
   - Which files use SHA1? (`scan.py`, `model.py`, others?)
   - Are there SHA1 assumptions in queries?
   - Does payload hash use SHA1 or SHA256?

2. **Migration Requirements:**
   - Backward compatibility (read old SHA1 entries)
   - Migration tool (rehash files or convert database)
   - Dual-hash period (support both during transition)
   - Cutover strategy (when to deprecate SHA1)

3. **Impact Analysis:**
   - Existing catalogs (need migration)
   - Existing payloads (need recomputation?)
   - External tools (jdupes, cross-seed)

**Deliverable:** `SHA256-MIGRATION-PLAN.md` with:
- Current SHA1 usage inventory
- Migration strategy options
- Recommended approach
- Implementation tasks
- Rollback plan

**Task 2.3: Link Deduplication Gap Analysis**

**Focus:** Requirements Section 6 (Deduplication)

1. **Existing Code Audit:**
   - What does `dupes` command do?
   - What's in `scripts/link_plan.py`?
   - Is there a link execution engine anywhere?

2. **Missing Components:**
   - `link analyze` command
   - `link plan` command
   - `link execute` command
   - `link show-plan` command
   - Link plans table (does it exist? is it used?)

3. **Integration Needs:**
   - How should this integrate with existing catalog?
   - Safety checks needed (verify same device, backup before link)
   - Rollback mechanism

**Deliverable:** `LINK-DEDUPLICATION-GAP.md` with:
- Existing vs required commands matrix
- Missing functionality list
- Integration requirements
- Safety/testing needs

**Estimated Effort:** 6-8 hours (can be accelerated with CLI agent doing code searches)

---

### 3.3 Phase 3: Prioritization (Plan Development Roadmap)

**Task 3.1: Impact vs Effort Matrix**

Create 2x2 matrix for each gap:

```
          Low Effort              High Effort
        ┌─────────────────────┬─────────────────────┐
High    │ QUICK WINS          │ MAJOR PROJECTS      │
Impact  │ (Do First)          │ (Plan Carefully)    │
        ├─────────────────────┼─────────────────────┤
Low     │ NICE TO HAVES       │ AVOID/DEFER         │
Impact  │ (Fill Time)         │ (Low ROI)           │
        └─────────────────────┴─────────────────────┘
```

**Deliverable:** `PRIORITIZATION-MATRIX.md` with gaps plotted on matrix

**Task 3.2: Dependency Analysis**

For each gap, identify:
- **Blocks:** What gaps must be resolved first?
- **Blocked by:** What gaps does this block?
- **Related:** What gaps should be done together?

**Example:**
```
REQ-DEDUPE-003: Link Plan Command
  Blocked by: REQ-DEDUPE-002 (Link Analyze) - need to identify duplicates first
  Blocks: REQ-DEDUPE-004 (Link Execute) - execution needs a plan
  Related: REQ-DEDUPE-005 (Show Plan) - should implement together
```

**Deliverable:** `DEPENDENCY-GRAPH.md` (or visual diagram)

**Task 3.3: Development Roadmap Generation**

Based on impact, effort, and dependencies, create a phased roadmap:

**Sprint 1 (Critical Gaps - 2 weeks):**
- Items from "Quick Wins" quadrant
- Critical blockers for core workflows

**Sprint 2 (High-Value Features - 2 weeks):**
- Items from "Major Projects" quadrant
- High-impact items with manageable effort

**Sprint 3 (Refinements - 1 week):**
- Items from "Nice to Haves" quadrant
- Polish and testing

**Deliverable:** `DEVELOPMENT-ROADMAP.md` with:
- Sprint breakdowns
- Task descriptions
- Estimated effort (story points or hours)
- Acceptance criteria
- Risk mitigation strategies

**Estimated Effort:** 3-4 hours

---

## 4. Execution Plan

### 4.1 Recommended Approach

**Option A: Manual Analysis** (Human-led, 2-3 days)
- User performs discovery and gap identification
- Detailed but time-consuming
- High accuracy, deep understanding

**Option B: CLI Agent-Assisted** (Agent-led, 6-8 hours)
- Use Task tool with Explore agent for discovery
- Agent generates initial gap reports
- User reviews and refines
- Faster but requires validation

**Option C: Hybrid** (Recommended, 1 day)
- Agent performs automated discovery (Tasks 1.1-1.4)
- Human performs gap identification (Tasks 2.1-2.3) with agent assistance
- Collaborate on prioritization (Task 3.1-3.3)
- Best of both worlds: speed + accuracy

### 4.2 Agent Tasking Scripts

**For Option B/C, the following agent prompts can be used:**

**Agent Task 1: CLI Command Inventory**
```
Use the Explore agent to:
1. Find all @cli.command and @cli.group decorators in src/hashall/cli.py and src/rehome/cli.py
2. For each command, document: name, options, arguments, docstring
3. Run each command with --help to capture help text
4. Generate CLI-COMMAND-INVENTORY.md with complete command tree
```

**Agent Task 2: Module Capability Mapping**
```
Use the Explore agent to:
1. List all Python modules in src/hashall/ and src/rehome/
2. For each module, extract:
   - Module docstring
   - Public functions (not starting with _)
   - Public classes
   - Main purpose
3. Map each module to REQUIREMENTS.md sections
4. Generate MODULE-CAPABILITY-MAP.md
```

**Agent Task 3: Feature Gap Analysis**
```
For each requirement in REQUIREMENTS.md Sections 4-9:
1. Search codebase for related implementations
2. Check if CLI command exists
3. Determine implementation status (complete/partial/missing)
4. Document gaps
5. Generate FEATURE-GAP-REPORT.md
```

**Agent Task 4: SHA256 Migration Analysis**
```
Search codebase for:
1. All references to "sha1", "SHA1", "hashlib.sha1"
2. All references to "sha256", "SHA256", "hashlib.sha256"
3. Database schema SHA1 columns
4. Payload hash computation logic
Generate SHA256-MIGRATION-PLAN.md with findings
```

### 4.3 Deliverables Checklist

After gap analysis is complete, you should have:

- [ ] `CLI-COMMAND-INVENTORY.md` - Complete command reference
- [ ] `MODULE-CAPABILITY-MAP.md` - Module → Requirements mapping
- [ ] `FEATURE-GAP-MATRIX.csv` - Structured gap data
- [ ] `FEATURE-GAP-REPORT.md` - Narrative gap analysis
- [ ] `SHA256-MIGRATION-PLAN.md` - Migration strategy
- [ ] `LINK-DEDUPLICATION-GAP.md` - Link feature analysis
- [ ] `TEST-COVERAGE-REPORT.md` - Testing gaps
- [ ] `PRIORITIZATION-MATRIX.md` - Impact vs effort
- [ ] `DEPENDENCY-GRAPH.md` - Task dependencies
- [ ] `DEVELOPMENT-ROADMAP.md` - Next cycle plan

---

## 5. Success Criteria

The gap analysis is successful if:

1. **Complete Inventory**
   - All CLI commands documented
   - All modules mapped to requirements
   - No unknown/undocumented code

2. **Clear Gap Classification**
   - Every requirement has a status (complete/partial/missing)
   - Gaps are categorized by severity
   - Impact on users is clear

3. **Actionable Roadmap**
   - Next sprint tasks are well-defined
   - Dependencies are clear
   - Effort estimates are realistic
   - Acceptance criteria are specific

4. **Stakeholder Alignment**
   - User understands what's built vs what's needed
   - Priorities match user's needs
   - Roadmap is agreed upon

---

## 6. Next Steps After Gap Analysis

Once gap analysis is complete:

1. **Review with User**
   - Present findings
   - Validate priorities
   - Adjust roadmap based on feedback

2. **Create Development Plan**
   - Break roadmap into user stories
   - Set up task tracking (could use TaskCreate for this)
   - Assign to CLI agents or human developers

3. **Begin Implementation**
   - Start with Sprint 1 critical gaps
   - Test incrementally
   - Update REQUIREMENTS.md as implementation progresses

4. **Iterate**
   - Run mini gap analyses between sprints
   - Adjust priorities as new requirements emerge
   - Keep REQUIREMENTS.md as living document

---

## 7. Appendix: Quick-Start Commands

### For Immediate Discovery (No Agent)

```bash
# 1. List all CLI commands
python3 -m hashall --help
python3 -m hashall devices --help
python3 -m hashall payload --help
python3 -m rehome --help

# 2. Check what's actually in the database
sqlite3 ~/.hashall/catalog.db ".tables"
sqlite3 ~/.hashall/catalog.db ".schema"

# 3. Check module structure
find src/hashall -name "*.py" -type f | xargs grep -l "^def " | sort
find src/rehome -name "*.py" -type f | xargs grep -l "^def " | sort

# 4. Check test coverage
pytest --cov=src --cov-report=term-missing tests/ 2>/dev/null | grep TOTAL

# 5. Search for SHA1 vs SHA256
grep -r "sha1" src/ --include="*.py" | wc -l
grep -r "sha256" src/ --include="*.py" | wc -l

# 6. Check for link-related code
grep -r "link.*plan\|link.*execute\|link.*analyze" src/ --include="*.py"
```

### For Agent-Assisted Discovery

```bash
# Start a Task tool with Explore agent:
# Prompt: "Explore the hashall codebase and generate a complete inventory of:
#         1. All CLI commands and their implementations
#         2. All Python modules and their purposes
#         3. Database schema and tables
#         4. Test coverage for major features
#         Produce CLI-COMMAND-INVENTORY.md and MODULE-CAPABILITY-MAP.md"
```

---

## Document History

**Version 1.0 (2026-02-02):**
- Initial gap analysis plan
- Three-phase methodology
- Agent-assisted execution options
- Comprehensive deliverables checklist
