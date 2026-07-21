import unittest

from engine.graph.runtime import GraphError, apply_event, load_graph
from engine.observability.tracing import TraceValidationError, prepare_record


def graph_event(**overrides):
    value = {
        "schema_version": "1.0", "event_id": "evt-1", "run_id": "run-1", "sequence": 1,
        "type": "RUN_STARTED", "occurred_at": "2026-07-21T00:00:00Z", "payload": {},
    }
    value.update(overrides)
    return value


def trace(**overrides):
    value = {
        "schema_version": "1.0", "trace_id": "trace-1", "span_id": "span-1", "run_id": "run-1",
        "kind": "EVENT", "name": "test", "timestamp": "2026-07-21T00:00:00Z", "attributes": {},
    }
    value.update(overrides)
    return value


class NegativeSchemaTest(unittest.TestCase):
    def test_control_event_rejects_invalid_datetime_and_extra_field(self) -> None:
        with self.assertRaisesRegex(GraphError, "RFC3339"):
            apply_event(None, graph_event(occurred_at="yesterday"), load_graph())
        with self.assertRaisesRegex(GraphError, "undeclared fields"):
            apply_event(None, graph_event(forged=True), load_graph())

    def test_trace_rejects_invalid_datetime_and_extra_field(self) -> None:
        with self.assertRaisesRegex(TraceValidationError, "RFC3339"):
            prepare_record(trace(timestamp="2026-07-21"))
        with self.assertRaisesRegex(TraceValidationError, "unknown trace fields"):
            prepare_record(trace(forged=True))


if __name__ == "__main__":
    unittest.main()
