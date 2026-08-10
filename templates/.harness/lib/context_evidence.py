#!/usr/bin/env python3
"""Evidence verification for CONTEXT-DELIVERY."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class ContextEvidenceError(ValueError):
    """Context evidence is missing, stale, inconsistent or untrusted."""


COMPLETENESS_RE = re.compile(
    r"\b(all|every|complete|completely|exhaustive|exhaustively|todos|todas|cada|completo|completa|exaustivo|exaustiva)\b",
    re.IGNORECASE,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContextEvidenceError(message)


def _safe_file(root: Path, relative: str, allowed_root: str) -> Path:
    _require(bool(relative), "evidence path is empty")
    path = (root / relative).resolve()
    boundary = (root / allowed_root).resolve()
    _require(path == boundary or boundary in path.parents, f"evidence path escapes {allowed_root}: {relative}")
    _require(path.is_file(), f"evidence file does not exist: {relative}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_file(root: Path, receipt: dict[str, Any], allowed_root: str) -> Path:
    path = _safe_file(root, str(receipt.get("path", "")), allowed_root)
    expected = str(receipt.get("sha256", ""))
    _require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"invalid sha256 for {receipt.get('path')}")
    _require(_sha256(path) == expected, f"evidence hash mismatch: {receipt.get('path')}")
    return path


def _lifecycle_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContextEvidenceError(f"{path}:{number}: invalid JSONL: {exc}") from exc
        _require(isinstance(item, dict), f"{path}:{number}: lifecycle record must be an object")
        records.append(item)
    return records


def _verify_lifecycle(root: Path, delivery: dict[str, Any], plan: dict[str, Any]) -> None:
    receipt = delivery["lifecycle_receipt"]
    path = _verify_file(root, receipt, ".harness/runs/subagents")
    records = _lifecycle_records(path)
    agent_id = delivery["agent_id"]
    agent_type = delivery["agent_type"]
    runtime = delivery["runtime"]

    matching = [
        item for item in records
        if item.get("agent_id") == agent_id
        and item.get("agent_type") == agent_type
        and item.get("runtime") == runtime
    ]
    _require(any(item.get("event") == "SubagentStart" for item in matching), "missing matching SubagentStart receipt")
    _require(any(item.get("event") == "SubagentStop" for item in matching), "missing matching SubagentStop receipt")

    configured = {str(item.get("configured_model")) for item in matching if item.get("configured_model")}
    observed = {
        str(item.get("model")) for item in matching
        if item.get("event") == "AgentToolResult" and item.get("model")
    }
    allowed = set(plan.get("allowed_models", []))
    if allowed:
        _require(delivery["model"] in allowed, f"delivery model is not allowed: {delivery['model']}")
        _require(not configured or configured <= allowed, f"configured subagent model is not allowed: {sorted(configured)}")
        if runtime == "claude":
            _require(bool(observed), "Claude context agent requires AgentToolResult with resolvedModel")
            _require(observed <= allowed, f"observed Claude model is not allowed: {sorted(observed)}")
            _require(delivery["model"] in observed, "delivery model differs from observed Claude resolvedModel")

    allowed_types = set(plan.get("allowed_agent_types", []))
    if allowed_types:
        _require(agent_type in allowed_types, f"agent_type is not authorized by CONTEXT-PLAN: {agent_type}")


def _verify_artifacts(root: Path, delivery: dict[str, Any], plan: dict[str, Any]) -> None:
    required = list(plan["required_methods"])
    artifacts = delivery["artifacts"]
    by_method: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        method = artifact["method"]
        _require(method not in by_method, f"duplicate artifact method: {method}")
        _verify_file(root, artifact, ".harness/runs")
        stage = artifact.get("stage")
        _require(isinstance(stage, int) and stage >= 0, f"invalid artifact stage: {method}")
        by_method[method] = artifact
    missing = [method for method in required if method not in by_method]
    _require(not missing, f"missing artifacts for required methods: {missing}")

    planned_stages = {item["method"]: item["stage"] for item in plan["method_stages"]}
    for method in required:
        _require(
            by_method[method]["stage"] == planned_stages[method],
            f"artifact stage differs from CONTEXT-PLAN: {method}",
        )
    for edge in plan.get("dependency_edges", []):
        before, after = edge["before"], edge["after"]
        _require(
            by_method[before]["stage"] < by_method[after]["stage"],
            f"artifact execution order violates {before} -> {after}",
        )


def _verify_provider(delivery: dict[str, Any], plan: dict[str, Any]) -> None:
    if "codegraph" not in plan["required_methods"]:
        return
    provider = delivery["provider_state"]
    _require(provider.get("provider") == "codegraph", "codegraph route requires codegraph provider_state")
    _require(provider.get("status") == "AVAILABLE", "codegraph provider was not available")
    _require(provider.get("index_fresh") is True, "codegraph index is stale")
    _require(provider.get("pending_changes") == 0, "codegraph has pending changes affecting freshness")


def _verify_coverage(delivery: dict[str, Any], plan: dict[str, Any]) -> None:
    coverage = delivery["coverage"]
    for key in ("eligible_files", "analyzed_files", "candidates", "confirmed", "false_positives", "unresolved"):
        value = coverage.get(key)
        _require(isinstance(value, int) and value >= 0, f"coverage.{key} must be a non-negative integer")
    claim_text = "\n".join(item.get("claim", "") for item in delivery.get("claims", []))
    exhaustive = bool(plan.get("claims_completeness")) or bool(COMPLETENESS_RE.search(claim_text))
    if exhaustive:
        _require(coverage["analyzed_files"] == coverage["eligible_files"], "exhaustive claim requires analyzed_files == eligible_files")
        _require(coverage["unresolved"] == 0, "exhaustive claim requires unresolved == 0")
        _require(
            coverage["confirmed"] + coverage["false_positives"] == coverage["candidates"],
            "exhaustive claim requires every candidate classified",
        )
    _require(
        not any(item.get("severity") in {"CRITICAL", "HIGH"} for item in delivery.get("unresolved_items", [])),
        "critical/high context items remain unresolved",
    )


def verify_context_delivery(
    delivery: dict[str, Any],
    plan: dict[str, Any],
    repository_root: Path,
) -> dict[str, Any]:
    """Verify a CONTEXT-DELIVERY payload against its persisted plan and files."""
    _require(delivery.get("status") == "SATISFEITO", "CONTEXT-DELIVERY requires SATISFEITO")
    _require(delivery.get("skill") == "context-delivery", "CONTEXT-DELIVERY requires context-delivery skill")
    _require(delivery.get("plan_id") == plan.get("plan_id"), "CONTEXT-DELIVERY plan_id differs from CONTEXT-PLAN")
    _verify_lifecycle(repository_root, delivery, plan)
    _verify_artifacts(repository_root, delivery, plan)
    _verify_provider(delivery, plan)
    _verify_coverage(delivery, plan)
    claims = delivery.get("claims", [])
    _require(isinstance(claims, list) and claims, "CONTEXT-DELIVERY requires at least one evidence-bound claim")
    for number, claim in enumerate(claims, 1):
        _require(bool(claim.get("claim")), f"claim {number} is empty")
        evidence = claim.get("evidence")
        _require(isinstance(evidence, list) and evidence, f"claim {number} has no evidence")
    return {
        "plan_id": delivery["plan_id"],
        "agent_id": delivery["agent_id"],
        "agent_type": delivery["agent_type"],
        "runtime": delivery["runtime"],
        "model": delivery["model"],
        "coverage": dict(delivery["coverage"]),
        "methods": list(plan["required_methods"]),
    }
