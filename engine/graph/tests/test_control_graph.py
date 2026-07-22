from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from engine.graph.runtime import GraphError, apply_event, checkpoint, load_graph, replay, restore_checkpoint
from engine.graph.event_log import append_event, read_events
from engine.graph.validate_graph import validate_graph


ROOT = Path(__file__).resolve().parents[3]


def event(sequence: int, kind: str, payload: dict | None = None, event_id: str | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "event_id": event_id or f"evt-{sequence}",
        "run_id": "run-1",
        "sequence": sequence,
        "type": kind,
        "occurred_at": f"2026-07-21T00:00:{sequence:02d}Z",
        "payload": payload or {},
    }


def happy_events() -> list[dict]:
    return [
        event(1, "RUN_STARTED", {"graph_id": "orions-belt-council"}),
        event(2, "NODE_ENTERED", {"node_id": "context", "on": "START"}),
        event(3, "NODE_ENTERED", {"node_id": "risk_router", "on": "READY"}),
        event(4, "NODE_ENTERED", {"node_id": "plan", "on": "PLAN"}),
        event(5, "NODE_ENTERED", {"node_id": "plan_review", "on": "READY"}),
        event(6, "REVIEW_RECORDED", {"family": "plan", "outcome": "SATISFEITO"}),
        event(7, "NODE_ENTERED", {"node_id": "execute", "on": "SATISFEITO"}),
        event(8, "NODE_ENTERED", {"node_id": "execution_review", "on": "READY"}),
        event(9, "REVIEW_RECORDED", {"family": "execution", "outcome": "SATISFEITO"}),
        event(10, "NODE_ENTERED", {"node_id": "proof", "on": "SATISFEITO"}),
        event(11, "NODE_ENTERED", {"node_id": "done", "on": "PASS"}),
        event(12, "RUN_COMPLETED"),
    ]


class ControlGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = load_graph()

    def test_canonical_graph_is_valid_and_reachable(self) -> None:
        self.assertEqual([], validate_graph(self.graph))
        self.assertEqual("context", self.graph["start"])
        self.assertEqual({"done", "blocked", "pending"}, set(self.graph["terminal"]))

    def test_validator_rejects_ambiguous_and_unreachable_graph(self) -> None:
        broken = copy.deepcopy(self.graph)
        broken["nodes"].append({"id": "orphan", "kind": "action"})
        broken["transitions"].append(copy.deepcopy(broken["transitions"][0]))
        errors = validate_graph(broken)
        self.assertTrue(any("ambiguous transition" in item for item in errors))
        self.assertTrue(any("unreachable nodes: orphan" in item for item in errors))

    def test_validator_enforces_schema_version_and_additional_properties(self) -> None:
        broken = copy.deepcopy(self.graph)
        broken["schema_version"] = "999"
        broken["forged"] = True
        broken["nodes"][0]["forged"] = True
        errors = validate_graph(broken)
        self.assertTrue(any("schema_version" in item for item in errors))
        self.assertTrue(any("undeclared root fields: forged" in item for item in errors))
        self.assertTrue(any("node context: undeclared fields: forged" in item for item in errors))

    def test_happy_path_replays_deterministically(self) -> None:
        first = replay(happy_events(), self.graph)
        second = replay(happy_events(), self.graph)
        self.assertEqual(first, second)
        self.assertEqual("COMPLETED", first["status"])
        self.assertEqual("done", first["current_node"])
        self.assertEqual(12, first["budgets"]["total_events"]["used"])

    def test_plan_review_supports_sabatinar_and_human_resume(self) -> None:
        events = happy_events()[:5] + [
            event(6, "REVIEW_RECORDED", {"family": "plan", "outcome": "SABATINAR"}),
            event(7, "NODE_ENTERED", {"node_id": "human_input", "on": "SABATINAR"}),
            event(8, "HUMAN_DECISION", {"outcome": "DECIDIDO"}),
            event(9, "NODE_ENTERED", {"node_id": "plan_review", "on": "DECIDIDO"}),
        ]
        state = replay(events, self.graph)
        self.assertEqual("plan_review", state["current_node"])
        self.assertEqual(1, state["budgets"]["plan_review"]["used"])
        self.assertEqual(1, state["budgets"]["human_input"]["used"])

    def test_execution_review_supports_corrigir(self) -> None:
        events = happy_events()[:8] + [
            event(9, "REVIEW_RECORDED", {"family": "execution", "outcome": "CORRIGIR"}),
            event(10, "NODE_ENTERED", {"node_id": "execute", "on": "CORRIGIR"}),
        ]
        state = replay(events, self.graph)
        self.assertEqual("execute", state["current_node"])
        self.assertEqual(1, state["budgets"]["execution_review"]["used"])

    def test_recorded_review_must_match_transition(self) -> None:
        state = replay(happy_events()[:6], self.graph)
        with self.assertRaisesRegex(GraphError, "differs from recorded review"):
            apply_event(state, event(7, "NODE_ENTERED", {"node_id": "plan", "on": "REPLANEJAR"}), self.graph)

    def test_budget_is_enforced(self) -> None:
        state = replay(happy_events()[:5], self.graph)
        state["budgets"]["plan_review"] = {"used": 2, "limit": 2}
        with self.assertRaisesRegex(GraphError, "exhausted"):
            apply_event(state, event(6, "REVIEW_RECORDED", {"family": "plan", "outcome": "REPLANEJAR"}), self.graph)

    def test_budget_exhausted_transition_is_reachable_via_direct_node_entered(self) -> None:
        # council.graph.yaml declares plan_review/execution_review --BUDGET_EXHAUSTED--> pending.
        # It is NOT reached through REVIEW_RECORDED (that event's outcome enum only has real
        # review verdicts: SATISFEITO/REPLANEJAR/SABATINAR/BLOQUEADO — BUDGET_EXHAUSTED would fail that
        # check, and _consume_budget always raises rather than returning a value). It is a
        # PROACTIVE, orchestrator-initiated stop: the caller checks the budget itself BEFORE
        # attempting one more review round and, if exhausted, emits NODE_ENTERED directly
        # (bypassing REVIEW_RECORDED) — find_transition matches purely against the declared
        # transitions table, independent of the review-outcome enum. RUN_BLOCKED is the
        # required follow-up to close the run status (it requires
        # current_node in {blocked, pending}).
        state = replay(happy_events()[:5], self.graph)
        state["budgets"]["plan_review"] = {"used": 2, "limit": 2}
        state = apply_event(state, event(6, "NODE_ENTERED", {"node_id": "pending", "on": "BUDGET_EXHAUSTED"}), self.graph)
        self.assertEqual(state["current_node"], "pending")
        state = apply_event(state, event(7, "RUN_BLOCKED", {}), self.graph)
        self.assertEqual(state["status"], "BLOCKED")

    def test_duplicate_event_id_is_idempotent(self) -> None:
        state = replay(happy_events()[:2], self.graph)
        duplicate = copy.deepcopy(happy_events()[1])
        self.assertEqual(state, apply_event(state, duplicate, self.graph))
        collision = copy.deepcopy(duplicate)
        collision["payload"]["on"] = "DIFFERENT"
        with self.assertRaisesRegex(GraphError, "event_id collision"):
            apply_event(state, collision, self.graph)

    def test_event_log_validates_append_and_deduplicates_redelivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.jsonl"
            for item in happy_events()[:3]:
                append_event(path, item, self.graph)
            append_event(path, happy_events()[2], self.graph)
            self.assertEqual(3, len(read_events(path)))
            self.assertEqual("risk_router", replay(read_events(path), self.graph)["current_node"])

    def test_sequence_gap_is_rejected(self) -> None:
        state = replay(happy_events()[:2], self.graph)
        with self.assertRaisesRegex(GraphError, "sequence gap"):
            apply_event(state, event(4, "NODE_ENTERED", {"node_id": "risk_router", "on": "READY"}), self.graph)

    def test_checkpoint_integrity_and_resume_match_clean_replay(self) -> None:
        events = happy_events()
        partial = replay(events[:7], self.graph)
        envelope = checkpoint(partial)
        restored = restore_checkpoint(envelope)
        resumed = replay(events[7:], self.graph, restored)
        self.assertEqual(replay(events, self.graph), resumed)
        tampered = copy.deepcopy(envelope)
        tampered["state"]["status"] = "COMPLETED"
        with self.assertRaisesRegex(GraphError, "integrity"):
            restore_checkpoint(tampered)

    def test_cli_replay_and_transition(self) -> None:
        transition = subprocess.run(
            ["python3", "engine/graph/validate_transition.py", "plan_review", "human_input", "SABATINAR"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(0, transition.returncode, transition.stdout + transition.stderr)
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "events.jsonl"
            log.write_text("\n".join(json.dumps(item) for item in happy_events()) + "\n", encoding="utf-8")
            proc = subprocess.run(
                ["python3", "engine/graph/replay_run.py", str(log)], cwd=ROOT, capture_output=True, text=True,
            )
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual("COMPLETED", json.loads(proc.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
