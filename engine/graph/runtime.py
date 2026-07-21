#!/usr/bin/env python3
"""Append-only event reducer and replay/checkpoint support for control graphs."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from .validate_graph import assert_valid_graph, read_graph
except ImportError:  # direct CLI execution from this directory
    from validate_graph import assert_valid_graph, read_graph

PLAN_OUTCOMES = {"SATISFEITO", "REPLANEJAR", "SABATINAR", "BLOQUEADO"}
EXECUTION_OUTCOMES = {"SATISFEITO", "CORRIGIR", "BLOQUEADO"}
HUMAN_OUTCOMES = {"DECIDIDO", "BLOQUEADO"}
PROOF_OUTCOMES = {"PASS", "FAIL", "BLOQUEADO"}
EVENT_TYPES = {
    "RUN_STARTED", "NODE_ENTERED", "REVIEW_RECORDED", "HUMAN_DECISION",
    "BUDGET_CONSUMED", "CHECKPOINT_SAVED", "RUN_COMPLETED", "RUN_BLOCKED",
}


class GraphError(ValueError):
    pass


def load_graph(path: Path | str | None = None) -> dict[str, Any]:
    graph = read_graph(Path(path) if path else Path(__file__).with_name("council.graph.yaml"))
    assert_valid_graph(graph)
    return graph


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def event_hash(event: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(event)).hexdigest()


def _validate_event_shape(event: dict[str, Any]) -> None:
    required = {"schema_version", "event_id", "run_id", "sequence", "type", "occurred_at", "payload"}
    missing = sorted(required - event.keys())
    if missing:
        raise GraphError(f"event missing fields: {', '.join(missing)}")
    extra = sorted(set(event) - required)
    if extra:
        raise GraphError(f"event has undeclared fields: {', '.join(extra)}")
    if event["schema_version"] != "1.0":
        raise GraphError("unsupported event schema_version")
    if event["type"] not in EVENT_TYPES:
        raise GraphError(f"unknown event type {event['type']!r}")
    if not isinstance(event["sequence"], int) or isinstance(event["sequence"], bool) or event["sequence"] < 1:
        raise GraphError("event sequence must be a positive integer")
    if not isinstance(event["payload"], dict):
        raise GraphError("event payload must be an object")
    for key in ("event_id", "run_id", "occurred_at"):
        if not isinstance(event[key], str) or not event[key]:
            raise GraphError(f"event {key} must be a non-empty string")
    try:
        occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        if occurred.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise GraphError("event occurred_at must be a valid timezone-aware RFC3339 timestamp") from exc


def initial_state(event: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    if event["type"] != "RUN_STARTED" or event["sequence"] != 1:
        raise GraphError("first event must be RUN_STARTED with sequence=1")
    requested = event["payload"].get("graph_id", graph["graph_id"])
    if requested != graph["graph_id"]:
        raise GraphError(f"run requests graph {requested!r}, loaded {graph['graph_id']!r}")
    return {
        "schema_version": "1.0",
        "run_id": event["run_id"],
        "graph_id": graph["graph_id"],
        "graph_version": graph["version"],
        "status": "RUNNING",
        "current_node": None,
        "sequence": 1,
        "visited": [],
        "reviews": {"plan": [], "execution": []},
        "budgets": {
            name: {"used": 1 if name == "total_events" else 0, "limit": limit}
            for name, limit in graph["budgets"].items()
        },
        "applied_event_ids": [event["event_id"]],
        "applied_event_hashes": {event["event_id"]: event_hash(event)},
        "pending_outcome": None,
    }


def find_transition(graph: dict[str, Any], source: str, target: str, outcome: str) -> dict[str, str]:
    matches = [item for item in graph["transitions"] if item == {"from": source, "to": target, "on": outcome}]
    if len(matches) != 1:
        raise GraphError(f"transition not allowed: {source} --{outcome}--> {target}")
    return matches[0]


def _consume_budget(state: dict[str, Any], name: str, amount: int = 1) -> None:
    if name not in state["budgets"]:
        raise GraphError(f"unknown budget {name!r}")
    record = state["budgets"][name]
    if amount < 1 or record["used"] + amount > record["limit"]:
        raise GraphError(f"budget {name!r} exhausted ({record['used']}/{record['limit']})")
    record["used"] += amount


def apply_event(state: dict[str, Any] | None, event: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Pure reducer: returns a copy, never mutates the supplied state."""
    _validate_event_shape(event)
    if state is None:
        return initial_state(event, graph)
    if event["run_id"] != state["run_id"]:
        raise GraphError("event run_id differs from checkpoint/run state")
    if event["event_id"] in state["applied_event_ids"]:
        if state.get("applied_event_hashes", {}).get(event["event_id"]) != event_hash(event):
            raise GraphError(f"event_id collision with different content: {event['event_id']}")
        return copy.deepcopy(state)  # at-least-once delivery is idempotent
    if state["status"] in {"COMPLETED", "BLOCKED"}:
        raise GraphError(f"cannot append to terminal run status={state['status']}")
    if event["sequence"] != state["sequence"] + 1:
        raise GraphError(f"sequence gap: expected {state['sequence'] + 1}, got {event['sequence']}")

    result = copy.deepcopy(state)
    payload = event["payload"]
    kind = event["type"]
    if kind == "RUN_STARTED":
        raise GraphError("RUN_STARTED may only be the first event")
    if kind == "NODE_ENTERED":
        target, outcome = payload.get("node_id"), payload.get("on")
        if not isinstance(target, str) or not isinstance(outcome, str):
            raise GraphError("NODE_ENTERED requires string node_id and on")
        if result["current_node"] is None:
            if target != graph["start"] or outcome != "START":
                raise GraphError(f"first node must be {graph['start']!r} with on=START")
        else:
            if result["pending_outcome"] is not None and outcome != result["pending_outcome"]:
                raise GraphError(f"transition outcome {outcome!r} differs from recorded review {result['pending_outcome']!r}")
            find_transition(graph, result["current_node"], target, outcome)
        result["current_node"] = target
        result["visited"].append(target)
        result["pending_outcome"] = None
        node = next(node for node in graph["nodes"] if node["id"] == target)
        result["status"] = "WAITING_HUMAN" if node["kind"] == "human" else "RUNNING"
    elif kind == "REVIEW_RECORDED":
        family, outcome = payload.get("family"), payload.get("outcome")
        node = next((node for node in graph["nodes"] if node["id"] == result["current_node"]), None)
        if not node or node.get("review_family") != family:
            raise GraphError(f"cannot record {family!r} review at node {result['current_node']!r}")
        allowed = PLAN_OUTCOMES if family == "plan" else EXECUTION_OUTCOMES if family == "execution" else set()
        if outcome not in allowed:
            raise GraphError(f"invalid {family} review outcome {outcome!r}")
        _consume_budget(result, result["current_node"])
        result["reviews"][family].append({"outcome": outcome, "event_id": event["event_id"]})
        result["pending_outcome"] = outcome
    elif kind == "HUMAN_DECISION":
        if result["current_node"] != "human_input":
            raise GraphError("HUMAN_DECISION is only valid at human_input")
        _consume_budget(result, "human_input")
        outcome = payload.get("outcome")
        if outcome not in HUMAN_OUTCOMES:
            raise GraphError("HUMAN_DECISION outcome must be DECIDIDO|BLOQUEADO")
        result["pending_outcome"] = outcome
        result["status"] = "RUNNING"
    elif kind == "BUDGET_CONSUMED":
        _consume_budget(result, payload.get("name"), payload.get("amount", 1))
    elif kind == "CHECKPOINT_SAVED":
        claimed = payload.get("state_hash")
        actual = state_hash(result)
        if claimed != actual:
            raise GraphError(f"checkpoint state_hash mismatch: expected {actual}, got {claimed}")
    elif kind == "RUN_COMPLETED":
        if result["current_node"] != "done":
            raise GraphError("RUN_COMPLETED requires current_node=done")
        result["status"] = "COMPLETED"
    elif kind == "RUN_BLOCKED":
        if result["current_node"] not in {"blocked", "pending"}:
            raise GraphError("RUN_BLOCKED requires current_node=blocked|pending")
        result["status"] = "BLOCKED"

    # Every non-duplicate event consumes the global event budget, except the
    # first event whose initial state already represents one consumed slot.
    total = result["budgets"].get("total_events")
    if total:
        if total["used"] + 1 > total["limit"]:
            raise GraphError("budget 'total_events' exhausted")
        total["used"] += 1
    result["sequence"] = event["sequence"]
    result["applied_event_ids"].append(event["event_id"])
    result["applied_event_hashes"][event["event_id"]] = event_hash(event)
    return result


def replay(events: Iterable[dict[str, Any]], graph: dict[str, Any], base_state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = copy.deepcopy(base_state)
    for event in events:
        state = apply_event(state, event, graph)
    if state is None:
        raise GraphError("cannot replay an empty event stream without a checkpoint")
    return state


def state_hash(state: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(state)).hexdigest()


def checkpoint(state: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "1.0", "sequence": state["sequence"], "state_hash": state_hash(state), "state": copy.deepcopy(state)}


def restore_checkpoint(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != "1.0" or not isinstance(value.get("state"), dict):
        raise GraphError("invalid checkpoint envelope")
    state = copy.deepcopy(value["state"])
    if value.get("sequence") != state.get("sequence") or value.get("state_hash") != state_hash(state):
        raise GraphError("checkpoint envelope failed integrity check")
    return state
