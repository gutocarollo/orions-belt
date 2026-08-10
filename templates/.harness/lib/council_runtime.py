#!/usr/bin/env python3
"""Deterministic state and authority rules for the installed Delivery Council."""
from __future__ import annotations

from copy import deepcopy
import json
import re
from pathlib import Path
from typing import Any

from context_evidence import ContextEvidenceError, repository_fingerprint, verify_context_delivery
from context_routing import RoutingError, validate_route
from mini_schema_validate import validate_instance
from objective_control import (
    ObjectiveControlError,
    TEST_CLASSES,
    assess_impact,
    validate_execution_graph,
    verify_impact_evidence,
)


class TransitionError(ValueError):
    """Raised when evidence does not authorize the requested transition."""


REVIEWER_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

NEXT = {
    None: {"ANCHOR"},
    "ANCHOR": {"CONTEXT-PLAN", "PHASE-PLAN", "DELIVERY"},
    "CONTEXT-PLAN": {"CONTEXT-DELIVERY"},
    "CONTEXT-DELIVERY": {"PHASE-PLAN"},
    "PHASE-PLAN": {"ITEM-PLAN"},
    "ITEM-PLAN": {"SLICE"},
    "SLICE": {"VALIDATION"},
    "VALIDATION": {"LOCAL-COMMIT"},
    "LOCAL-COMMIT": {"PHASE-PLAN", "ITEM-PLAN", "QUALITY", "ADVERSARIAL"},
    "QUALITY": {"ITEM-PLAN", "SIMPLIFICATION"},
    "SIMPLIFICATION": {"ITEM-PLAN", "ADVERSARIAL"},
    "ADVERSARIAL": {"ITEM-PLAN", "DELIVERY"},
    "DELIVERY": set(),
}
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
PAYLOAD_SCHEMAS = {
    "CONTEXT-PLAN": "context-plan-result.schema.json",
    "CONTEXT-DELIVERY": "context-delivery-result.schema.json",
    "PHASE-PLAN": "phase-plan-result.schema.json",
    "ITEM-PLAN": "item-plan-result.schema.json",
    "QUALITY": "quality-review-result.schema.json",
    "SIMPLIFICATION": "simplification-result.schema.json",
    "ADVERSARIAL": "adversarial-review-result.schema.json",
    "DELIVERY": "delivery-result.schema.json",
    "SLICE": "slice-event.schema.json",
    "VALIDATION": "validation-event.schema.json",
    "LOCAL-COMMIT": "local-commit-event.schema.json",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TransitionError(message)


def evaluate_quality(findings: dict[str, int]) -> str:
    return "CORRIGIR" if findings.get("Critical", 0) or findings.get("Required", 0) else "SATISFEITO"


def _test_map(tests: dict[str, list[str]]) -> dict[str, str]:
    mapped = {test_id: test_class for test_class in TEST_CLASSES for test_id in tests[test_class]}
    _require(len(mapped) == sum(len(tests[name]) for name in TEST_CLASSES), "test IDs must be unique across classes")
    return mapped


def _review_decision(
    payload: dict[str, Any],
    state: dict[str, Any],
    repository_root: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    immediate: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    active_phase = state.get("active_phase", {})
    graph = state.get("execution_graph", {})
    graph_nodes = set(graph.get("nodes", []))
    critical_nodes = {
        node
        for edge in graph.get("edges", [])
        if edge.get("critical")
        for node in (edge.get("from"), edge.get("to"))
    }

    def bind_to_active_phase(value: dict[str, Any], blocking: bool) -> None:
        active_nodes = {active_phase.get("entry_node"), active_phase.get("exit_node")} - {None}
        assessed_nodes = set(value.get("graph_nodes", []))
        _require(assessed_nodes <= graph_nodes, "impact graph_nodes must exist in the anchored execution graph")
        affects_current = bool(active_nodes & assessed_nodes)
        _require(
            value.get("affects_current_phase") is affects_current,
            "impact affects_current_phase must be derived from the active phase graph nodes",
        )
        if blocking:
            _require(affects_current, "blocking findings must reference a node in the active phase")
        _require(
            value.get("on_critical_path") is bool(assessed_nodes & critical_nodes),
            "impact on_critical_path must be derived from the anchored execution graph",
        )
        if value.get("evidence_status") == "REAL":
            _require(repository_root is not None, "REAL impact evidence requires repository resolution")
            verify_impact_evidence(repository_root, value)

    try:
        for finding in payload.get("findings", []):
            bind_to_active_phase(finding["impact"], True)
            decision = assess_impact(finding["impact"])
            _require(
                decision["disposition"] in {"CRITICAL_BLOCK", "HIGH_FIX_NOW"},
                "blocking findings must be CRITICAL_BLOCK or HIGH_FIX_NOW",
            )
            immediate.append({**deepcopy(finding), "impact": decision})
        for finding in payload.get("deferred_findings", []):
            bind_to_active_phase(finding["impact"], False)
            decision = assess_impact(finding["impact"])
            _require(decision["disposition"] == "DEFER_RUN", "deferred findings must be DEFER_RUN")
            deferred.append({**deepcopy(finding), "impact": decision})
    except (KeyError, ObjectiveControlError) as exc:
        raise TransitionError(str(exc)) from exc

    critical = sum(item["impact"]["disposition"] == "CRITICAL_BLOCK" for item in immediate)
    high = sum(item["impact"]["disposition"] == "HIGH_FIX_NOW" for item in immediate)
    _require(
        payload.get("critical") == critical and payload.get("required") == high,
        "review counts disagree with assessed findings",
    )
    status = payload.get("status")
    if status == "BLOQUEADO":
        _require(
            critical > 0 and bool(payload.get("external_blocker")),
            "BLOQUEADO requires a critical finding and concrete external_blocker",
        )
    else:
        _require(status == ("CORRIGIR" if immediate else "SATISFEITO"), "review status disagrees with assessed findings")
    return immediate, deferred


def remote_action_allowed(action: str, authority: dict[str, Any]) -> bool:
    if action == "local-commit":
        return True
    if action not in {"push", "merge-main"}:
        return False
    return bool(
        authority.get("remote_authorized") is True
        and authority.get("authorized_by")
        and authority.get("authorization_evidence")
    )


def bind_context_payload(
    state: dict[str, Any],
    event: str,
    payload: dict[str, Any],
    repository_root: Path,
    *,
    run_id: str | None = None,
    replaying: bool = False,
) -> dict[str, Any]:
    """Bind context events to the active run, anchor and repository snapshot."""
    _require(event in {"CONTEXT-PLAN", "CONTEXT-DELIVERY"}, f"cannot bind context event: {event}")
    expected_run = str(state.get("run_id") or run_id or "")
    expected_base = str(state.get("base_sha") or "")
    _require(bool(expected_run), f"{event} requires an active Council run_id")
    _require(not run_id or run_id == expected_run, f"{event} run_id differs from its Council ledger")
    _require(re.fullmatch(r"[0-9a-f]{40}", expected_base) is not None, f"{event} requires the Council base_sha")
    result = deepcopy(payload)
    if event == "CONTEXT-PLAN":
        supplied = result.get("council_binding")
        anchored_fingerprint = str(state.get("repository_fingerprint") or "")
        _require(re.fullmatch(r"[0-9a-f]{64}", anchored_fingerprint) is not None, "CONTEXT-PLAN requires the anchor repository fingerprint")
        if replaying:
            _require(isinstance(supplied, dict), "historical CONTEXT-PLAN lacks Council binding")
            fingerprint = str(supplied.get("repository_fingerprint") or "")
        else:
            fingerprint = repository_fingerprint(repository_root)
            _require(fingerprint == anchored_fingerprint, "repository drifted after Council ANCHOR")
            if supplied is not None:
                _require(isinstance(supplied, dict), "CONTEXT-PLAN council_binding must be an object")
                _require(
                    supplied == {
                        "run_id": expected_run,
                        "base_sha": expected_base,
                        "repository_fingerprint": fingerprint,
                    },
                    "CONTEXT-PLAN council_binding differs from the active run or repository",
                )
        _require(re.fullmatch(r"[0-9a-f]{64}", fingerprint) is not None, "CONTEXT-PLAN repository fingerprint is invalid")
        result["council_binding"] = {
            "run_id": expected_run,
            "base_sha": expected_base,
            "repository_fingerprint": fingerprint,
        }
        return result

    plan = state.get("context_plan") or {}
    binding = plan.get("council_binding") or {}
    _require(binding.get("run_id") == expected_run, "CONTEXT-PLAN is not bound to the active Council run")
    _require(binding.get("base_sha") == expected_base, "CONTEXT-PLAN is not bound to the Council anchor")
    expected = {
        "run_id": expected_run,
        "base_sha": expected_base,
        "repository_fingerprint": binding.get("repository_fingerprint"),
    }
    for key, value in expected.items():
        if key in result:
            _require(result[key] == value, f"CONTEXT-DELIVERY {key} differs from CONTEXT-PLAN")
        result[key] = value
    _require(bool(result.get("session_id")), "CONTEXT-DELIVERY requires runtime session_id")
    if not replaying:
        _require(
            repository_fingerprint(repository_root) == result["repository_fingerprint"],
            "CONTEXT-DELIVERY repository fingerprint drifted after CONTEXT-PLAN",
        )
    return result


def apply_transition(
    state: dict[str, Any] | None,
    event: str,
    payload: dict[str, Any],
    repository_root: Path | None = None,
    *,
    run_id: str | None = None,
    replaying: bool = False,
) -> dict[str, Any]:
    current = state.get("stage") if state else None
    if state and current == "QUALITY" and state.get("quality_status") == "CORRIGIR":
        _require(event == "ITEM-PLAN", "QUALITY: CORRIGIR requires ITEM-PLAN for the fix")
    if state and current == "ADVERSARIAL" and state.get("adversarial_status") == "CORRIGIR":
        _require(event == "ITEM-PLAN", "ADVERSARIAL: CORRIGIR requires ITEM-PLAN for the fix")
    if state and current == "SIMPLIFICATION":
        expected = "ITEM-PLAN" if state.get("simplification_status") == "APLICAR" else "ADVERSARIAL"
        _require(event == expected, f"SIMPLIFICATION: {state.get('simplification_status')} requires {expected}")
    if state and (
        (current == "QUALITY" and state.get("quality_status") == "BLOQUEADO")
        or (current == "ADVERSARIAL" and state.get("adversarial_status") == "BLOQUEADO")
    ):
        raise TransitionError(f"{current}: BLOQUEADO is terminal until external resolution")

    allowed = set(NEXT.get(current, set()))
    if state and current == "ANCHOR" and state.get("context_required"):
        allowed = {"CONTEXT-PLAN", "DELIVERY"}
    _require(event in allowed, f"{event} cannot follow {current}; expected {sorted(allowed)}")

    if state and run_id:
        _require(state.get("run_id") == run_id, "Council state run_id differs from its ledger")
    if event in {"CONTEXT-PLAN", "CONTEXT-DELIVERY"}:
        _require(repository_root is not None, f"{event} requires repository resolution")
        _require(state is not None, f"{event} requires an anchored Council state")
        payload = bind_context_payload(
            state, event, payload, repository_root, run_id=run_id, replaying=replaying
        )

    schema_name = PAYLOAD_SCHEMAS.get(event)
    if schema_name:
        errors = validate_instance(payload, json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8")))
        _require(not errors, f"{event} payload schema violation: {'; '.join(errors)}")

    result = deepcopy(state) if state else {"history": [], "commits": []}

    if event == "ANCHOR":
        mode = payload.get("mutation_mode")
        _require(mode in {"READ_ONLY", "WORKSPACE_WRITE"}, "ANCHOR requires a valid mutation_mode")
        _require(bool(payload.get("anchor_source")), "ANCHOR requires anchor_source")
        result["mutation_mode"] = mode
        result["context_required"] = bool(payload.get("context_required", False))
        effective_run_id = str(payload.get("run_id") or run_id or "")
        if payload.get("run_id") and run_id:
            _require(payload["run_id"] == run_id, "ANCHOR run_id differs from its Council ledger")
        if result["context_required"]:
            _require(bool(effective_run_id), "context-enabled ANCHOR requires run_id")
        if effective_run_id:
            _require(re.fullmatch(r"[A-Za-z0-9_.-]+", effective_run_id) is not None, "ANCHOR run_id is invalid")
            result["run_id"] = effective_run_id
        if result["context_required"]:
            supplied_fingerprint = str(payload.get("repository_fingerprint") or "")
            if replaying:
                _require(
                    re.fullmatch(r"[0-9a-f]{64}", supplied_fingerprint) is not None,
                    "historical context-enabled ANCHOR lacks repository fingerprint",
                )
            else:
                _require(repository_root is not None, "context-enabled ANCHOR requires repository resolution")
                current_fingerprint = repository_fingerprint(repository_root)
                if supplied_fingerprint:
                    _require(
                        supplied_fingerprint == current_fingerprint,
                        "ANCHOR repository fingerprint differs from the current checkout",
                    )
                supplied_fingerprint = current_fingerprint
            result["repository_fingerprint"] = supplied_fingerprint
        result["implementer_id"] = payload.get("implementer_id", "council-implementer")
        if mode == "WORKSPACE_WRITE":
            base_sha = str(payload.get("base_sha", ""))
            _require(
                len(base_sha) == 40 and all(char in "0123456789abcdef" for char in base_sha.lower()),
                "workspace ANCHOR requires a full base_sha",
            )
            _require(isinstance(payload.get("worktree_baseline"), list), "workspace ANCHOR requires worktree_baseline")
            result["base_sha"] = base_sha
            result["worktree_baseline"] = sorted(str(item) for item in payload["worktree_baseline"])
            graph = payload.get("execution_graph")
            _require(isinstance(graph, dict), "workspace ANCHOR requires execution_graph")
            try:
                validate_execution_graph(graph)
            except ObjectiveControlError as exc:
                raise TransitionError(str(exc)) from exc
            result["execution_graph"] = deepcopy(graph)
            result["objective"] = graph["objective"]
    else:
        read_only_delivery = result.get("mutation_mode") == "READ_ONLY" and event == "DELIVERY"
        _require(
            result.get("mutation_mode") != "READ_ONLY" or read_only_delivery,
            "read-only Council runs cannot enter execution",
        )

    if event == "CONTEXT-PLAN":
        try:
            validate_route(payload)
        except RoutingError as exc:
            raise TransitionError(str(exc)) from exc
        result["context_plan"] = deepcopy(payload)

    elif event == "CONTEXT-DELIVERY":
        _require(repository_root is not None, "CONTEXT-DELIVERY requires repository resolution")
        plan = result.get("context_plan")
        _require(isinstance(plan, dict), "CONTEXT-DELIVERY requires persisted CONTEXT-PLAN")
        try:
            result["context_delivery"] = verify_context_delivery(
                payload,
                plan,
                repository_root,
                expected_run_id=str(result.get("run_id") or ""),
                expected_base_sha=str(result.get("base_sha") or ""),
                verify_current_repository=not replaying,
            )
        except ContextEvidenceError as exc:
            raise TransitionError(str(exc)) from exc

    elif event in {"PHASE-PLAN", "ITEM-PLAN"}:
        if event == "PHASE-PLAN" and result.get("context_required"):
            _require(bool(result.get("context_delivery")), "PHASE-PLAN requires verified CONTEXT-DELIVERY")
        _require(payload.get("skill") == "planning-and-task-breakdown", f"{event} requires planning-and-task-breakdown")
        _require(payload.get("status") == "PRONTO", f"{event} requires PRONTO")
        if event == "PHASE-PLAN":
            _require(payload["entry_node"] != payload["exit_node"], "PHASE-PLAN entry_node and exit_node must differ")
            _require(
                not result.get("objective") or result["objective"] == payload["objective"],
                "PHASE-PLAN cannot change the macro objective",
            )
            edge = next(
                (item for item in result["execution_graph"]["edges"] if item["edge_id"] == payload["edge_id"]),
                None,
            )
            _require(
                bool(edge)
                and payload["entry_node"] == edge["from"]
                and payload["exit_node"] == edge["to"]
                and payload["tests"] == edge["tests"],
                "PHASE-PLAN must match the anchored execution graph edge",
            )
            result["objective"] = payload["objective"]
            result["active_phase"] = {
                key: deepcopy(payload[key])
                for key in ("phase", "edge_id", "entry_node", "exit_node", "tests")
            }
        else:
            phase = result.get("active_phase", {})
            _require(payload["objective"] == result.get("objective"), "ITEM-PLAN objective must equal the macro objective")
            _require(
                payload["phase"] == phase.get("phase") and payload["edge_id"] == phase.get("edge_id"),
                "ITEM-PLAN must reference the active phase and graph edge",
            )
            _require(payload["tests"] == phase.get("tests"), "ITEM-PLAN tests must equal the active phase tests")
            result["planned_tests"] = _test_map(payload["tests"])
            if result.get("pending_fix"):
                pending = result["pending_fix"]
                _require(
                    payload.get("fix_kind") == pending["kind"]
                    and payload.get("consumes_review_round") == pending["round"],
                    "ITEM-PLAN must consume the pending review fix request",
                )
                result["pending_fix"] = None

    elif event == "SLICE":
        _require(payload.get("skill") == "incremental-implementation", "SLICE requires incremental-implementation")
        result["slice_files"] = list(payload["changed_files"])

    elif event == "VALIDATION":
        _require(payload.get("status") == "PASS" and payload.get("commands"), "VALIDATION requires PASS and commands")
        _require(set(payload["checked_files"]) == set(result.get("slice_files", [])), "VALIDATION checked_files must equal the current slice files")
        _require(
            {item["path"] for item in payload["file_hashes"]} == set(payload["checked_files"]),
            "VALIDATION file hashes must equal checked_files",
        )
        command_test_ids = [test_id for command in payload["commands"] for test_id in command["test_ids"]]
        _require(len(command_test_ids) == len(set(command_test_ids)), "VALIDATION command test IDs must be unique")
        actual_tests = {test_id: test_class for test_class, ids in payload["tests"].items() for test_id in ids}
        _require(set(command_test_ids) == set(actual_tests), "VALIDATION commands must execute every planned test ID")
        _require(actual_tests == result.get("planned_tests"), "VALIDATION test IDs and classes must equal the item plan")
        result["validated_files"] = list(payload["checked_files"])
        result["validated_tests"] = actual_tests
        result["validation_evidence"] = deepcopy(payload)

    elif event == "LOCAL-COMMIT":
        sha = str(payload.get("sha", ""))
        _require(
            len(sha) == 40 and all(char in "0123456789abcdef" for char in sha.lower()),
            "LOCAL-COMMIT requires a 40-character SHA",
        )
        _require(sha not in result["commits"], "LOCAL-COMMIT requires a new SHA for every slice")
        _require(
            set(payload["files"]) == set(result.get("validated_files", [])),
            "LOCAL-COMMIT files must equal the validated slice files",
        )
        result["commits"].append(sha)
        result.setdefault("commit_files", {})[sha] = list(payload["files"])
        result.setdefault("commit_tests", {})[sha] = deepcopy(result.get("validated_tests", {}))
        result.setdefault("commit_edges", {})[sha] = result["active_phase"]["edge_id"]

    elif event == "QUALITY":
        findings, deferred = _review_decision(payload, result, repository_root)
        status = payload.get("status")
        reviewer = payload.get("reviewer_id")
        round_number = payload.get("round", 1)
        _require(bool(reviewer) and reviewer != result.get("implementer_id"), "QUALITY requires an independent reviewer_id")
        _require(bool(REVIEWER_ID_RE.fullmatch(str(reviewer))), "QUALITY reviewer_id must be a thread UUID")
        _require(isinstance(round_number, int) and 1 <= round_number <= 3, "QUALITY round must be between 1 and 3")
        previous = result.get("quality_reviewer_id")
        _require(not previous or previous == reviewer, "QUALITY rounds must continue the same reviewer thread")
        _require(round_number == result.get("quality_round", 0) + 1, "QUALITY round must increment exactly by one")
        result["quality_status"] = status
        result["quality_reviewer_id"] = reviewer
        result["quality_round"] = round_number
        result.setdefault("deferred_findings", []).extend(deferred)
        if status == "CORRIGIR":
            result["pending_fix"] = {"kind": "quality", "round": round_number, "findings": findings}

    elif event == "SIMPLIFICATION":
        status = payload.get("status")
        _require(status in {"APLICAR", "NAO_NECESSARIA"}, "SIMPLIFICATION requires APLICAR or NAO_NECESSARIA")
        result["simplification_status"] = status
        if status == "APLICAR":
            result["pending_fix"] = {
                "kind": "simplification",
                "round": result.get("quality_round", 1),
                "findings": [],
            }

    elif event == "ADVERSARIAL":
        findings, deferred = _review_decision(payload, result, repository_root)
        reviewer = payload.get("reviewer_id")
        round_number = payload.get("round", 1)
        _require(bool(reviewer) and reviewer != result.get("implementer_id"), "ADVERSARIAL requires an independent reviewer_id")
        _require(reviewer != result.get("quality_reviewer_id"), "ADVERSARIAL requires a reviewer distinct from QUALITY")
        _require(bool(REVIEWER_ID_RE.fullmatch(str(reviewer))), "ADVERSARIAL reviewer_id must be a thread UUID")
        _require(isinstance(round_number, int) and 1 <= round_number <= 3, "ADVERSARIAL round must be between 1 and 3")
        previous = result.get("adversarial_reviewer_id")
        _require(not previous or previous == reviewer, "ADVERSARIAL rounds must continue the same reviewer thread")
        _require(round_number == result.get("adversarial_round", 0) + 1, "ADVERSARIAL round must increment exactly by one")
        result["adversarial_status"] = payload["status"]
        result["adversarial_reviewer_id"] = reviewer
        result["adversarial_round"] = round_number
        result.setdefault("deferred_findings", []).extend(deferred)
        if payload["status"] == "CORRIGIR":
            result["pending_fix"] = {"kind": "adversarial", "round": round_number, "findings": findings}

    elif event == "DELIVERY":
        _require(payload.get("status") == "SATISFEITO" and payload.get("manifest"), "DELIVERY requires SATISFEITO and manifest")
        if result.get("mutation_mode") == "WORKSPACE_WRITE":
            _require(bool(result.get("commits")), "workspace delivery requires local commits")
            _require(
                not result.get("quality_status") or result.get("quality_status") == "SATISFEITO",
                "DELIVERY requires any executed QUALITY review to be SATISFEITO",
            )
            _require(result.get("adversarial_status") == "SATISFEITO", "DELIVERY requires ADVERSARIAL: SATISFEITO")

    result["stage"] = event
    result["history"].append({"event": event, "payload": deepcopy(payload)})
    return result
