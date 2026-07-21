import json
import tempfile
import unittest
from pathlib import Path

from engine.observability.tracing import REDACTED, TraceValidationError, append_trace, correlated, prepare_record


def record(**overrides):
    value = {
        "schema_version": "1.0", "trace_id": "trace-1", "span_id": "span-1",
        "parent_span_id": None, "run_id": "run-1", "node_id": "plan",
        "agent_id": "planner", "kind": "EVENT", "name": "plan.created",
        "timestamp": "2026-07-21T00:00:00Z", "attributes": {"attempt": 1},
    }
    value.update(overrides)
    return value


class TracingTest(unittest.TestCase):
    def test_nested_secrets_and_bearer_values_are_redacted(self) -> None:
        safe = prepare_record(record(attributes={
            "api_key": "abc", "nested": {"password": "x"},
            "message": "request used Bearer abc.DEF-123", "safe": "visible",
        }))
        self.assertEqual(REDACTED, safe["attributes"]["api_key"])
        self.assertEqual(REDACTED, safe["attributes"]["nested"]["password"])
        self.assertNotIn("abc.DEF", safe["attributes"]["message"])
        self.assertEqual("visible", safe["attributes"]["safe"])

    def test_append_writes_redacted_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            append_trace(path, record(attributes={"token": "do-not-write"}))
            persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(REDACTED, persisted["attributes"]["token"])

    def test_correlation_filters_run_node_and_agent(self) -> None:
        records = [record(), record(span_id="span-2", node_id="execute", agent_id="worker"), record(span_id="span-3", run_id="other")]
        self.assertEqual(["span-1"], [item["span_id"] for item in correlated(records, "run-1", "plan", "planner")])

    def test_invalid_record_is_rejected(self) -> None:
        with self.assertRaises(TraceValidationError):
            prepare_record(record(run_id=""))
        with self.assertRaises(TraceValidationError):
            prepare_record(record(extra="not-allowed"))


if __name__ == "__main__":
    unittest.main()
