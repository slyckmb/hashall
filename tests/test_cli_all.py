# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import subprocess
import unittest
import os

class TestHashallCLIIntegration(unittest.TestCase):

    def test_cli_help_flag(self):
        result = subprocess.run(
            ["python3", "-m", "src.hashall.__main__", "--help"],
            capture_output=True, text=True
        )
        self.assertIn("verify-trees", result.stdout)
        self.assertEqual(result.returncode, 0)

    def test_cli_verify_trees_fake_paths(self):
        # NOTE: This should fail gracefully, not crash
        result = subprocess.run(
            ["python3", "-m", "src.hashall.__main__", "verify-trees", "/not/real", "/also/fake"],
            capture_output=True, text=True
        )
        self.assertIn("could not load", result.stderr.lower())
        self.assertNotEqual(result.returncode, 0)

    def test_cli_without_args(self):
        result = subprocess.run(
            ["python3", "-m", "src.hashall.__main__"],
            capture_output=True, text=True
        )
        self.assertIn("usage", result.stdout.lower())
        self.assertEqual(result.returncode, 0)

if __name__ == "__main__":
    unittest.main()
