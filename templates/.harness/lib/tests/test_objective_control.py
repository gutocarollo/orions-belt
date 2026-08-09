import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

from objective_control import ObjectiveControlError, assess_impact, record_deferred, validate_execution_graph, verify_code_necessity  # noqa: E402


def impact(**overrides):
    value = {"id": "F-1", "evidence_status": "REAL", "evidence": "test evidence", "objective_impact": 4, "journey_reachability": 4, "acceptance_impact": 4, "irreversibility": 3, "dependency_urgency": 4, "on_critical_path": True, "affects_current_phase": True, "validated_workaround": False, "graph_nodes": ["start", "goal"]}
    value.update(overrides)
    return value


def graph():
    tests1 = {"functional": ["F1"], "quality": ["Q1"], "regression": ["R1"]}
    tests2 = {"functional": ["F2"], "quality": ["Q2"], "regression": ["R2"]}
    return {"objective": "deliver the requested result", "start_node": "request", "goal_node": "delivery", "nodes": ["request", "implementation", "delivery"], "edges": [
        {"edge_id": "E1", "from": "request", "to": "implementation", "critical": True, "phase": "p1", "item": "i1", "tests": tests1, "evidence": ["evidence/e1.json"]},
        {"edge_id": "E2", "from": "implementation", "to": "delivery", "critical": True, "phase": "p2", "item": "i2", "tests": tests2, "evidence": ["evidence/e2.json"]},
    ]}


class ObjectiveImpactTest(unittest.TestCase):
    def test_disposition_is_computed_from_evidence_path_and_weighted_score(self):
        critical = assess_impact(impact())
        high = assess_impact(impact(objective_impact=3, journey_reachability=3, acceptance_impact=3, irreversibility=3, dependency_urgency=3))
        deferred = assess_impact(impact(evidence_status="UNVERIFIED"))
        self.assertEqual((96.25, "CRITICAL_BLOCK"), (critical["score"], critical["disposition"]))
        self.assertEqual((75.0, "HIGH_FIX_NOW"), (high["score"], high["disposition"]))
        self.assertEqual("DEFER_RUN", deferred["disposition"])

    def test_declared_score_or_disposition_cannot_override_calculation(self):
        with self.assertRaisesRegex(ObjectiveControlError, "declared score"):
            assess_impact(impact(score=10, disposition="DEFER_RUN"))

    def test_noncritical_or_workaround_finding_is_deferred(self):
        self.assertEqual("DEFER_RUN", assess_impact(impact(on_critical_path=False, affects_current_phase=False))["disposition"])
        self.assertEqual("DEFER_RUN", assess_impact(impact(validated_workaround=True))["disposition"])


class ExecutionGraphTest(unittest.TestCase):
    def test_connected_graph_with_three_test_classes_passes(self):
        result = validate_execution_graph(graph())
        self.assertEqual(["E1", "E2"], result["critical_path"])
        self.assertEqual(["E1", "E2"], result["critical_edges"])

    def test_all_critical_branches_are_returned_not_only_first_path(self):
        branching = graph()
        branching["nodes"].append("alternate")
        branching["edges"].extend([
            {**branching["edges"][0], "edge_id": "E3", "to": "alternate"},
            {**branching["edges"][1], "edge_id": "E4", "from": "alternate"},
        ])
        self.assertEqual(["E1", "E2", "E3", "E4"], validate_execution_graph(branching)["critical_edges"])

    def test_disconnected_graph_or_missing_test_class_fails(self):
        disconnected = graph()
        disconnected["edges"] = disconnected["edges"][:1]
        with self.assertRaisesRegex(ObjectiveControlError, "no path"):
            validate_execution_graph(disconnected)
        missing = graph()
        missing["edges"][0]["tests"]["quality"] = []
        with self.assertRaisesRegex(ObjectiveControlError, "quality"):
            validate_execution_graph(missing)


