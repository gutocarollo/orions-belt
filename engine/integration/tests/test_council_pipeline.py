import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from engine.evidence.manifest import assert_valid_manifest
from engine.graph.runtime import load_graph, replay
from engine.integration.council_pipeline import IntegrationError, integrate_ledger
from engine.observability.tracing import correlated

ROOT = Path(__file__).resolve().parents[3]


def ledger() -> list[dict]:
    rows = [
        ("planning", 1, "review", "SABATINAR", {}),
        ("planning", 1, "validation", "DECIDIDO", {"agent_id": "human-owner"}),
        ("planning", 2, "review", "SATISFEITO", {}),
        ("execution", 3, "review", "CORRIGIR", {}),
        ("execution", 3, "fix-request", "CORRIGIR", {"gap": "high-risk gap"}),
        ("execution", 3, "fix-consumed", "CORRIGIR", {"fix": "applied"}),
        ("execution", 4, "review", "SATISFEITO", {}),
        ("execution", 4, "validation", "PASS", {"tests": 42}),
    ]
    result = []
    for seq, (loop, round_number, event, status, payload) in enumerate(rows, 1):
        item = {
            "ts": f"2026-07-21T12:00:{seq:02d}Z", "run_id": "integration-1", "seq": seq,
            "loop": loop, "round": round_number, "event": event, "status": status, "payload": payload,
        }
        if event == "fix-consumed":
            item["parent_seq"] = 5
        result.append(item)
    return result


class CouncilPipelineE2ETest(unittest.TestCase):
    def test_sabatinar_human_corrigir_proof_pipeline(self) -> None:
        result = integrate_ledger(ledger(), "2fedfb9")
        state = result["state"]
        self.assertEqual(("COMPLETED", "done"), (state["status"], state["current_node"]))
        self.assertEqual(["SABATINAR", "SATISFEITO"], [item["outcome"] for item in state["reviews"]["plan"]])
        self.assertEqual(["CORRIGIR", "SATISFEITO"], [item["outcome"] for item in state["reviews"]["execution"]])
        self.assertIn("human_input", state["visited"])
        self.assertEqual(state, replay(result["control_events"], load_graph()))

        evidence = result["evidence"]
        assert_valid_manifest(evidence)
        self.assertEqual("PASS", evidence["claims"][0]["status"])
        self.assertEqual(4, len(evidence["entities"]))
        replay_activity = next(item for item in evidence["activities"] if item["id"] == "activity:replay")
        self.assertEqual("transform", replay_activity["type"])
        self.assertNotIn("command", replay_activity)

        traces = result["traces"]
        self.assertEqual(16, len(traces))
        self.assertEqual(2, len(correlated(traces, "integration-1", "human_input", "council")))
        self.assertEqual(2, len(correlated(traces, "integration-1", "plan_review", "human-owner")))
        self.assertTrue(all(item["trace_id"] == "trace-integration-1" for item in traces))

    def test_same_ledger_has_byte_stable_derived_structures(self) -> None:
        first = integrate_ledger(ledger(), "2fedfb9")
        second = integrate_ledger(ledger(), "2fedfb9")
        self.assertEqual(first, second)

    def test_invalid_ledger_timestamp_fails_before_expansion(self) -> None:
        broken = ledger()
        broken[0]["ts"] = "not-a-dateZ"
        with self.assertRaisesRegex(IntegrationError, "RFC3339"):
            integrate_ledger(broken, "2fedfb9")

    def test_cli_consumes_ledger_materialized_by_installed_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            lib = target / ".harness" / "lib"
            lib.mkdir(parents=True)
            for name in ("agent_swarm_ledger.py", "_tooling_conf.py"):
                shutil.copy2(ROOT / "templates" / ".harness" / "lib" / name, lib / name)
            environment = {**os.environ, "HARNESS_PROJECT_ROOT": str(target)}
            commands = [
                ("planning", "1", "review", "SABATINAR", "{}"),
                ("planning", "1", "validation", "DECIDIDO", '{"agent_id":"human-owner"}'),
                ("planning", "2", "review", "SATISFEITO", "{}"),
                ("execution", "3", "review", "CORRIGIR", "{}"),
                ("execution", "3", "fix-request", "CORRIGIR", "{}"),
                ("execution", "3", "fix-consumed", "CORRIGIR", "{}"),
                ("execution", "4", "review", "SATISFEITO", "{}"),
                ("execution", "4", "validation", "PASS", "{}"),
            ]
            for loop, round_number, event_name, status, payload in commands:
                proc = subprocess.run(
                    ["python3", str(lib / "agent_swarm_ledger.py"), "append", "--run-id", "real-ledger",
                     "--loop", loop, "--round", round_number, "--event", event_name,
                     "--status", status, "--payload-json", payload],
                    cwd=target, env=environment, capture_output=True, text=True,
                )
                self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            ledger_path = target / ".harness" / "runs" / "agent-swarm" / "real-ledger" / "loop.jsonl"
            output = target / "proof"
            proc = subprocess.run(
                ["python3", "engine/integration/council_pipeline.py", str(ledger_path),
                 "--git-sha", "2fedfb9", "--output-dir", str(output)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            state = json.loads((output / "run-state.json").read_text(encoding="utf-8"))
            evidence = json.loads((output / "evidence-manifest.json").read_text(encoding="utf-8"))
            traces = json.loads((output / "traces.json").read_text(encoding="utf-8"))
            self.assertEqual(("COMPLETED", "done"), (state["status"], state["current_node"]))
            self.assertEqual("PASS", evidence["claims"][0]["status"])
            self.assertEqual(16, len(traces))


if __name__ == "__main__":
    unittest.main()
