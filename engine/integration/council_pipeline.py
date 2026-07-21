#!/usr/bin/env python3
"""Canonical Council ledger → Control Graph → trace → evidence adapter.

The Council ledger remains the input journal. This module deterministically
expands its domain events into the finer-grained Control Graph event stream;
all downstream trace and evidence artifacts are derived from those two
immutable inputs, never maintained as parallel hand-authored state.
"""

from __future__ import annotations

import hashlib
import json
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.contract.scripts.mini_schema_validate import validate_instance
from engine.evidence.manifest import assert_valid_manifest, canonical_hash
from engine.graph.runtime import EXECUTION_OUTCOMES, HUMAN_OUTCOMES, PLAN_OUTCOMES, PROOF_OUTCOMES, apply_event, load_graph, replay
from engine.observability.tracing import prepare_record

_LEDGER_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "contract" / "schemas" / "ledger-event.schema.json").read_text(encoding="utf-8"))
_STATUS = {
    ("planning", "review"): PLAN_OUTCOMES,
    ("execution", "review"): EXECUTION_OUTCOMES,
    ("planning", "validation"): HUMAN_OUTCOMES,
    ("execution", "validation"): PROOF_OUTCOMES,
}


class IntegrationError(ValueError):
    pass


def _timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise IntegrationError("ledger ts must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise IntegrationError(f"ledger ts is not timezone-aware RFC3339: {value!r}") from exc


def validate_ledger(entries: list[dict[str, Any]]) -> None:
    if not entries:
        raise IntegrationError("ledger is empty")
    run_id = entries[0].get("run_id")
    previous_round = 0
    for index, entry in enumerate(entries, 1):
        errors = validate_instance(entry, _LEDGER_SCHEMA)
        if errors:
            raise IntegrationError(f"ledger[{index}]: {'; '.join(errors)}")
        _timestamp(entry["ts"])
        if entry["seq"] != index:
            raise IntegrationError(f"ledger[{index}]: expected seq={index}, got {entry['seq']}")
        if entry["run_id"] != run_id:
            raise IntegrationError(f"ledger[{index}]: run_id changed")
        if entry["round"] < previous_round:
            raise IntegrationError(f"ledger[{index}]: round regressed")
        previous_round = entry["round"]
        allowed = _STATUS.get((entry["loop"], entry["event"]))
        if allowed is not None and entry["status"] not in allowed:
            raise IntegrationError(f"ledger[{index}]: invalid status {entry['status']!r}")
        if entry["event"] in {"replan-consumed", "fix-consumed"}:
            parent_seq = entry.get("parent_seq")
            expected = "replan-request" if entry["event"] == "replan-consumed" else "fix-request"
            if not isinstance(parent_seq, int) or parent_seq >= index or entries[parent_seq - 1]["event"] != expected:
                raise IntegrationError(f"ledger[{index}]: invalid parent for {entry['event']}")


class _Expansion:
    def __init__(self, run_id: str, graph: dict[str, Any]) -> None:
        self.run_id = run_id
        self.graph = graph
        self.events: list[dict[str, Any]] = []
        self.state: dict[str, Any] | None = None

    def emit(self, kind: str, ts: str, payload: dict[str, Any] | None = None) -> None:
        sequence = len(self.events) + 1
        event = {
            "schema_version": "1.0", "event_id": f"{self.run_id}-control-{sequence}",
            "run_id": self.run_id, "sequence": sequence, "type": kind,
            "occurred_at": ts, "payload": payload or {},
        }
        self.state = apply_event(self.state, event, self.graph)
        self.events.append(event)

    def start_for(self, loop: str, ts: str) -> None:
        if self.state is not None:
            return
        self.emit("RUN_STARTED", ts, {"graph_id": self.graph["graph_id"]})
        self.emit("NODE_ENTERED", ts, {"node_id": "context", "on": "START"})
        self.emit("NODE_ENTERED", ts, {"node_id": "risk_router", "on": "READY"})
        target, outcome = ("plan", "PLAN") if loop == "planning" else ("execute", "EXECUTE")
        self.emit("NODE_ENTERED", ts, {"node_id": target, "on": outcome})

    def map_entry(self, entry: dict[str, Any]) -> None:
        ts, loop, event, status = entry["ts"], entry["loop"], entry["event"], entry["status"]
        self.start_for(loop, ts)
        assert self.state is not None
        node = self.state["current_node"]
        if loop == "planning" and event == "review":
            if node == "plan":
                self.emit("NODE_ENTERED", ts, {"node_id": "plan_review", "on": "READY"})
            if self.state["current_node"] != "plan_review":
                raise IntegrationError(f"planning review cannot occur at {self.state['current_node']!r}")
            self.emit("REVIEW_RECORDED", ts, {"family": "plan", "outcome": status})
            target = {"SATISFEITO": "execute", "REPLANEJAR": "plan", "SABATINAR": "human_input", "BLOQUEADO": "blocked"}[status]
            self.emit("NODE_ENTERED", ts, {"node_id": target, "on": status})
        elif loop == "planning" and event == "validation":
            if self.state["current_node"] != "human_input":
                raise IntegrationError("planning validation is the human decision and requires human_input")
            self.emit("HUMAN_DECISION", ts, {"outcome": status})
            target = "plan_review" if status == "DECIDIDO" else "blocked"
            self.emit("NODE_ENTERED", ts, {"node_id": target, "on": status})
        elif loop == "execution" and event == "review":
            if node == "execute":
                self.emit("NODE_ENTERED", ts, {"node_id": "execution_review", "on": "READY"})
            if self.state["current_node"] != "execution_review":
                raise IntegrationError(f"execution review cannot occur at {self.state['current_node']!r}")
            self.emit("REVIEW_RECORDED", ts, {"family": "execution", "outcome": status})
            target = {"SATISFEITO": "proof", "CORRIGIR": "execute", "BLOQUEADO": "blocked"}[status]
            self.emit("NODE_ENTERED", ts, {"node_id": target, "on": status})
        elif loop == "execution" and event in {"validation", "final"} and status in PROOF_OUTCOMES:
            if self.state["current_node"] != "proof":
                raise IntegrationError(f"proof result cannot occur at {self.state['current_node']!r}")
            target = {"PASS": "done", "FAIL": "execute", "BLOQUEADO": "blocked"}[status]
            self.emit("NODE_ENTERED", ts, {"node_id": target, "on": status})
            if status == "PASS":
                self.emit("RUN_COMPLETED", ts)
            elif status == "BLOQUEADO":
                self.emit("RUN_BLOCKED", ts)
        # request/consumed handoffs and non-proof final events carry provenance
        # but intentionally do not invent Control Graph transitions.


def _trace_for(entry: dict[str, Any], current_node: str | None) -> list[dict[str, Any]]:
    common = {
        "schema_version": "1.0", "trace_id": f"trace-{entry['run_id']}", "run_id": entry["run_id"],
        "node_id": current_node, "agent_id": str(entry["payload"].get("agent_id", "council")),
        "name": f"council.{entry['loop']}.{entry['event']}", "timestamp": entry["ts"],
        "attributes": {"ledger_seq": entry["seq"], "round": entry["round"], "status": entry["status"]},
    }
    span = f"ledger-{entry['seq']}"
    return [
        prepare_record({**common, "span_id": span, "parent_span_id": None, "kind": "SPAN_START"}),
        prepare_record({**common, "span_id": span + "-end", "parent_span_id": span, "kind": "SPAN_END"}),
    ]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_evidence(entries: list[dict[str, Any]], control_events: list[dict[str, Any]], traces: list[dict[str, Any]], state: dict[str, Any], git_sha: str) -> dict[str, Any]:
    timestamp = entries[-1]["ts"]
    manifest = {
        "schema_version": "1.0", "report_id": f"proof-{state['run_id']}", "title": "Council control-graph proof",
        "git_sha": git_sha, "recorded_at": timestamp, "valid_at": timestamp,
        "agents": [
            {"id": "agent:council", "type": "software", "name": "Council ledger adapter"},
            {"id": "agent:control-runtime", "type": "software", "name": "Control Graph deterministic reducer"},
        ],
        "activities": [
            {"id": "activity:ledger-expand", "type": "transform", "agent_id": "agent:council", "started_at": entries[0]["ts"], "ended_at": timestamp,
             "used": ["entity:ledger"], "generated": ["entity:control-events", "entity:traces"]},
            {"id": "activity:replay", "type": "transform", "agent_id": "agent:control-runtime", "started_at": timestamp, "ended_at": timestamp,
             "used": ["entity:control-events"], "generated": ["entity:run-state"]},
        ],
        "entities": [
            {"id": "entity:ledger", "type": "source", "uri": f"urn:orions-belt:ledger:{state['run_id']}", "sha256": _digest(entries), "media_type": "application/x-ndjson", "trust": "validated", "recorded_at": timestamp},
            {"id": "entity:control-events", "type": "log", "uri": f"urn:orions-belt:control:{state['run_id']}", "sha256": _digest(control_events), "media_type": "application/x-ndjson", "trust": "validated", "recorded_at": timestamp},
            {"id": "entity:traces", "type": "log", "uri": f"urn:orions-belt:traces:{state['run_id']}", "sha256": _digest(traces), "media_type": "application/x-ndjson", "trust": "validated", "recorded_at": timestamp},
            {"id": "entity:run-state", "type": "test-result", "uri": f"urn:orions-belt:state:{state['run_id']}", "sha256": canonical_hash(state), "media_type": "application/json", "trust": "validated", "recorded_at": timestamp},
        ],
        "claims": [{
            "id": "claim:proof-pass", "statement": "Council trajectory replay reached a completed proof state.",
            "status": "PASS" if state["status"] == "COMPLETED" and state["current_node"] == "done" else "FAIL",
            "recorded_at": timestamp, "valid_at": timestamp,
            "activities": ["activity:ledger-expand", "activity:replay"],
            "entities": ["entity:ledger", "entity:control-events", "entity:traces", "entity:run-state"],
        }],
    }
    assert_valid_manifest(manifest)
    return manifest


def integrate_ledger(entries: list[dict[str, Any]], git_sha: str) -> dict[str, Any]:
    validate_ledger(entries)
    graph = load_graph()
    expansion = _Expansion(entries[0]["run_id"], graph)
    traces: list[dict[str, Any]] = []
    for entry in entries:
        expansion.map_entry(entry)
        assert expansion.state is not None
        traces.extend(_trace_for(entry, expansion.state["current_node"]))
    assert expansion.state is not None
    replayed = replay(expansion.events, graph)
    if replayed != expansion.state:
        raise IntegrationError("incremental reduction differs from clean replay")
    evidence = build_evidence(entries, expansion.events, traces, replayed, git_sha)
    return {"control_events": expansion.events, "state": replayed, "traces": traces, "evidence": evidence}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise IntegrationError(f"{path}:{number}: expected JSON object")
        entries.append(value)
    return entries


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize Control Graph, traces and evidence from a Council loop ledger")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = integrate_ledger(_read_jsonl(args.ledger), args.git_sha)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(args.output_dir / "control-events.json", result["control_events"])
        _write_json(args.output_dir / "run-state.json", result["state"])
        _write_json(args.output_dir / "traces.json", result["traces"])
        _write_json(args.output_dir / "evidence-manifest.json", result["evidence"])
    except (OSError, json.JSONDecodeError, IntegrationError, ValueError) as exc:
        print(f"council-pipeline: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["state"]["status"], "current_node": result["state"]["current_node"], "output_dir": str(args.output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
