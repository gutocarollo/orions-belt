#!/usr/bin/env python3
"""Validate a control graph structurally, without third-party packages."""

from __future__ import annotations

import argparse
import json
import re
from collections import deque
from pathlib import Path
from typing import Any


class GraphValidationError(ValueError):
    pass


NODE_KINDS = {"action", "router", "review", "human", "proof", "terminal"}
REVIEW_FAMILIES = {"plan", "execution"}


def read_graph(path: Path) -> dict[str, Any]:
    """Read JSON-compatible YAML. JSON is deliberately the supported subset."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphValidationError(f"cannot read graph {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GraphValidationError("graph root must be an object")
    return value


def validate_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"schema_version", "graph_id", "version", "start", "terminal", "nodes", "transitions", "budgets"}
    extra = sorted(set(graph) - required)
    if extra:
        errors.append(f"undeclared root fields: {', '.join(extra)}")
    missing = sorted(required - graph.keys())
    if missing:
        errors.append(f"missing root fields: {', '.join(missing)}")
    if graph.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    if not isinstance(graph.get("graph_id"), str) or not re.fullmatch(r"[a-z][a-z0-9-]*", graph["graph_id"]):
        errors.append("graph_id does not match ^[a-z][a-z0-9-]*$")
    if isinstance(graph.get("version"), bool) or not isinstance(graph.get("version"), int) or graph["version"] < 1:
        errors.append("version must be a positive integer")

    nodes_value = graph.get("nodes", [])
    if not isinstance(nodes_value, list):
        return errors + ["nodes must be an array"]
    if not nodes_value:
        errors.append("nodes must contain at least one item")
    node_ids: list[str] = []
    node_by_id: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes_value):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            errors.append(f"nodes[{index}] must have a string id")
            continue
        node_id = node["id"]
        node_extra = sorted(set(node) - {"id", "kind", "review_family"})
        if node_extra:
            errors.append(f"node {node_id}: undeclared fields: {', '.join(node_extra)}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", node_id):
            errors.append(f"node {node_id!r}: id does not match ^[a-z][a-z0-9_]*$")
        node_ids.append(node_id)
        node_by_id[node_id] = node
        if node.get("kind") not in NODE_KINDS:
            errors.append(f"node {node_id}: invalid kind {node.get('kind')!r}")
        if "review_family" in node and node.get("review_family") not in REVIEW_FAMILIES:
            errors.append(f"node {node_id}: invalid review_family {node.get('review_family')!r}")
        if node.get("kind") == "review" and node.get("review_family") not in REVIEW_FAMILIES:
            errors.append(f"node {node_id}: review node requires plan|execution review_family")
    duplicates = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    if duplicates:
        errors.append(f"duplicate node ids: {', '.join(duplicates)}")
    known = set(node_ids)

    start = graph.get("start")
    if start not in known:
        errors.append(f"start node {start!r} does not exist")
    terminals_value = graph.get("terminal", [])
    if not isinstance(terminals_value, list):
        errors.append("terminal must be an array")
        terminals = set()
    else:
        terminals = set(item for item in terminals_value if isinstance(item, str))
        if len(terminals) != len(terminals_value):
            errors.append("terminal entries must be unique strings")
    if not terminals:
        errors.append("terminal must contain at least one node")
    for terminal in sorted(terminals):
        if terminal not in known:
            errors.append(f"terminal node {terminal!r} does not exist")
        elif node_by_id[terminal].get("kind") != "terminal":
            errors.append(f"terminal node {terminal!r} must have kind=terminal")

    transitions = graph.get("transitions", [])
    if not isinstance(transitions, list):
        return errors + ["transitions must be an array"]
    if not transitions:
        errors.append("transitions must contain at least one item")
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in known}
    keys: set[tuple[str, str]] = set()
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            errors.append(f"transitions[{index}] must be an object")
            continue
        transition_extra = sorted(set(transition) - {"from", "to", "on"})
        if transition_extra:
            errors.append(f"transitions[{index}]: undeclared fields: {', '.join(transition_extra)}")
        source, target, outcome = transition.get("from"), transition.get("to"), transition.get("on")
        if source not in known:
            errors.append(f"transitions[{index}]: unknown from={source!r}")
        if target not in known:
            errors.append(f"transitions[{index}]: unknown to={target!r}")
        if not isinstance(outcome, str) or not outcome:
            errors.append(f"transitions[{index}]: on must be a non-empty string")
        if isinstance(source, str) and isinstance(outcome, str):
            key = (source, outcome)
            if key in keys:
                errors.append(f"ambiguous transition from={source!r} on={outcome!r}")
            keys.add(key)
        if source in known and target in known:
            outgoing[source].append(target)

    for node_id in sorted(known - terminals):
        if not outgoing[node_id]:
            errors.append(f"non-terminal node {node_id!r} has no outgoing transition")
    for terminal in sorted(terminals):
        if outgoing.get(terminal):
            errors.append(f"terminal node {terminal!r} has outgoing transitions")

    reachable: set[str] = set()
    if start in known:
        queue: deque[str] = deque([start])
        while queue:
            node_id = queue.popleft()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            queue.extend(outgoing[node_id])
        unreachable = sorted(known - reachable)
        if unreachable:
            errors.append(f"unreachable nodes: {', '.join(unreachable)}")

    budgets = graph.get("budgets", {})
    if not isinstance(budgets, dict):
        errors.append("budgets must be an object")
    else:
        allowed_budget_keys = known | {"total_events"}
        for name, limit in budgets.items():
            if name not in allowed_budget_keys:
                errors.append(f"budget {name!r} does not name a node or total_events")
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                errors.append(f"budget {name!r} must be a positive integer")
    return errors


def assert_valid_graph(graph: dict[str, Any]) -> None:
    errors = validate_graph(graph)
    if errors:
        raise GraphValidationError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", nargs="?", type=Path, default=Path(__file__).with_name("council.graph.yaml"))
    args = parser.parse_args()
    try:
        graph = read_graph(args.graph)
        assert_valid_graph(graph)
    except GraphValidationError as exc:
        print(f"INVALID: {exc}")
        return 2
    print(f"VALID: {graph['graph_id']} v{graph['version']} ({len(graph['nodes'])} nodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
