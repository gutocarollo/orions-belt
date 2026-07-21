import json
import tempfile
import unittest
from pathlib import Path

from engine.release_check import Gate, _select, run_gates


class ReleaseCheckTest(unittest.TestCase):
    def test_machine_report_aggregates_pass_and_failure(self) -> None:
        gates = [
            Gate("pass", ("python3", "-c", "print('ok')"), 5),
            Gate("fail", ("python3", "-c", "raise SystemExit(7)"), 5),
        ]
        report = run_gates(gates)
        self.assertEqual(("FAIL", 1, 1), (report["status"], report["passed"], report["failed"]))
        self.assertEqual(7, report["gates"][1]["exit_code"])
        json.dumps(report)

    def test_timeout_is_a_failure(self) -> None:
        report = run_gates([Gate("slow", ("python3", "-c", "import time; time.sleep(2)"), 1)])
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(report["gates"][0]["timed_out"])

    def test_gate_selection_is_deterministic_and_rejects_unknown(self) -> None:
        self.assertEqual(["graph_schema", "diff_check"], [gate.name for gate in _select(["diff_check,graph_schema"])])
        with self.assertRaises(ValueError):
            _select(["imaginary"])


if __name__ == "__main__":
    unittest.main()
