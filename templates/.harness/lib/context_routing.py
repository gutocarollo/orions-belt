#!/usr/bin/env python3
"""Deterministic routing for Context Delivery.

The model classifies the task once. This module converts that classification
into an auditable tool topology. It deliberately separates lexical discovery
from dependency reachability and only parallelizes methods whose inputs are
independent.
"""
from __future__ import annotations

import argparse
import json
import uuid
from typing import Any

TASK_SHAPES = {
    "LEXICAL_ENUMERATION",
    "KNOWN_SYMBOL_IMPACT",
    "DYNAMIC_STATE_FLOW",
    "DOCS_OR_CONFIG",
    "LIVE_STATE",
    "DIRECT_TARGETED",
}
RISK_TIERS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
KNOWN_METHODS = {
    "canonical-docs",
    "rg",
    "targeted-read",
    "codegraph",
    "lsp",
    "live-state",
}


class RoutingError(ValueError):
    """Raised when a task classification cannot produce a safe route."""


def _append(methods: list[str], stages: dict[str, int], method: str, stage: int) -> None:
    if method not in methods:
        methods.append(method)
    stages[method] = max(stage, stages.get(method, stage))


def _edge(edges: list[dict[str, str]], before: str, after: str) -> None:
    item = {"before": before, "after": after}
    if before != after and item not in edges:
        edges.append(item)


def route_context(
    *,
    task_shape: str,
    risk_tier: str = "MEDIUM",
    codegraph_available: bool = False,
    lsp_available: bool = False,
    live_state_available: bool = False,
    symbol_ambiguous: bool = False,
    claims_completeness: bool = False,
    include_canonical_docs: bool = True,
    parallel_shards: list[str] | None = None,
    allowed_agent_types: list[str] | None = None,
    allowed_models: list[str] | None = None,
    plan_id: str | None = None,
) -> dict[str, Any]:
    task_shape = task_shape.upper().strip()
    risk_tier = risk_tier.upper().strip()
    if task_shape not in TASK_SHAPES:
        raise RoutingError(f"unsupported task_shape: {task_shape}")
    if risk_tier not in RISK_TIERS:
        raise RoutingError(f"unsupported risk_tier: {risk_tier}")

    methods: list[str] = []
    stages: dict[str, int] = {}
    edges: list[dict[str, str]] = []
    parallel_groups: list[list[str]] = []

    if include_canonical_docs:
        _append(methods, stages, "canonical-docs", 0)

    high_radius = risk_tier in {"HIGH", "CRITICAL"} or claims_completeness
    code_stage = 1 if include_canonical_docs else 0

    if task_shape == "LEXICAL_ENUMERATION":
        # The graph has no useful query target until lexical discovery has
        # produced concrete components/symbols.
        _append(methods, stages, "rg", code_stage)
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "rg", "targeted-read")
        if codegraph_available:
            _append(methods, stages, "codegraph", code_stage + 2)
            _edge(edges, "targeted-read", "codegraph")
        elif lsp_available:
            _append(methods, stages, "lsp", code_stage + 2)
            _edge(edges, "targeted-read", "lsp")

    elif task_shape == "KNOWN_SYMBOL_IMPACT":
        if codegraph_available and high_radius:
            _append(methods, stages, "codegraph", code_stage)
            _append(methods, stages, "rg", code_stage)
            parallel_groups.append(["codegraph", "rg"])
            _append(methods, stages, "targeted-read", code_stage + 1)
            _edge(edges, "codegraph", "targeted-read")
            _edge(edges, "rg", "targeted-read")
        elif codegraph_available:
            _append(methods, stages, "codegraph", code_stage)
            _append(methods, stages, "targeted-read", code_stage + 1)
            _edge(edges, "codegraph", "targeted-read")
        else:
            _append(methods, stages, "rg", code_stage)
            _append(methods, stages, "targeted-read", code_stage + 1)
            _edge(edges, "rg", "targeted-read")
        if lsp_available and (symbol_ambiguous or not codegraph_available):
            _append(methods, stages, "lsp", code_stage + 2)
            _edge(edges, "targeted-read", "lsp")

    elif task_shape == "DYNAMIC_STATE_FLOW":
        # Click -> setState -> conditional class is local data/control flow;
        # import/call graphs become useful only after that local path is proven.
        _append(methods, stages, "rg", code_stage)
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "rg", "targeted-read")
        local_tail = "targeted-read"
        if lsp_available:
            _append(methods, stages, "lsp", code_stage + 2)
            _edge(edges, "targeted-read", "lsp")
            local_tail = "lsp"
        if codegraph_available:
            _append(methods, stages, "codegraph", code_stage + 3)
            _edge(edges, local_tail, "codegraph")

    elif task_shape == "DOCS_OR_CONFIG":
        _append(methods, stages, "rg", code_stage)
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "rg", "targeted-read")
        if include_canonical_docs:
            _edge(edges, "canonical-docs", "targeted-read")

    elif task_shape == "LIVE_STATE":
        if not live_state_available:
            raise RoutingError("LIVE_STATE requires a configured read-only live-state tool")
        _append(methods, stages, "live-state", code_stage)
        _append(methods, stages, "rg", code_stage)
        parallel_groups.append(["live-state", "rg"])
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "live-state", "targeted-read")
        _edge(edges, "rg", "targeted-read")
        if codegraph_available:
            _append(methods, stages, "codegraph", code_stage + 2)
            _edge(edges, "targeted-read", "codegraph")
        elif lsp_available:
            _append(methods, stages, "lsp", code_stage + 2)
            _edge(edges, "targeted-read", "lsp")

    else:  # DIRECT_TARGETED
        _append(methods, stages, "rg", code_stage)
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "rg", "targeted-read")

    if include_canonical_docs and task_shape != "DOCS_OR_CONFIG":
        first_code_methods = [
            method for method in methods
            if method != "canonical-docs" and stages[method] == code_stage
        ]
        for method in first_code_methods:
            _edge(edges, "canonical-docs", method)
    elif include_canonical_docs and task_shape == "DOCS_OR_CONFIG":
        _edge(edges, "canonical-docs", "rg")

    if not methods:
        raise RoutingError("route produced no methods")
    unknown = set(methods) - KNOWN_METHODS
    if unknown:
        raise RoutingError(f"route produced unknown methods: {sorted(unknown)}")

    shards = [value.strip() for value in (parallel_shards or []) if value.strip()]
    if len(shards) != len(set(shards)):
        raise RoutingError("parallel shard scopes must be unique")

    plan = {
        "status": "PRONTO",
        "skill": "context-delivery",
        "plan_id": plan_id or str(uuid.uuid4()),
        "task_shape": task_shape,
        "risk_tier": risk_tier,
        "claims_completeness": bool(claims_completeness),
        "required_methods": methods,
        "method_stages": [{"method": method, "stage": stages[method]} for method in methods],
        "dependency_edges": edges,
        "parallel_groups": parallel_groups,
        "parallel_shards": shards,
        "allowed_agent_types": allowed_agent_types or [],
        "allowed_models": allowed_models or [],
    }
    validate_route(plan)
    return plan


