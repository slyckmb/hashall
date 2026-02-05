# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import unittest
from hashall import diff

class TestDiffLogic(unittest.TestCase):

    def setUp(self):
        # Simulate file scan entries: {path: (hash, inode, device_id)}
        self.src_files = {
            "/alpha.txt": {"hash": "hash1", "inode": 101, "device_id": 1},
            "/beta.txt": {"hash": "hash2", "inode": 102, "device_id": 1},
            "/hardlink1": {"hash": "hash3", "inode": 200, "device_id": 1},
        }

        self.dest_files = {
            "/alpha.txt": {"hash": "hash1", "inode": 201, "device_id": 1},
            "/beta.txt": {"hash": "DIFFERENT", "inode": 102, "device_id": 1},
            "/extra.txt": {"hash": "hash4", "inode": 300, "device_id": 1},
            "/hardlink2": {"hash": "hash3", "inode": 200, "device_id": 1},  # same inode = hardlink
        }

    def test_detects_changed_file(self):
        result = diff.diff_sessions(self.src_files, self.dest_files)
        self.assertIn("/beta.txt", result["changed"])

    def test_detects_added_file(self):
        result = diff.diff_sessions(self.src_files, self.dest_files)
        self.assertIn("/extra.txt", result["added"])

    def test_detects_removed_file(self):
        del self.dest_files["/beta.txt"]
        result = diff.diff_sessions(self.src_files, self.dest_files)
        self.assertIn("/beta.txt", result["removed"])

    def test_hardlink_equivalence(self):
        # Should only consider hash and inode+device match
        result = diff.diff_sessions(self.src_files, self.dest_files)
        self.assertNotIn("/hardlink2", result["changed"])
        self.assertNotIn("/hardlink2", result["added"])

    def test_hardlink_not_removed(self):
        # Same inode+device present under different path should not be removed
        result = diff.diff_sessions(self.src_files, self.dest_files)
        self.assertNotIn("/hardlink1", result["removed"])

    def test_device_id_mismatch_is_change(self):
        self.dest_files["/alpha.txt"]["device_id"] = 9  # mismatch
        result = diff.diff_sessions(self.src_files, self.dest_files)
        self.assertIn("/alpha.txt", result["changed"])

if __name__ == '__main__':
    unittest.main()
