#!/usr/bin/env python3
"""Plan proportional execution-review batches without adding Council states."""
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from council_findings import FindingPolicyError, partition_findings

EXECUTION_PROFILES = ("DIRECT", "LIGHT", "FULL")
REVIEW_MODES = ("AUTO", "SINGLE", "BATCH", "FULL")
PRISMS = (
    "correctness-security-data",
    "tests-acceptance-regression",
    "simplicity-maintainability",
)
REVIEWER_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ReviewBatchError(ValueError):
    """Invalid review-profile request."""


def _enum(value: str, allowed: tuple[str, ...], label: str) -> str:
    normalized = str(value or "").upper().strip()
    if normalized not in allowed:
        raise ReviewBatchError(f"unsupported {label}: {value!r}")
    return normalized


def _single(profile: str, requested: str) -> dict[str, Any]:
    return {
        "execution_profile": profile,
        "requested_mode": requested,
        "effective_mode": "SINGLE",
        "parallel": False,
        "prisms": ["correctness-security-data"],
        "max_reviewers": 1,
        "max_batches": 1,
        "requires_profile_escalation": None,
    }


def plan_review_batch(*, execution_profile: str, review_mode: str = "AUTO", prisms: list[str] | None = None) -> dict[str, Any]:
    profile = _enum(execution_profile, EXECUTION_PROFILES, "execution_profile")
    requested = _enum(review_mode, REVIEW_MODES, "review_mode")

    if profile == "DIRECT" and requested == "AUTO":
        return {"execution_profile": profile, "requested_mode": requested, "effective_mode": "NONE", "parallel": False, "prisms": [], "max_reviewers": 0, "max_batches": 0, "requires_profile_escalation": None}

    if requested == "FULL":
        return {"execution_profile": profile, "requested_mode": requested, "effective_mode": "FULL", "parallel": False, "prisms": [], "max_reviewers": 2, "max_batches": 1, "requires_profile_escalation": None if profile == "FULL" else "FULL"}

    if requested == "AUTO":
        requested = "BATCH" if profile == "FULL" else "SINGLE"

    if requested == "SINGLE":
        return _single(profile, review_mode.upper())

    selected = list(dict.fromkeys(prisms or PRISMS))
    unknown = [item for item in selected if item not in PRISMS]
    if unknown:
        raise ReviewBatchError(f"unknown review prisms: {unknown}")
    limit = 3 if profile == "FULL" else 2
    selected = selected[:limit]
    if len(selected) < 2:
        return _single(profile, review_mode.upper())
    return {"execution_profile": profile, "requested_mode": review_mode.upper(), "effective_mode": "BATCH", "parallel": True, "prisms": selected, "max_reviewers": len(selected), "max_batches": 1, "requires_profile_escalation": None}


def normalize_review_batch(receipts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_prisms: set[str] = set()
    seen_reviewers: set[str] = set()
    for raw in receipts or []:
        item = dict(raw)
        prism = str(item.get("prism") or "")
        reviewer_id = str(item.get("reviewer_id") or "")
        status = str(item.get("status") or "").upper()
        evidence = str(item.get("evidence") or "").strip()
        if prism not in PRISMS:
            raise ReviewBatchError(f"unknown review prism: {prism!r}")
        if not REVIEWER_ID_RE.fullmatch(reviewer_id):
            raise ReviewBatchError(f"invalid reviewer_id for prism {prism}: {reviewer_id!r}")
        if status not in {"SATISFEITO", "CORRIGIR", "BLOQUEADO"}:
            raise ReviewBatchError(f"invalid review status for prism {prism}: {status!r}")
        if not evidence:
            raise ReviewBatchError(f"review prism {prism} requires evidence")
        if prism in seen_prisms or reviewer_id in seen_reviewers:
            raise ReviewBatchError("review_batch requires unique prisms and reviewer identities")
        seen_prisms.add(prism)
        seen_reviewers.add(reviewer_id)
        normalized.append({"prism": prism, "reviewer_id": reviewer_id, "status": status, "evidence": evidence})
    return normalized


def consolidate_findings(findings: list[dict[str, Any]], review_batch: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fix_now, backlog = partition_findings(findings)
    affected_prisms = sorted({str(item.get("prism") or "") for item in fix_now if str(item.get("prism") or "") in PRISMS})
    return {
        "fix_now": fix_now,
        "backlog": backlog,
        "review_batch": normalize_review_batch(review_batch),
        "targeted_recheck_prisms": affected_prisms,
        "requires_recheck": bool(fix_now),
    }


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
        result = plan_review_batch(**request) if action == "plan" else consolidate_findings(request.get("findings", []), request.get("review_batch"))
    except (ReviewBatchError, FindingPolicyError, TypeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
