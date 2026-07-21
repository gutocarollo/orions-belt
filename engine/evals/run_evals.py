#!/usr/bin/env python3
"""Deterministic golden-trajectory evaluator for the control graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.graph.runtime import GraphError, load_graph, replay


class EvalFormatError(ValueError):
    pass


def validate_suite(suite: Any) -> None:
    if not isinstance(suite, dict) or suite.get("schema_version") != "1.0":
        raise EvalFormatError("suite must be an object with schema_version=1.0")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvalFormatError("suite.cases must be a non-empty array")
    ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise EvalFormatError(f"cases[{index}] requires string id")
        if case["id"] in ids:
            raise EvalFormatError(f"duplicate case id {case['id']!r}")
        ids.add(case["id"])
        if not isinstance(case.get("trajectory"), list) or not case["trajectory"]:
            raise EvalFormatError(f"case {case['id']}: trajectory must be non-empty")
        if not isinstance(case.get("expected"), dict):
            raise EvalFormatError(f"case {case['id']}: expected must be an object")


def materialize_events(case: dict[str, Any], graph_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, step in enumerate(case["trajectory"], 1):
        if not isinstance(step, dict) or not isinstance(step.get("type"), str):
            raise EvalFormatError(f"case {case['id']}: trajectory[{index - 1}] requires type")
        payload = step.get("payload", {})
        if index == 1 and step["type"] == "RUN_STARTED":
            payload = {"graph_id": graph_id, **payload}
        events.append({
            "schema_version": "1.0", "event_id": f"{case['id']}-{index}",
            "run_id": f"eval-{case['id']}", "sequence": index,
            "type": step["type"], "occurred_at": f"2026-01-01T00:00:{index:02d}Z",
            "payload": payload,
        })
    return events


def _transitions(visited: list[str]) -> set[tuple[str, str]]:
    return set(zip(visited, visited[1:]))


def evaluate(suite: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    validate_suite(suite)
    results: list[dict[str, Any]] = []
    covered: set[tuple[str, str]] = set()
    for case in suite["cases"]:
        errors: list[str] = []
        state: dict[str, Any] | None = None
        try:
            state = replay(materialize_events(case, graph["graph_id"]), graph)
            expected = case["expected"]
            for field in ("status", "current_node", "visited"):
                if field in expected and state[field] != expected[field]:
                    errors.append(f"{field}: expected {expected[field]!r}, got {state[field]!r}")
            for family, expected_field in (("plan", "plan_outcomes"), ("execution", "execution_outcomes")):
                actual = [item["outcome"] for item in state["reviews"][family]]
                if expected_field in expected and actual != expected[expected_field]:
                    errors.append(f"{expected_field}: expected {expected[expected_field]!r}, got {actual!r}")
            covered.update(_transitions(state["visited"]))
        except (GraphError, EvalFormatError, KeyError, TypeError) as exc:
            errors.append(str(exc))
        results.append({"id": case["id"], "passed": not errors, "errors": errors})
    graph_edges = {(item["from"], item["to"]) for item in graph["transitions"]}
    passed = sum(1 for item in results if item["passed"])
    return {
        "schema_version": "1.0", "passed": passed, "total": len(results),
        "failed": len(results) - passed,
        "transition_coverage": round(len(covered & graph_edges) / len(graph_edges), 6) if graph_edges else 1.0,
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", nargs="?", type=Path, default=Path(__file__).with_name("fixtures") / "golden_cases.json")
    parser.add_argument("--graph")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        suite = json.loads(args.suite.read_text(encoding="utf-8"))
        result = evaluate(suite, load_graph(args.graph))
    except (OSError, json.JSONDecodeError, EvalFormatError, ValueError) as exc:
        result = {"schema_version": "1.0", "passed": 0, "total": 0, "failed": 1, "transition_coverage": 0, "cases": [{"id": "suite", "passed": False, "errors": [str(exc)]}]}
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
