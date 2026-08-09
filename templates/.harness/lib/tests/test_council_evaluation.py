import sys
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
ROOT = LIB.parents[1]
sys.path.insert(0, str(LIB))

from council_evaluator import evaluate  # noqa: E402
from council_scenarios import run_scenarios  # noqa: E402


class CouncilEvaluationTest(unittest.TestCase):
    def test_all_runtime_scenarios_pass_with_real_git_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_scenarios(ROOT, Path(directory))
        self.assertEqual({"read_only", "trivial", "complex"}, set(report["scenarios"]))
        self.assertTrue(all(item["status"] == "PASS" for item in report["scenarios"].values()))
        self.assertTrue(report["scenarios"]["read_only"]["zero_workspace_changes"])
        self.assertTrue(report["scenarios"]["trivial"]["remote_push_blocked"])
        self.assertGreaterEqual(len(report["scenarios"]["complex"]["local_commits"]), 4)
        self.assertTrue(report["scenarios"]["complex"]["resume_replay_equal"])
        self.assertGreaterEqual(len(set(report["scenarios"]["complex"]["reviewer_ids"])), 2)

    def test_evaluator_promotes_only_when_every_criterion_exceeds_8_5(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_scenarios(ROOT, Path(directory))
            result = evaluate(ROOT, report)
            self.assertFalse(result["gates"]["independent_reviewer_evidence"])
            sha = result["git_sha"]
            quality_path = Path(directory) / "quality.md"
            adversarial_path = Path(directory) / "adversarial.md"
            quality_path.write_text(f"SHA: {sha}\nQUALITY-REVIEW: SATISFEITO\n", encoding="utf-8")
            adversarial_path.write_text(f"SHA: {sha}\nADVERSARIAL-VERIFICATION: SATISFEITO\n", encoding="utf-8")
            reviewed = evaluate(ROOT, report, {
                "quality": {"reviewer_id": "11111111-1111-4111-8111-111111111111", "verdict": "SATISFEITO", "critical": 0, "required": 0, "git_sha": sha, "report_path": str(quality_path), "report_sha256": hashlib.sha256(quality_path.read_bytes()).hexdigest()},
                "adversarial": {"reviewer_id": "22222222-2222-4222-8222-222222222222", "verdict": "SATISFEITO", "blocking": 0, "high": 0, "git_sha": sha, "report_path": str(adversarial_path), "report_sha256": hashlib.sha256(adversarial_path.read_bytes()).hexdigest()},
            })
        self.assertFalse(reviewed["gates"]["independent_reviewer_evidence"])
        self.assertTrue(reviewed["gates"]["external_attestation_required"])
        self.assertEqual(min(result["scores"].values()) > 8.5 and all(result["gates"].values()), result["promotion"])
        self.assertGreater(min(reviewed["scores"].values()), 8.5)
        self.assertGreaterEqual(reviewed["overall"], 9.1)
        self.assertEqual(40, len(result["git_sha"]))

    def test_cli_materializes_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            process = subprocess.run(
                [sys.executable, str(LIB / "council_evaluator.py"), "--root", str(ROOT), "--output", str(output), "--expected-sha", subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()],
                capture_output=True, text=True,
            )
            self.assertTrue(output.is_file(), process.stdout + process.stderr)
            self.assertIn('"scores"', output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
