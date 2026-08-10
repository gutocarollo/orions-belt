from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "templates/.harness/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from council_cost_report import build_report  # noqa: E402


class CouncilCostReportTest(unittest.TestCase):
    def test_observed_metrics_are_aggregated_without_becoming_a_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sub = root / ".harness/runs/subagents/session-1/agent-1.jsonl"
            sub.parent.mkdir(parents=True)
            sub.write_text("\n".join([
                json.dumps({"event": "SubagentStart", "run_id": "r1", "agent_id": "a1", "agent_type": "context-scout", "model": "sonnet"}),
                json.dumps({"event": "AgentToolResult", "run_id": "r1", "agent_id": "a1", "agent_type": "context-scout", "model": "sonnet", "usage": {"input_tokens": 100, "output_tokens": 20}, "duration_ms": 250}),
            ]) + "\n", encoding="utf-8")
            tools = root / ".harness/runs/context-tools/session-1/tools.jsonl"
            tools.parent.mkdir(parents=True)
            tools.write_text(json.dumps({"event": "PostToolUse", "run_id": "r1", "tool_use_id": "t1"}) + "\n", encoding="utf-8")
            report = build_report(root, run_id="r1", profile="LIGHT")
            self.assertFalse(report["blocking"])
            self.assertEqual(1, report["observed"]["subagents_started"])
            self.assertEqual(1, report["observed"]["tool_calls"])
            self.assertEqual(100, report["observed"]["token_usage"]["input_tokens"])
            self.assertEqual(20, report["observed"]["token_usage"]["output_tokens"])
            self.assertEqual("OBSERVED", report["observed"]["token_usage"]["source"])
            self.assertEqual(250, report["observed"]["duration"]["subagent_duration_ms"])

    def test_missing_runtime_metrics_are_reported_as_unavailable_not_inferred(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build_report(Path(directory), run_id="missing", profile="DIRECT")
            self.assertEqual(0, report["observed"]["token_usage"]["input_tokens"])
            self.assertEqual("UNAVAILABLE", report["observed"]["token_usage"]["source"])
            self.assertEqual("UNAVAILABLE", report["observed"]["duration"]["source"])
            self.assertIn("Parent-model tokens", report["limitations"][0])


if __name__ == "__main__":
    unittest.main()
