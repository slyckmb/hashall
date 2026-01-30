# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import os
import shutil
import yaml
from pathlib import Path
from gptrail.utils.trail import remove_slug_entry

TRAIL_DIR = Path(".gpt")
TRAIL_FILE = TRAIL_DIR / "trail.yaml"
DUMMY_SLUG = "test-gptrail-delete-001"

def setup_module(module):
    # Prepare test .gpt dir and files
    os.makedirs(TRAIL_DIR, exist_ok=True)
    (TRAIL_DIR / f"{DUMMY_SLUG}.md").write_text("# test md file", encoding="utf-8")

    trail_data = {
        "trail": [
            {"slug": DUMMY_SLUG, "title": "Test Deletion"}
        ]
    }
    with open(TRAIL_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(trail_data, f)

def teardown_module(module):
    shutil.rmtree(TRAIL_DIR)

def test_delete_dry_run():
    matched, deleted = remove_slug_entry("delete-001", force=False)
    assert matched == DUMMY_SLUG
    assert deleted is False
    assert (TRAIL_DIR / f"{DUMMY_SLUG}.md").exists()
    assert DUMMY_SLUG in open(TRAIL_FILE).read()

def test_delete_force():
    matched, deleted = remove_slug_entry("delete-001", force=True)
    assert matched == DUMMY_SLUG
    assert deleted is True
    assert not (TRAIL_DIR / f"{DUMMY_SLUG}.md").exists()
    with open(TRAIL_FILE, encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)
        assert all(DUMMY_SLUG not in e["slug"] for e in yaml_data["trail"])
