# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import unittest
from unittest.mock import MagicMock
from src.hashall import verify_trees

class TestVerifyTrees(unittest.TestCase):

    def setUp(self):
        # Mock scan sessions for source and dest
        self.src_session = MagicMock()
        self.dest_session = MagicMock()

        self.src_session.id = 1
        self.dest_session.id = 2

        self.src_session.files = {
            "/foo.txt": {"hash": "abc123", "inode": 1001},
            "/bar.txt": {"hash": "def456", "inode": 1002},
        }

        self.dest_session.files = {
            "/foo.txt": {"hash": "abc123", "inode": 1003},
            "/bar.txt": {"hash": "changed456", "inode": 1002},
            "/extra.txt": {"hash": "zzz999", "inode": 1004},
        }

    def test_diff_finds_changed_and_extra_files(self):
        diff_report = verify_trees.compare_sessions(self.src_session, self.dest_session)
        self.assertIn("/bar.txt", diff_report["changed"])
        self.assertIn("/extra.txt", diff_report["added"])
        self.assertNotIn("/foo.txt", diff_report["changed"])

    def test_diff_finds_missing_files(self):
        self.dest_session.files.pop("/bar.txt")  # Simulate deletion
        diff_report = verify_trees.compare_sessions(self.src_session, self.dest_session)
        self.assertIn("/bar.txt", diff_report["removed"])

    def test_no_diffs_for_identical_trees(self):
        self.dest_session.files = self.src_session.files.copy()
        diff_report = verify_trees.compare_sessions(self.src_session, self.dest_session)
        self.assertFalse(diff_report["added"])
        self.assertFalse(diff_report["removed"])
        self.assertFalse(diff_report["changed"])

if __name__ == '__main__':
    unittest.main()
