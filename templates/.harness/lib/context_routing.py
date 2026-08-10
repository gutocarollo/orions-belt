#!/usr/bin/env python3
"""Deterministic adaptive routing for Context Delivery.

The LLM classifies only the task shape. Repository risk predicates P1-P3 are
computed from Git, P4/P5 are resolved from runtime receipts, and P6 is derived
from the task shape. Parallelism is emitted only for independent inputs.
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from context_predicates import evaluate_repository_predicates

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
    "codegraph-status",
    "codegraph",
    "lsp",
    "live-state",
}
DEFAULT_TOOL_MATCHERS = {
    "canonical-docs": ["Read(docs/**)", "read_file(docs/**)"],
    "rg": ["Grep", "Glob", "Bash(^|\\s)rg(\\s|$)"],
    "targeted-read": ["Read", "read_file"],
    "codegraph-status": ["mcp__codegraph__.*status.*", "Bash(^|\\s)codegraph\\s+status(\\s|$)"],
    "codegraph": ["mcp__codegraph__.*", "Bash(^|\\s)codegraph(\\s|$)"],
    "lsp": ["mcp__serena__.*", ".*lsp.*"],
    "live-state": ["mcp__.*(postgres|database|sql|salesforce).*"],
}


class RoutingError(ValueError):
    """A task classification cannot produce a safe, auditable route."""


def _append(methods: list[str], stages: dict[str, int], method: str, stage: int) -> None:
    if method not in methods:
        methods.append(method)
    stages[method] = max(stage, stages.get(method, stage))


def _edge(edges: list[dict[str, str]], before: str, after: str) -> None:
    item = {"before": before, "after": after}
    if before != after and item not in edges:
        edges.append(item)


def _status(predicates: dict[str, Any], key: str, default: Any = False) -> Any:
    value = predicates.get(key, {})
    return value.get("status", default) if isinstance(value, dict) else default


def derive_risk_tier(predicates: dict[str, Any], *, claims_completeness: bool) -> str:
    if _status(predicates, "P3") is True:
        return "CRITICAL"
    if any(_status(predicates, key) is True for key in ("P1", "P2")) or claims_completeness:
        return "HIGH"
    return "MEDIUM"


def _risk_rank(value: str) -> int:
    return ["LOW", "MEDIUM", "HIGH", "CRITICAL"].index(value)


def route_context(
    *,
    task_shape: str,
    predicates: dict[str, Any] | None = None,
    risk_tier: str | None = None,
    codegraph_available: bool = False,
    lsp_available: bool = False,
    live_state_available: bool = False,
    symbol_ambiguity_hint: bool = False,
    claims_completeness: bool = False,
    include_canonical_docs: bool = True,
    canonical_docs: list[str] | None = None,
    parallel_shards: list[str] | None = None,
    allowed_agent_types: list[str] | None = None,
    allowed_models: list[str] | None = None,
    tool_matchers: dict[str, list[str]] | None = None,
    plan_id: str | None = None,
) -> dict[str, Any]:
    task_shape = task_shape.upper().strip()
    if task_shape not in TASK_SHAPES:
        raise RoutingError(f"unsupported task_shape: {task_shape}")
    predicates = dict(predicates or {})
    # At task start there may be no implementation diff yet. Unknown is not
    # false: P1-P3 remain deferred until an existing diff can be measured.
    predicates.setdefault("P1", {"name": "touches_shared_core", "status": "DEFERRED", "source": "diff-time", "command": None, "evidence": []})
    predicates.setdefault("P2", {"name": "multi_file_change", "status": "DEFERRED", "source": "diff-time", "command": None, "evidence": []})
    predicates.setdefault("P3", {"name": "database_write", "status": "DEFERRED", "source": "diff-time", "command": None, "evidence": []})
    # A hint may influence the planned fallback, but it never resolves P4.
    predicates["P4"] = {
        "name": "symbol_ambiguous",
        "status": "UNKNOWN",
        "source": "runtime-tool-receipt",
        "command": None,
        "evidence": [],
    }
    predicates["P5"] = {
        "name": "graph_fresh",
        "status": "UNKNOWN" if codegraph_available else "NOT_APPLICABLE",
        "source": "runtime-provider-receipt" if codegraph_available else "route",
        "command": None,
        "evidence": [],
    }
    predicates["P6"] = {
        "name": "dynamic_state_or_control_flow",
        "status": task_shape == "DYNAMIC_STATE_FLOW",
        "source": "task-shape",
        "command": None,
        "evidence": [task_shape],
    }

    derived_risk = derive_risk_tier(predicates, claims_completeness=claims_completeness)
    if risk_tier is None:
        risk_tier = derived_risk
    else:
        risk_tier = risk_tier.upper().strip()
        if risk_tier not in RISK_TIERS:
            raise RoutingError(f"unsupported risk_tier: {risk_tier}")
        if _risk_rank(risk_tier) < _risk_rank(derived_risk):
            raise RoutingError(f"risk_tier {risk_tier} understates deterministic risk {derived_risk}")

    methods: list[str] = []
    stages: dict[str, int] = {}
    edges: list[dict[str, str]] = []
    parallel_groups: list[list[str]] = []
    conditional_methods: list[dict[str, Any]] = []
    docs = [str(item).strip() for item in (canonical_docs or []) if str(item).strip()]
    if include_canonical_docs and docs:
        _append(methods, stages, "canonical-docs", 0)
    code_stage = 1 if "canonical-docs" in methods else 0
    high_radius = risk_tier in {"HIGH", "CRITICAL"} or claims_completeness

    if task_shape == "LEXICAL_ENUMERATION":
        _append(methods, stages, "rg", code_stage)
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "rg", "targeted-read")
        if codegraph_available:
            _append(methods, stages, "codegraph-status", 0)
            _append(methods, stages, "codegraph", code_stage + 2)
            _edge(edges, "targeted-read", "codegraph")
            _edge(edges, "codegraph-status", "codegraph")
        elif lsp_available:
            _append(methods, stages, "lsp", code_stage + 2)
            _edge(edges, "targeted-read", "lsp")

    elif task_shape == "KNOWN_SYMBOL_IMPACT":
        if codegraph_available and high_radius:
            # `rg` is independent and starts with provider preflight. The graph
            # query starts as soon as freshness is proven, while `rg` may still
            # be running; the join waits for both before targeted reads.
            _append(methods, stages, "codegraph-status", 0)
            _append(methods, stages, "rg", code_stage)
            if code_stage == 0:
                parallel_groups.append(["codegraph-status", "rg"])
            graph_stage = max(code_stage + 1, 1)
            _append(methods, stages, "codegraph", graph_stage)
            _edge(edges, "codegraph-status", "codegraph")
            _append(methods, stages, "targeted-read", graph_stage + 1)
            _edge(edges, "codegraph", "targeted-read")
            _edge(edges, "rg", "targeted-read")
        elif codegraph_available:
            _append(methods, stages, "codegraph-status", 0)
            graph_stage = max(code_stage, 1)
            _append(methods, stages, "codegraph", graph_stage)
            _append(methods, stages, "targeted-read", graph_stage + 1)
            _edge(edges, "codegraph-status", "codegraph")
            _edge(edges, "codegraph", "targeted-read")
        else:
            _append(methods, stages, "rg", code_stage)
            _append(methods, stages, "targeted-read", code_stage + 1)
            _edge(edges, "rg", "targeted-read")

        if lsp_available:
            lsp_stage = stages["targeted-read"] + 1
            _append(methods, stages, "lsp", lsp_stage)
            _edge(edges, "targeted-read", "lsp")
            if not symbol_ambiguity_hint and codegraph_available:
                conditional_methods.append({
                    "method": "lsp",
                    "when_predicate": "P4",
                    "equals": True,
                })

    elif task_shape == "DYNAMIC_STATE_FLOW":
        _append(methods, stages, "rg", code_stage)
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "rg", "targeted-read")
        tail = "targeted-read"
        tail_stage = code_stage + 1
        if lsp_available:
            _append(methods, stages, "lsp", code_stage + 2)
            _edge(edges, "targeted-read", "lsp")
            tail = "lsp"
            tail_stage = code_stage + 2
        if codegraph_available:
            _append(methods, stages, "codegraph-status", 0)
            _append(methods, stages, "codegraph", tail_stage + 1)
            _edge(edges, tail, "codegraph")
            _edge(edges, "codegraph-status", "codegraph")

    elif task_shape == "DOCS_OR_CONFIG":
        _append(methods, stages, "rg", code_stage)
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "rg", "targeted-read")

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
            _append(methods, stages, "codegraph-status", 0)
            _append(methods, stages, "codegraph", code_stage + 2)
            _edge(edges, "targeted-read", "codegraph")
            _edge(edges, "codegraph-status", "codegraph")
        elif lsp_available:
            _append(methods, stages, "lsp", code_stage + 2)
            _edge(edges, "targeted-read", "lsp")

    else:  # DIRECT_TARGETED
        _append(methods, stages, "rg", code_stage)
        _append(methods, stages, "targeted-read", code_stage + 1)
        _edge(edges, "rg", "targeted-read")

    if "canonical-docs" in methods:
        for method in methods:
            if method != "canonical-docs" and stages[method] == code_stage:
                _edge(edges, "canonical-docs", method)

    shards = [value.strip() for value in (parallel_shards or []) if value.strip()]
    if len(shards) != len(set(shards)):
        raise RoutingError("parallel shard scopes must be unique")
    if shards:
        raise RoutingError("parallel_shards are not supported until per-shard lifecycle, tool and coverage receipts are enforced")
    matchers = tool_matchers or {method: DEFAULT_TOOL_MATCHERS[method] for method in methods}
    conditional_names = {item["method"] for item in conditional_methods}
    required_methods = [method for method in methods if method not in conditional_names]
    plan = {
        "status": "PRONTO",
        "skill": "context-delivery",
        "plan_id": plan_id or str(uuid.uuid4()),
        "task_shape": task_shape,
        "risk_tier": risk_tier,
        "claims_completeness": bool(claims_completeness),
        "predicates": predicates,
        "canonical_docs": docs,
        "required_methods": required_methods,
        "conditional_methods": conditional_methods,
        "method_stages": [{"method": method, "stage": stages[method]} for method in methods],
        "dependency_edges": edges,
        "parallel_groups": parallel_groups,
        "parallel_shards": shards,
        "allowed_agent_types": allowed_agent_types or [],
        "allowed_models": allowed_models or [],
        "tool_matchers": [{"method": method, "patterns": list(matchers.get(method, []))} for method in methods],
        "provider_requirements": {
            "codegraph_freshness_required": "codegraph" in methods,
            "provider_status_tool_required": "codegraph-status" in methods,
        },
    }
    validate_route(plan)
    return plan


def route_from_repository(
    root: Path,
    *,
    base_ref: str,
    head_ref: str,
    task_shape: str,
    core_paths: str,
    data_write_patterns: str,
    **kwargs: Any,
) -> dict[str, Any]:
    predicates = evaluate_repository_predicates(
        root,
        base_ref=base_ref,
        head_ref=head_ref,
        core_paths=core_paths,
        data_write_patterns=data_write_patterns,
        task_shape=task_shape,
        claims_completeness=bool(kwargs.get("claims_completeness")),
    )
    return route_context(task_shape=task_shape, predicates=predicates, **kwargs)


def validate_route(plan: dict[str, Any]) -> None:
    required = plan.get("required_methods", [])
    conditional = plan.get("conditional_methods", [])
    conditional_names = [item.get("method") for item in conditional]
    if not isinstance(required, list) or not required or len(required) != len(set(required)):
        raise RoutingError("required_methods must be a non-empty unique list")
    if len(conditional_names) != len(set(conditional_names)):
        raise RoutingError("conditional_methods must be unique")
    all_methods = required + conditional_names
    if len(all_methods) != len(set(all_methods)):
        raise RoutingError("a method cannot be both required and conditional")
    stages = {item["method"]: item["stage"] for item in plan.get("method_stages", [])}
    if set(stages) != set(all_methods):
        raise RoutingError("method_stages must cover every required/conditional method exactly once")
    for method, stage in stages.items():
        if method not in KNOWN_METHODS or not isinstance(stage, int) or stage < 0:
            raise RoutingError(f"invalid method stage: {method}={stage!r}")
    for item in conditional:
        if item.get("when_predicate") not in {"P4"} or not isinstance(item.get("equals"), bool):
            raise RoutingError(f"unsupported conditional method: {item}")
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
    if not {"P1", "P2", "P3", "P4", "P5", "P6"} <= set(plan.get("predicates", {})):
        raise RoutingError("CONTEXT-PLAN must carry predicates P1-P6")
    matcher_methods = {item.get("method") for item in plan.get("tool_matchers", [])}
    if matcher_methods != set(all_methods):
        raise RoutingError("tool_matchers must cover every required/conditional method")
    if plan.get("parallel_shards"):
        raise RoutingError("parallel_shards are not supported until per-shard lifecycle, tool and coverage receipts are enforced")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", help="JSON object; stdin when omitted")
    parser.add_argument("--root")
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    raw = args.input_json if args.input_json is not None else input()
    request = json.loads(raw)
    if args.root and args.base:
        request.update({"root": Path(args.root), "base_ref": args.base, "head_ref": args.head})
        result = route_from_repository(**request)
    else:
        result = route_context(**request)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
