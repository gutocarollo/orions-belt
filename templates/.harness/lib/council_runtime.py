#!/usr/bin/env python3
"""Deterministic state and authority rules for the installed Delivery Council."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from mini_schema_validate import validate_instance


class TransitionError(ValueError):
    """Raised when evidence does not authorize the requested transition."""


NEXT = {
    None: {"ANCHOR"},
    "ANCHOR": {"PHASE-PLAN", "DELIVERY"},
    "PHASE-PLAN": {"ITEM-PLAN"},
    "ITEM-PLAN": {"SLICE"},
    "SLICE": {"VALIDATION"},
    "VALIDATION": {"LOCAL-COMMIT"},
    "LOCAL-COMMIT": {"PHASE-PLAN", "ITEM-PLAN", "QUALITY"},
    "QUALITY": {"ITEM-PLAN", "SIMPLIFICATION"},
    "SIMPLIFICATION": {"ADVERSARIAL"},
    "ADVERSARIAL": {"ITEM-PLAN", "DELIVERY"},
    "DELIVERY": set(),
}
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
PAYLOAD_SCHEMAS = {
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
    """Canonical quality result: Critical and Required are blocking."""
    return "CORRIGIR" if findings.get("Critical", 0) or findings.get("Required", 0) else "SATISFEITO"


def remote_action_allowed(action: str, authority: dict[str, Any]) -> bool:
    """Local commits are intrinsic; remote push/main merge require evidence."""
    if action == "local-commit":
        return True
    if action not in {"push", "merge-main"}:
        return False
    return bool(
        authority.get("remote_authorized") is True
        and authority.get("authorized_by")
        and authority.get("authorization_evidence")
    )


def apply_transition(state: dict[str, Any] | None, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply one Council event after validating its predecessor and evidence."""
    current = state.get("stage") if state else None
    if state and current == "QUALITY" and state.get("quality_status") == "CORRIGIR":
        _require(event == "ITEM-PLAN", "QUALITY: CORRIGIR requires ITEM-PLAN for the fix")
    if state and current == "ADVERSARIAL" and state.get("adversarial_status") == "CORRIGIR":
        _require(event == "ITEM-PLAN", "ADVERSARIAL: CORRIGIR requires ITEM-PLAN for the fix")
    if state and ((current == "QUALITY" and state.get("quality_status") == "BLOQUEADO") or (current == "ADVERSARIAL" and state.get("adversarial_status") == "BLOQUEADO")):
        raise TransitionError(f"{current}: BLOQUEADO is terminal until external resolution")
    _require(event in NEXT.get(current, set()), f"{event} cannot follow {current}; expected {sorted(NEXT.get(current, set()))}")
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
        result["implementer_id"] = payload.get("implementer_id", "council-implementer")
    else:
        read_only_delivery = result.get("mutation_mode") == "READ_ONLY" and event == "DELIVERY"
        _require(result.get("mutation_mode") != "READ_ONLY" or read_only_delivery, "read-only Council runs cannot enter execution")

    if event in {"PHASE-PLAN", "ITEM-PLAN"}:
        _require(payload.get("skill") == "planning-and-task-breakdown", f"{event} requires planning-and-task-breakdown")
        _require(payload.get("status") == "PRONTO", f"{event} requires PRONTO")
        if event == "ITEM-PLAN" and result.get("pending_fix"):
            pending = result["pending_fix"]
            _require(payload.get("fix_kind") == pending["kind"] and payload.get("consumes_review_round") == pending["round"], "ITEM-PLAN must consume the pending review fix request")
            result["pending_fix"] = None
    elif event == "SLICE":
        _require(payload.get("skill") == "incremental-implementation", "SLICE requires incremental-implementation")
        result["slice_files"] = list(payload["changed_files"])
    elif event == "VALIDATION":
        _require(payload.get("status") == "PASS" and payload.get("commands"), "VALIDATION requires PASS and commands")
        _require(set(payload["checked_files"]) == set(result.get("slice_files", [])), "VALIDATION checked_files must equal the current slice files")
        result["validated_files"] = list(payload["checked_files"])
    elif event == "LOCAL-COMMIT":
        sha = str(payload.get("sha", ""))
        _require(len(sha) == 40 and all(char in "0123456789abcdef" for char in sha.lower()), "LOCAL-COMMIT requires a 40-character SHA")
        _require(set(payload["files"]) == set(result.get("validated_files", [])), "LOCAL-COMMIT files must equal the validated slice files")
        result["commits"].append(sha)
        result.setdefault("commit_files", {})[sha] = list(payload["files"])
    elif event == "QUALITY":
        critical = payload.get("critical", 0)
        required = payload.get("required", 0)
        _require(isinstance(critical, int) and isinstance(required, int) and critical >= 0 and required >= 0, "QUALITY counts must be non-negative integers")
        blocking = critical + required
        status = payload.get("status")
        reviewer = payload.get("reviewer_id")
        round_number = payload.get("round", 1)
        _require(bool(reviewer) and reviewer != result.get("implementer_id"), "QUALITY requires an independent reviewer_id")
        _require(isinstance(round_number, int) and 1 <= round_number <= 3, "QUALITY round must be between 1 and 3")
        previous = result.get("quality_reviewer_id")
        _require(not previous or previous == reviewer, "QUALITY rounds must continue the same reviewer thread")
        _require(round_number == result.get("quality_round", 0) + 1, "QUALITY round must increment exactly by one")
        expected = "CORRIGIR" if blocking else "SATISFEITO"
        _require(status == "BLOQUEADO" or status == expected, "QUALITY status disagrees with blocking findings")
        result["quality_status"] = status
        result["quality_reviewer_id"] = reviewer
        result["quality_round"] = round_number
        if status == "CORRIGIR":
            result["pending_fix"] = {"kind": "quality", "round": round_number, "findings": deepcopy(payload.get("findings", []))}
    elif event == "SIMPLIFICATION":
        _require(payload.get("status") in {"APLICADA", "NAO_NECESSARIA"}, "SIMPLIFICATION requires a terminal status")
        if payload.get("status") == "APLICADA":
            _require(payload.get("commit_sha") in result.get("commits", []), "SIMPLIFICATION: APLICADA must reference a validated local commit")
    elif event == "ADVERSARIAL":
        reviewer = payload.get("reviewer_id")
        round_number = payload.get("round", 1)
        _require(bool(reviewer) and reviewer != result.get("implementer_id"), "ADVERSARIAL requires an independent reviewer_id")
        _require(isinstance(round_number, int) and 1 <= round_number <= 3, "ADVERSARIAL round must be between 1 and 3")
        previous = result.get("adversarial_reviewer_id")
        _require(not previous or previous == reviewer, "ADVERSARIAL rounds must continue the same reviewer thread")
        _require(round_number == result.get("adversarial_round", 0) + 1, "ADVERSARIAL round must increment exactly by one")
        _require(payload.get("status") in {"SATISFEITO", "CORRIGIR", "BLOQUEADO"}, "ADVERSARIAL requires SATISFEITO, CORRIGIR or BLOQUEADO")
        result["adversarial_status"] = payload["status"]
        result["adversarial_reviewer_id"] = reviewer
        result["adversarial_round"] = round_number
        if payload["status"] == "CORRIGIR":
            result["pending_fix"] = {"kind": "adversarial", "round": round_number, "findings": deepcopy(payload.get("findings", []))}
    elif event == "DELIVERY":
        _require(payload.get("status") == "SATISFEITO" and payload.get("manifest"), "DELIVERY requires SATISFEITO and manifest")
        if result.get("mutation_mode") == "WORKSPACE_WRITE":
            _require(bool(result.get("commits")), "workspace delivery requires local commits")
            _require(result.get("quality_status") == "SATISFEITO", "DELIVERY requires QUALITY: SATISFEITO")
            _require(result.get("adversarial_status") == "SATISFEITO", "DELIVERY requires ADVERSARIAL: SATISFEITO")

    result["stage"] = event
    result["history"].append({"event": event, "payload": deepcopy(payload)})
    return result
