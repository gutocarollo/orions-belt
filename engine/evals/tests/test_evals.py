import copy
import json
import unittest
from pathlib import Path

from engine.evals.run_evals import EvalFormatError, evaluate, validate_suite
from engine.graph.runtime import load_graph


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "golden_cases.json"


class EvalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.suite = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.graph = load_graph()

    def test_golden_trajectories_pass(self) -> None:
        result = evaluate(self.suite, self.graph)
        self.assertEqual((2, 0), (result["passed"], result["failed"]))
        self.assertGreater(result["transition_coverage"], 0)

    def test_wrong_expected_outcome_is_a_failure(self) -> None:
        broken = copy.deepcopy(self.suite)
        broken["cases"][0]["expected"]["current_node"] = "blocked"
        result = evaluate(broken, self.graph)
        self.assertEqual(1, result["failed"])
        self.assertIn("current_node", result["cases"][0]["errors"][0])

    def test_duplicate_case_ids_are_rejected(self) -> None:
        broken = copy.deepcopy(self.suite)
        broken["cases"].append(copy.deepcopy(broken["cases"][0]))
        with self.assertRaises(EvalFormatError):
            validate_suite(broken)


if __name__ == "__main__":
    unittest.main()
