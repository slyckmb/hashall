# Known Pre-Existing Test Failures

**Last verified:** 2026-03-19
**Baseline:** 636 pass / 13 fail / 2 skip (full suite on this host)

These 13 failures pre-date the 2026-03-18/19 audit session and are unrelated to
any recent code changes. Each failure has a known root cause and a proposed fix.

---

## Group 1 — `test_scan_integration.py` (7 failures)

### Failing tests
```
test_first_scan_creates_catalog
test_rescan_with_deletions
test_rescan_with_additions
test_multiple_devices_separate_tables
test_scoped_deletion_subdirectory
test_mixed_operations_workflow
test_nested_directory_structure
```

### Root cause
`scan_path()` calls `findmnt -T <path>` to discover the device that a directory
lives on. On this host, `/tmp` is **not** a separate mount — it lives on the root
NVMe partition (`/dev/nvme0n1p7`). `findmnt -T /tmp/pytest-xxx/...` therefore
returns the device ID of the root partition (e.g. `2049`).

The tests create temp directories under `/tmp`, call `scan_path()`, then query
the catalog for tables named `files_<device_id>`. Because the device ID is
host-specific and collides with real catalog data from other scans on the same
machine, table lookups fail or return wrong results.

### Evidence
`tests/test_scan_integration.py` uses `tempfile.TemporaryDirectory()` and
`pytest`'s `tmp_path` fixture, both of which resolve to `/tmp/` on this host.
Observed assertion failure:
```
assert 0 == 3  # "Should have 3 active files in device table"
```
The device table is created under a different name than the test queries,
so it finds 0 rows.

### Proposed fix
**Option A — skip on `/tmp`-on-root hosts (minimal, immediate):**
Add a session-scoped autouse fixture that checks `findmnt -T /tmp` and emits
`pytest.skip()` with a clear message when it returns the root partition.

```python
# conftest.py (or tests/conftest_scan.py)
import subprocess, pytest
@pytest.fixture(scope="session", autouse=False)
def require_separate_tmp_mount():
    result = subprocess.run(
        ["findmnt", "-T", "/tmp", "-no", "SOURCE"],
        capture_output=True, text=True
    )
    src = result.stdout.strip()
    if src == subprocess.run(
        ["findmnt", "/", "-no", "SOURCE"],
        capture_output=True, text=True
    ).stdout.strip():
        pytest.skip("test_scan_integration requires /tmp on a separate mount")
```

Apply the fixture to all tests in `test_scan_integration.py` via `pytestmark`.

**Option B — redirect temp dirs off `/tmp` (robust, CI-safe):**
In `pyproject.toml`, add:
```toml
[tool.pytest.ini_options]
tmp_path_retention_policy = "failed"
```
and set `TMPDIR=/var/tmp` or a path on a separate device when running these
tests. `/var/tmp` is typically on a different partition on most Linux hosts.

**Option C — mock `findmnt` in these tests (hermetic):**
Patch `hashall.scan.get_mount_info` (or equivalent) to return a fixed device ID,
making these tests fully hermetic and device-agnostic.

**Recommended:** Option A is the least invasive and correctly communicates the
host requirement. Option C gives the most durable tests.

---

## Group 2 — `test_codex_says_run_this_next_script.py` (4 failures)

### Failing tests
```
test_cli_min_free_pct_overrides_nohl_default
test_cli_min_free_pct_rejects_non_numeric_values
test_nohl_restart_includes_qb_automation_audit_and_watchdog_steps
test_nohl_restart_watchdog_allow_file_is_rendered_when_set
```

### Root cause
The tests run `bin/codex-says-run-this-next.sh` with env
`REHOME_PROCESS_MODE=nohl-restart` and args like `--min-free-pct 17`, expecting
output strings such as `mode=nohl-restart min_free_pct=17`,
`bin/rehome-89_nohl-basics-qb-automation-audit.sh`, etc.

The **actual** script is a sequential real-filesystem pipeline runner:
```bash
step "1. Scan /stash/media ..." "$repo_root/bin/db-refresh-step1-scan-stash.sh"
step "2. Scan /pool/data ..."   "$repo_root/bin/db-refresh-step2-scan-pool-hotspare.sh"
...
```

