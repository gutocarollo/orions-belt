#!/usr/bin/env python3
"""Plan proportional execution-review batches without adding Council states.

Review orchestration is intentionally softer than the Full Council state
machine. Parallel prisms inspect one frozen objective/diff concurrently; their
findings are consolidated into the existing ADVERSARIAL transition.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

EXECUTION_PROFILES = ("DIRECT", "LIGHT", "FULL")
REVIEW_MODES = ("AUTO", "SINGLE", "BATCH", "FULL")
PRISMS = (
    "correctness-security-data",
    "tests-acceptance-regression",
    "simplicity-maintainability",
)
BLOCKING = {"CRITICAL", "HIGH"}


class ReviewBatchError(ValueError):
    """Invalid review-profile request."""


def _enum(value: str, allowed: tuple[str, ...], label: str) -> str:
    normalized = str(value or "").upper().strip()
    if normalized not in allowed:
        raise ReviewBatchError(f"unsupported {label}: {value!r}")
    return normalized


def plan_review_batch(
    *,
    execution_profile: str,
    review_mode: str = "AUTO",
    prisms: list[str] | None = None,
) -> dict[str, Any]:
    profile = _enum(execution_profile, EXECUTION_PROFILES, "execution_profile")
    requested = _enum(review_mode, REVIEW_MODES, "review_mode")

    if profile == "DIRECT":
        return {"execution_profile": profile, "requested_mode": requested, "effective_mode": "NONE", "parallel": False, "prisms": [], "max_reviewers": 0, "max_batches": 0}

    if requested == "FULL":
        return {"execution_profile": profile, "requested_mode": requested, "effective_mode": "FULL", "parallel": False, "prisms": list(PRISMS), "max_reviewers": 1, "max_batches": 1}

    if requested == "AUTO":
        requested = "BATCH" if profile == "FULL" else "SINGLE"

    if requested == "SINGLE":
        return {"execution_profile": profile, "requested_mode": review_mode.upper(), "effective_mode": "SINGLE", "parallel": False, "prisms": ["correctness-security-data"], "max_reviewers": 1, "max_batches": 1}

    selected = list(dict.fromkeys(prisms or PRISMS))
    unknown = [item for item in selected if item not in PRISMS]
    if unknown:
        raise ReviewBatchError(f"unknown review prisms: {unknown}")
    limit = 2 if profile == "LIGHT" else 3
    selected = selected[:limit]
    if len(selected) < 2:
        return {"execution_profile": profile, "requested_mode": review_mode.upper(), "effective_mode": "SINGLE", "parallel": False, "prisms": selected or ["correctness-security-data"], "max_reviewers": 1, "max_batches": 1}
    return {"execution_profile": profile, "requested_mode": review_mode.upper(), "effective_mode": "BATCH", "parallel": True, "prisms": selected, "max_reviewers": len(selected), "max_batches": 1}


def consolidate_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    fix_now: list[dict[str, Any]] = []
    backlog: list[dict[str, Any]] = []
    seen: set[str] = set()
    affected_prisms: set[str] = set()

    for raw in findings:
        item = dict(raw)
        finding_id = str(item.get("id") or "").strip()
        if finding_id and finding_id in seen:
            continue
        if finding_id:
            seen.add(finding_id)
        severity = str(item.get("severity") or "LOW").upper()
        reachable = bool(item.get("reachable_in_current_task", True))
        prism = str(item.get("prism") or "").strip()
        item["severity"] = severity
        item["reachable_in_current_task"] = reachable
        if severity in BLOCKING and reachable:
            fix_now.append(item)
            if prism in PRISMS:
                affected_prisms.add(prism)
        else:
            backlog.append(item)

    return {"fix_now": fix_now, "backlog": backlog, "targeted_recheck_prisms": sorted(affected_prisms), "requires_recheck": bool(fix_now)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", help="JSON object; stdin when omitted")
    args = parser.parse_args()
    raw = args.input_json if args.input_json is not None else input()
    request = json.loads(raw)
    if not isinstance(request, dict):
        raise SystemExit("input must be a JSON object")
    action = request.pop("action", "plan")
    try:
        result = plan_review_batch(**request) if action == "plan" else consolidate_findings(request.get("findings", []))
    except (ReviewBatchError, TypeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
