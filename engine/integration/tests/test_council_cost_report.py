from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "templates/.harness/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from council_cost_report import build_report  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "subagent_cost_ledger_test",
    ROOT / "templates/.harness/hooks/subagent-cost-ledger.py",
)
COST_LEDGER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = COST_LEDGER
SPEC.loader.exec_module(COST_LEDGER)


class CouncilCostReportTest(unittest.TestCase):
    def test_observed_metrics_are_aggregated_without_becoming_a_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sub = root / ".harness/runs/subagents/session-1/agent-1.jsonl"
            sub.parent.mkdir(parents=True)
            sub.write_text("\n".join([
                json.dumps({"event": "SubagentStart", "runtime": "claude", "session_id": "session-1", "run_id": "r1", "agent_id": "a1", "agent_type": "context-scout", "model": "sonnet"}),
                json.dumps({"event": "AgentToolResult", "runtime": "claude", "session_id": "session-1", "run_id": "r1", "agent_id": "a1", "agent_type": "context-scout", "model": "sonnet", "usage": {"input_tokens": 100, "output_tokens": 20}, "duration_ms": 250}),
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
            self.assertEqual("CONTEXT_ONLY_LEGACY", report["observed"]["metric_scope"])

    def test_non_context_agents_are_observed_by_lightweight_cost_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".harness").mkdir()
            for call_id, agent_id, role, model, input_tokens, output_tokens in [
                ("t1", "a1", "quality-reviewer", "sonnet", 100, 20),
                ("t2", "a2", "implementer", "opus", 200, 30),
            ]:
                COST_LEDGER.record_event({
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Agent",
                    "tool_use_id": call_id,
                    "session_id": "session-1",
                    "run_id": "r1",
                    "tool_input": {"subagent_type": role},
                    "tool_response": {
                        "agentId": agent_id,
                        "resolvedModel": model,
                        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
                        "durationMs": 250,
                    },
                }, "claude", root)
            report = build_report(root, run_id="r1", profile="LIGHT")
            self.assertEqual(2, report["observed"]["subagents_started"])
            self.assertEqual("ALL_SUBAGENTS", report["observed"]["metric_scope"])
            self.assertEqual(300, report["observed"]["token_usage"]["input_tokens"])
            self.assertEqual(50, report["observed"]["token_usage"]["output_tokens"])
            self.assertEqual({"implementer": 1, "quality-reviewer": 1}, report["observed"]["roles"])

    def test_new_cost_rows_do_not_double_count_legacy_context_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / ".harness/runs/subagents/session-1/agent-1.jsonl"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({
                "event": "SubagentStart", "runtime": "claude", "session_id": "session-1", "run_id": "r1",
                "agent_id": "a1", "agent_type": "context-scout", "model": "sonnet",
            }) + "\n", encoding="utf-8")
            cost = root / ".harness/runs/subagent-cost/session-1/events.jsonl"
            cost.parent.mkdir(parents=True)
            cost.write_text(json.dumps({
                "event": "AgentToolResult", "runtime": "claude", "session_id": "session-1", "run_id": "r1",
                "agent_id": "a1", "agent_type": "context-scout", "model": "sonnet",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }) + "\n", encoding="utf-8")
            report = build_report(root, run_id="r1")
            self.assertEqual(1, report["observed"]["subagents_started"])
            self.assertEqual(10, report["observed"]["token_usage"]["input_tokens"])

    def test_release_records_cost_before_slot_early_exit(self):
        source = (ROOT / "templates/.harness/hooks/subagent-release.sh").read_text(encoding="utf-8")
        self.assertLess(source.index("subagent-cost-ledger.py"), source.index('[ -d "$SLOTS" ] || exit 0'))

    def test_missing_runtime_metrics_are_reported_as_unavailable_not_inferred(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build_report(Path(directory), run_id="missing", profile="DIRECT")
            self.assertEqual(0, report["observed"]["token_usage"]["input_tokens"])
            self.assertEqual("UNAVAILABLE", report["observed"]["token_usage"]["source"])
            self.assertEqual("UNAVAILABLE", report["observed"]["duration"]["source"])
            self.assertIn("Parent-model tokens", report["limitations"][0])


if __name__ == "__main__":
    unittest.main()