`bash script.sh --min-free-pct 17` silently ignores the unknown args (bash
doesn't validate them). The script then **actually runs the full refresh
pipeline against the live filesystem**, taking ~18 minutes before failing with:

```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

This JSON error comes from a step inside the pipeline attempting to parse a qB
cache or state file that is empty or missing in the test environment. Exit code
is `1` (not `0` as tests expect for success, not `2` as the numeric-validation
test expects for a validation error).

**Secondary cost:** these 4 tests consume ~18 minutes of CI time on every run
while executing real scans on the live filesystem, which is a safety concern.

### Likely history
The tests were written speculatively to describe the *intended* behavior of a
nohl-restart orchestration wrapper. The script name was reused for a different
purpose (full refresh pipeline), and the tests were never updated to match.

### Proposed fix
**Option A — implement the described interface (correct long-term):**
Extend `bin/codex-says-run-this-next.sh` to support `REHOME_PROCESS_MODE` and
`--min-free-pct` flags, emitting the expected output lines. The tests then
document a real operational contract.

**Option B — rename/delete the tests (if the contract is dead):**
If the nohl-restart wrapper concept is no longer the intended design, remove or
rename this test file and record the decision in ops-log.md.

**Option C — xfail with a reason (interim):**
Mark all four tests `@pytest.mark.xfail(reason="bin/codex-says-run-this-next.sh not yet updated to nohl-restart mode", strict=True)` so they are tracked but don't pollute the failure count.

**Recommended:** Clarify intent — if the nohl-restart wrapper is still planned,
implement it (Option A) or xfail while it's in progress (Option C). If the
design moved on, delete the tests (Option B).

⚠️ **Immediate concern regardless of long-term plan:** Add a guard at the top of
the script (or in a conftest skip fixture) to prevent CI runs from executing the
18-minute live filesystem scan as a side effect of these tests.

---

## Group 3 — `test_payload_auto_workflow.py` (2 failures)

### Failing tests
```
test_main_fail_closed_stops_on_stale_qbit_manage
test_main_dry_run_previews_once_when_upgrade_needed
```

### Root cause
Both tests patch `workflow._load_completed_torrent_hashes` (leading underscore):
```python
monkeypatch.setattr(workflow, "_load_completed_torrent_hashes", lambda: (set(), True, None))
```

The function in `scripts/payload_auto_workflow.py` was renamed to the public
form `load_completed_torrent_hashes` (no leading underscore):
```python
completed_hashes, completion_filter_active, completion_filter_error = load_completed_torrent_hashes()
```

`monkeypatch.setattr` silently **adds** a new attribute `_load_completed_torrent_hashes`
to the module object without touching the real function. The real
`load_completed_torrent_hashes` runs instead, which requires a live qB cache
file or QB connection, and fails in the test environment.

### Proposed fix
**Minimal fix (one line per test):**
Change both monkeypatches from `_load_completed_torrent_hashes` to
`load_completed_torrent_hashes`.

```python
# Before
monkeypatch.setattr(workflow, "_load_completed_torrent_hashes", lambda: (set(), True, None))
# After
monkeypatch.setattr(workflow, "load_completed_torrent_hashes", lambda: (set(), True, None))
```

This is a pure test fix with no production code changes required.

**Effort:** ~5 minutes.

---

## Summary Table

| Test file | Count | Root cause | Effort | Priority |
|---|---|---|---|---|
| `test_scan_integration.py` | 7 | Host `/tmp` on root partition — `findmnt -T` returns wrong device ID | Low–Medium | Medium |
| `test_codex_says_run_this_next_script.py` | 4 | Script/test interface mismatch — nohl-restart mode not implemented | Medium (implement) or Low (xfail/delete) | Low |
| `test_payload_auto_workflow.py` | 2 | Monkeypatch targets `_load_completed_torrent_hashes` (private), function is now public `load_completed_torrent_hashes` | Trivial (5 min) | **High** |

**Recommended order of attack:**
1. Fix `test_payload_auto_workflow.py` — trivial rename, highest value (recovers 2 tests immediately).
2. Fix `test_scan_integration.py` — either skip fixture or Option C mock; recovers 7 tests.
3. Decide on `test_codex_says_run_this_next_script.py` — implement or delete.
