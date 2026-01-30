# gptrail: pyco-hashall-003-26Jun25-smart-verify-2cfc4c
import unittest
from unittest.mock import patch, MagicMock
import sys
from src.hashall import verify

class TestVerifyCLI(unittest.TestCase):

    @patch("src.hashall.verify_trees.run_verification")
    @patch("src.hashall.verify.load_scan_sessions")
    def test_verify_command_runs_comparison(self, mock_load_sessions, mock_run_verification):
        # Setup mock scan session loading
        mock_src = MagicMock()
        mock_dest = MagicMock()
        mock_load_sessions.return_value = (mock_src, mock_dest)

        test_args = ["verify", "/src", "/dest", "--force"]
        with patch.object(sys, "argv", ["hashall"] + test_args):
            verify.main()

        mock_load_sessions.assert_called_once_with("/src", "/dest", force=True)
        mock_run_verification.assert_called_once_with(mock_src, mock_dest, repair=False)

    @patch("src.hashall.verify_trees.run_verification")
    @patch("src.hashall.verify.load_scan_sessions")
    def test_repair_flag_triggers_repair_mode(self, mock_load_sessions, mock_run_verification):
        mock_src = MagicMock()
        mock_dest = MagicMock()
        mock_load_sessions.return_value = (mock_src, mock_dest)

        test_args = ["verify", "/src", "/dest", "--repair"]
        with patch.object(sys, "argv", ["hashall"] + test_args):
            verify.main()

        mock_run_verification.assert_called_once_with(mock_src, mock_dest, repair=True)

    @patch("src.hashall.verify.print_usage")
    def test_missing_arguments_prints_help(self, mock_print_usage):
        test_args = ["verify"]
        with patch.object(sys, "argv", ["hashall"] + test_args):
            with self.assertRaises(SystemExit):
                verify.main()

        mock_print_usage.assert_called_once()

if __name__ == "__main__":
    unittest.main()
