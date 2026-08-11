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


def _finding_id(item: dict[str, Any]) -> str:
    impact = item.get("impact")
    if isinstance(impact, dict) and impact.get("id"):
        return str(impact["id"]).strip()
    return str(item.get("id") or "").strip()


def normalize_review_batch(receipts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    raw_receipts = list(receipts or [])
    if raw_receipts and not 2 <= len(raw_receipts) <= 3:
        raise ReviewBatchError("review_batch requires between 2 and 3 prism receipts")
    normalized: list[dict[str, Any]] = []
    seen_prisms: set[str] = set()
    seen_reviewers: set[str] = set()
    for raw in raw_receipts:
        item = dict(raw)
        prism = str(item.get("prism") or "")
        reviewer_id = str(item.get("reviewer_id") or "")
        status = str(item.get("status") or "").upper()
        evidence = str(item.get("evidence") or "").strip()
        raw_finding_ids = item.get("finding_ids")
        if not isinstance(raw_finding_ids, list):
            raise ReviewBatchError(f"review prism {prism or '<unknown>'} requires finding_ids array")
        finding_ids = [str(value).strip() for value in raw_finding_ids]
        if any(not value for value in finding_ids) or len(finding_ids) != len(set(finding_ids)):
            raise ReviewBatchError(f"review prism {prism or '<unknown>'} finding_ids must be unique non-empty strings")
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
        normalized.append({"prism": prism, "reviewer_id": reviewer_id, "status": status, "evidence": evidence, "finding_ids": finding_ids})
    return normalized


def review_batch_consistency_errors(payload: dict[str, Any]) -> list[str]:
    """Cross-field checks consumed by the installed schema validator/runtime path."""
    raw_batch = payload.get("review_batch")
    if raw_batch is None:
        return []
    try:
        batch = normalize_review_batch(raw_batch)
    except ReviewBatchError as exc:
        return [str(exc)]

    errors: list[str] = []
    root_reviewer = str(payload.get("reviewer_id") or "")
    batch_reviewers = {item["reviewer_id"] for item in batch}
    if root_reviewer and root_reviewer in batch_reviewers:
        errors.append("ADVERSARIAL consolidator reviewer_id must be distinct from batch reviewers")

    immediate_ids = {_finding_id(item) for item in payload.get("findings", [])}
    deferred_ids = {_finding_id(item) for item in payload.get("deferred_findings", [])}
    immediate_ids.discard("")
    deferred_ids.discard("")
    known_ids = immediate_ids | deferred_ids
    mapped_ids = {finding_id for item in batch for finding_id in item["finding_ids"]}
    unknown_ids = sorted(mapped_ids - known_ids)
    if unknown_ids:
        errors.append(f"review_batch finding_ids reference unknown findings: {unknown_ids}")
    missing_blocking = sorted(immediate_ids - mapped_ids)
    if missing_blocking:
        errors.append(f"every blocking finding must be attributed to a review prism: {missing_blocking}")

    for item in batch:
        if item["status"] in {"CORRIGIR", "BLOQUEADO"} and not (set(item["finding_ids"]) & immediate_ids):
            errors.append(f"review prism {item['prism']} with status {item['status']} must reference at least one blocking finding")

    statuses = {item["status"] for item in batch}
    root_status = str(payload.get("status") or "")
    if "BLOQUEADO" in statuses and root_status != "BLOQUEADO":
        errors.append("ADVERSARIAL cannot downgrade a BLOQUEADO review prism")
    elif "CORRIGIR" in statuses and root_status == "SATISFEITO":
        errors.append("ADVERSARIAL cannot be SATISFEITO while a review prism requires correction")
    return errors


def consolidate_findings(findings: list[dict[str, Any]], review_batch: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fix_now, backlog = partition_findings(findings)
    normalized_batch = normalize_review_batch(review_batch)
    fix_ids = {_finding_id(item) for item in fix_now}
    fix_ids.discard("")
    if normalized_batch:
        affected_prisms = sorted({
            item["prism"]
            for item in normalized_batch
            if fix_ids & set(item["finding_ids"])
        })
    else:
        affected_prisms = sorted({str(item.get("prism") or "") for item in fix_now if str(item.get("prism") or "") in PRISMS})
    return {
        "fix_now": fix_now,
        "backlog": backlog,
        "review_batch": normalized_batch,
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