def validate_route(plan: dict[str, Any]) -> None:
    methods = plan.get("required_methods", [])
    if not isinstance(methods, list) or not methods or len(methods) != len(set(methods)):
        raise RoutingError("required_methods must be a non-empty unique list")
    stages = {item["method"]: item["stage"] for item in plan.get("method_stages", [])}
    if set(stages) != set(methods):
        raise RoutingError("method_stages must cover every required method exactly once")
    for method, stage in stages.items():
        if method not in KNOWN_METHODS or not isinstance(stage, int) or stage < 0:
            raise RoutingError(f"invalid method stage: {method}={stage!r}")
    for edge in plan.get("dependency_edges", []):
        before, after = edge.get("before"), edge.get("after")
        if before not in stages or after not in stages:
            raise RoutingError(f"dependency references unknown method: {edge}")
        if stages[before] >= stages[after]:
            raise RoutingError(f"dependency order violated: {before} -> {after}")
    for group in plan.get("parallel_groups", []):
        if len(group) < 2 or any(method not in stages for method in group):
            raise RoutingError(f"invalid parallel group: {group}")
        if len({stages[method] for method in group}) != 1:
            raise RoutingError(f"parallel group methods must share a stage: {group}")
        for edge in plan.get("dependency_edges", []):
            if edge["before"] in group and edge["after"] in group:
                raise RoutingError(f"dependent methods cannot be parallel: {group}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", help="JSON object; stdin when omitted")
    args = parser.parse_args()
    raw = args.input_json if args.input_json is not None else input()
    request = json.loads(raw)
    print(json.dumps(route_context(**request), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
