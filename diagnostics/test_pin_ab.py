import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock

SPEC = importlib.util.spec_from_file_location("pin_ab", Path(__file__).with_name("pin_ab.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TestDiagnostic(unittest.TestCase):
    def test_exact_catalog_requires_official_windows_build(self):
        row = {
            "key": MODULE.B_KEY,
            "url": "https://releases.astral.sh/github/python-build-standalone/releases/download/x/python.tar.gz",
        }
        self.assertEqual(MODULE.select_distribution([row]), row)
        for rows in ([], [{**row, "url": "https://evil.invalid/python.tar.gz"}], [row, row]):
            with self.assertRaises(ValueError):
                MODULE.select_distribution(rows)

    def test_classifies_timeout_crash_and_unexercised_pass_separately(self):
        self.assertEqual(MODULE.classify("1 passed", 0, False)["outcome"], "pass")
        self.assertFalse(MODULE.classify("1 passed", 0, False)["diagnostic_fired"])
        evidence = "Timeout (0:01:00)!\nWindows fatal exception: access violation"
        result = MODULE.classify(evidence, 1, False)
        self.assertEqual(result["outcome"], "access_violation")
        self.assertTrue(result["diagnostic_fired"])
        self.assertEqual(MODULE.classify("", -1, True)["outcome"], "outer_timeout_incomplete")

    def test_twelve_cells_alternate_without_retry(self):
        cells = MODULE.cells()
        self.assertEqual(len(cells), 12)
        self.assertEqual(len(set(cells)), 12)
        self.assertEqual([c[1] for c in cells[:2]], ["A", "B"])
        self.assertEqual([c[1] for c in cells[6:8]], ["B", "A"])

    def test_remaining_budget_never_negative(self):
        self.assertEqual(MODULE.remaining_seconds(180, 179), 1)
        self.assertEqual(MODULE.remaining_seconds(180, 181), 0)

    def test_kill_cleanup_stays_inside_cell_deadline(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("owned", 178), -1]
        clock = Mock(side_effect=[10, 188])
        code, timed_out, error = MODULE.bounded_wait(process, 190, clock)
        self.assertEqual(process.wait.call_args_list[0].kwargs["timeout"], 178)
        self.assertEqual(process.wait.call_args_list[1].kwargs["timeout"], 2)
        process.kill.assert_called_once_with()
        self.assertEqual((code, timed_out, error), (-1, True, None))

    def test_cleanup_failure_is_returned_for_preservation(self):
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired("owned", 178)
        process.kill.side_effect = OSError("owned handle failure")
        process.poll.return_value = None
        code, timed_out, error = MODULE.bounded_wait(process, 190, lambda: 10)
        self.assertIsNone(code)
        self.assertTrue(timed_out)
        self.assertIn("owned handle failure", error)