class DeferredRunTest(unittest.TestCase):
    def test_deferred_finding_is_recorded_idempotently_in_existing_section(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "RUN.md"
            run.write_text("# RUN\n\n## Pendências não bloqueantes\n- Nenhuma no início do run.\n\n## Journal\n", encoding="utf-8")
            deferred = assess_impact(impact(evidence_status="UNVERIFIED")) | {"reason": "not proven", "review_after": "phase-2"}
            record_deferred(run, deferred)
            first = run.read_text(encoding="utf-8")
            record_deferred(run, deferred)
            self.assertEqual(first, run.read_text(encoding="utf-8"))
            self.assertIn("F-1", first)


class CodeNecessityTest(unittest.TestCase):
    def test_every_added_code_line_must_belong_to_a_justified_portion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            source = root / "app.py"
            source.write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            source.write_text("value = 1\nresult = value + 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=root, check=True)
            report = {"base_sha": base, "head_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(), "portions": []}
            with self.assertRaisesRegex(ObjectiveControlError, "distinct"):
                verify_code_necessity(root, {"base_sha": report["head_sha"], "head_sha": report["head_sha"], "portions": []})
            with self.assertRaisesRegex(ObjectiveControlError, "uncovered"):
                verify_code_necessity(root, report)
            portion = {
                "path": "app.py",
                "start_line": 2,
                "end_line": 2,
                "purpose": "compute result",
                "objective": "prove the requested calculation",
                "inputs": ["value"],
                "outputs": ["result"],
                "evidence": [{"path": "app.py", "line": 2, "contains": "result = value + 1", "command": "test -s app.py"}],
                "simpler_alternative": "none",
                "necessity": "requested behavior",
            }
            report["portions"] = [portion]
            self.assertEqual(1, verify_code_necessity(root, report)["covered_lines"])

            report["portions"] = [{**portion, "evidence": [{"path": "missing.py", "line": 1, "contains": "proof", "command": "true"}]}]
            with self.assertRaisesRegex(ObjectiveControlError, "evidence path"):
                verify_code_necessity(root, report)
            report["portions"] = [{**portion, "evidence": [{"path": "app.py", "line": 2, "contains": "fabricated marker", "command": "true"}]}]
            with self.assertRaisesRegex(ObjectiveControlError, "evidence marker"):
                verify_code_necessity(root, report)
            report["portions"] = [{**portion, "evidence": [{"path": "app.py", "line": 2, "contains": "result = value + 1", "command": "false"}]}]
            with self.assertRaisesRegex(ObjectiveControlError, "evidence command"):
                verify_code_necessity(root, report)
            report["portions"] = [{**portion, "evidence": [{"path": "app.py", "line": 2, "contains": "result = value + 1", "command": "true"}]}]
            with self.assertRaisesRegex(ObjectiveControlError, "no-op"):
                verify_code_necessity(root, report)
            report["portions"] = [{**portion, "start_line": 1, "end_line": 1}]
            with self.assertRaisesRegex(ObjectiveControlError, "added code line"):
                verify_code_necessity(root, report)
            report["portions"] = [{key: value for key, value in portion.items() if key != "objective"}]
            with self.assertRaisesRegex(ObjectiveControlError, "objective"):
                verify_code_necessity(root, report)
            report["portions"] = [portion]

            receipt_head = report["head_sha"]
            (root / "receipt.json").write_text("{}\n", encoding="utf-8")
            subprocess.run(["git", "add", "receipt.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "version receipt"], cwd=root, check=True)
            self.assertEqual(1, verify_code_necessity(root, report)["covered_lines"])

            source.write_text("value = 1\nresult = value + 1\nfinal = result\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "later code"], cwd=root, check=True)
            self.assertEqual(receipt_head, report["head_sha"])
            with self.assertRaisesRegex(ObjectiveControlError, "stale"):
                verify_code_necessity(root, report)

    def test_code_necessity_rejects_vague_large_portion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "baseline.txt").write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "add", "baseline.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=root, check=True)
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            source = root / "large.py"
            source.write_text("".join(f"value_{line} = {line}\n" for line in range(1, 122)), encoding="utf-8")
            subprocess.run(["git", "add", "large.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "large addition"], cwd=root, check=True)
            report = {
                "base_sha": base,
                "head_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "portions": [{
                    "path": "large.py",
                    "start_line": 1,
                    "end_line": 121,
                    "purpose": "vague whole-file receipt",
                    "objective": "demonstrate rejected granularity",
                    "inputs": ["fixture"],
                    "outputs": ["large file"],
                    "evidence": [{"path": "large.py", "line": 1, "contains": "value_1 = 1", "command": "test -s large.py"}],
                    "simpler_alternative": "split by semantic responsibility",
                    "necessity": "negative fixture",
                }],
            }
            with self.assertRaisesRegex(ObjectiveControlError, "120 lines"):
                verify_code_necessity(root, report)


if __name__ == "__main__":
    unittest.main()
