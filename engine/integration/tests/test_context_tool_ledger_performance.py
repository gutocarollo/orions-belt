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

SPEC = importlib.util.spec_from_file_location(
    "context_tool_ledger_perf",
    ROOT / "templates/.harness/hooks/context-tool-ledger.py",
)
LEDGER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = LEDGER
SPEC.loader.exec_module(LEDGER)


def payload(event: str, *, call_id: str = "call-1", response: object | None = None) -> dict:
    value = {
        "hook_event_name": event,
        "session_id": "session-1",
        "tool_use_id": call_id,
        "tool_name": "Read",
        "tool_input": {"file_path": "README.md"},
    }
    if response is not None:
        value["tool_response"] = response
    return value


class ContextToolLedgerPerformanceTest(unittest.TestCase):
    def test_no_active_council_run_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("x\n", encoding="utf-8")
            result = LEDGER.record_event(payload("PreToolUse"), "claude", root)
            self.assertIsNone(result)
            self.assertFalse((root / ".harness/runs/context-tools").exists())

    def test_active_council_run_appends_ordered_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("x\n", encoding="utf-8")
            state = root / ".harness/runs/agent-swarm/run-1/council-state.json"
            state.parent.mkdir(parents=True)
            state.write_text("{}\n", encoding="utf-8")
            pointer = root / ".harness/council-active"
            pointer.write_text(str(state) + "\n", encoding="utf-8")

            LEDGER.record_event(payload("PreToolUse"), "claude", root)
            path = LEDGER.record_event(
                payload("PostToolUse", response={"content": "x"}),
                "claude",
                root,
            )
            self.assertIsNotNone(path)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(rows))
            self.assertEqual(["run-1", "run-1"], [row["run_id"] for row in rows])
            self.assertLess(rows[0]["seq"], rows[1]["seq"])
            self.assertEqual(rows[0]["seq"], rows[0]["time_ns"])
            self.assertEqual(rows[1]["seq"], rows[1]["time_ns"])

    def test_ledger_does_not_rescan_jsonl_to_allocate_sequence(self):
        source = (ROOT / "templates/.harness/hooks/context-tool-ledger.py").read_text(encoding="utf-8")
        self.assertNotIn("existing = [json.loads", source)
        self.assertNotIn("stream.seek(0)\n", source)
        self.assertIn('"seq": now_ns', source)


if __name__ == "__main__":
    unittest.main()
