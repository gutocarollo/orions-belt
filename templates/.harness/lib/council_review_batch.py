#!/usr/bin/env python3
"""Plan proportional execution-review batches without adding Council states."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
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
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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


def _finding_uid(item: dict[str, Any]) -> str:
    return str(item.get("finding_uid") or "").strip()


def normalize_review_batch(receipts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    raw_receipts = list(receipts or [])
    if raw_receipts and not 2 <= len(raw_receipts) <= 3:
        raise ReviewBatchError("review_batch requires between 2 and 3 prism receipts")
    normalized: list[dict[str, Any]] = []
    seen_prisms: set[str] = set()
    seen_reviewers: set[str] = set()
    for raw in raw_receipts:
        if not isinstance(raw, dict):
            raise ReviewBatchError("review_batch receipts must be objects")
        item = dict(raw)
        prism = str(item.get("prism") or "")
        reviewer_id = str(item.get("reviewer_id") or "")
        status = str(item.get("status") or "").upper()
        evidence = str(item.get("evidence") or "").strip()
        raw_finding_uids = item.get("finding_uids")
        if not isinstance(raw_finding_uids, list):
            raise ReviewBatchError(f"review prism {prism or '<unknown>'} requires finding_uids array")
        finding_uids = [str(value).strip() for value in raw_finding_uids]
        if any(not value for value in finding_uids) or len(finding_uids) != len(set(finding_uids)):
            raise ReviewBatchError(f"review prism {prism or '<unknown>'} finding_uids must be unique non-empty strings")
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
        normalized.append(
            {
                "prism": prism,
                "reviewer_id": reviewer_id,
                "status": status,
                "evidence": evidence,
                "finding_uids": finding_uids,
            }
        )
    return normalized


def _project_root() -> Path:
    explicit = os.environ.get("HARNESS_PROJECT_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
    if explicit:
        return Path(explicit).resolve()
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".harness").is_dir() or (candidate / ".git").exists():
            return candidate
    return cwd


def _active_council_state(root: Path) -> dict[str, Any] | None:
    pointer = root / ".harness/council-active"
    if not pointer.is_file():
        return None
    try:
        state_path = Path(pointer.read_text(encoding="utf-8").strip())
        if not state_path.is_absolute():
            state_path = (root / state_path).resolve()
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _all_runtime_lifecycle_rows(root: Path) -> list[dict[str, Any]]:
    ledger_root = root / ".harness/runs/subagent-cost"
    if not ledger_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(ledger_root.glob("*/events.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def review_batch_runtime_binding_errors(payload: dict[str, Any], batch: list[dict[str, Any]]) -> list[str]:
    """Bind batch reviewers to real completed subagents from the same run/session/snapshot."""
    if not batch:
        return []
    errors: list[str] = []
    run_id = str(payload.get("run_id") or "").strip()
    implementer_id = str(payload.get("implementer_id") or "").strip()
    snapshot_sha = str(payload.get("snapshot_sha") or "").strip()
    if not run_id:
        errors.append("review_batch requires run_id")
    if not implementer_id:
        errors.append("review_batch requires implementer_id")
    if not SHA_RE.fullmatch(snapshot_sha):
        errors.append("review_batch requires a full lowercase snapshot_sha")
    if errors:
        return errors

    root = _project_root()
    active_state = _active_council_state(root)
    if active_state is not None:
        if str(active_state.get("run_id") or "") != run_id:
            errors.append("review_batch run_id differs from the active Council state")
        if str(active_state.get("implementer_id") or "") != implementer_id:
            errors.append("review_batch implementer_id differs from the active Council state")

    lifecycle = _all_runtime_lifecycle_rows(root)
    reviewer_sessions: list[set[str]] = []
    for item in batch:
        reviewer_id = item["reviewer_id"]
        prism = item["prism"]
        if reviewer_id == implementer_id:
            errors.append(f"review prism {prism} cannot use the Council implementer as reviewer")
            continue
        matches = [
            row for row in lifecycle
            if str(row.get("run_id") or "") == run_id
            and str(row.get("agent_id") or "") == reviewer_id
            and str(row.get("agent_id_source") or "") == "runtime"
            and str(row.get("snapshot_sha") or "") == snapshot_sha
            and str(row.get("event") or "") in {"AgentToolResult", "SubagentStop"}
            and str(row.get("session_id") or "")
        ]
        if not matches:
            errors.append(
                f"review prism {prism} has no successful runtime lifecycle receipt for reviewer "
                f"{reviewer_id} in run/snapshot"
            )
            continue
        reviewer_sessions.append({str(row["session_id"]) for row in matches})

    if len(reviewer_sessions) == len(batch):
        common_sessions = set.intersection(*reviewer_sessions)
        if not common_sessions:
            errors.append("review_batch reviewers must belong to the same runtime session")
    return errors


def review_batch_consistency_errors(payload: dict[str, Any]) -> list[str]:
    """Cross-field and runtime receipt checks consumed by the installed schema validator."""
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

    immediate = list(payload.get("findings", []))
    deferred = list(payload.get("deferred_findings", []))
    all_findings = immediate + deferred
    finding_uids = [_finding_uid(item) for item in all_findings if isinstance(item, dict)]
    if any(not value for value in finding_uids):
        errors.append("every batched finding must define finding_uid")
    duplicates = sorted({value for value in finding_uids if finding_uids.count(value) > 1 and value})
    if duplicates:
        errors.append(f"finding_uid values must be globally unique: {duplicates}")

    immediate_uids = {_finding_uid(item) for item in immediate if isinstance(item, dict)}
    deferred_uids = {_finding_uid(item) for item in deferred if isinstance(item, dict)}
    immediate_uids.discard("")
    deferred_uids.discard("")
    known_uids = immediate_uids | deferred_uids
    mapped_uids = {finding_uid for item in batch for finding_uid in item["finding_uids"]}
    unknown_uids = sorted(mapped_uids - known_uids)
    if unknown_uids:
        errors.append(f"review_batch finding_uids reference unknown findings: {unknown_uids}")
    missing_blocking = sorted(immediate_uids - mapped_uids)
    if missing_blocking:
        errors.append(f"every blocking finding must be attributed to a review prism: {missing_blocking}")

    for item in batch:
        if item["status"] in {"CORRIGIR", "BLOQUEADO"} and not (set(item["finding_uids"]) & immediate_uids):
            errors.append(f"review prism {item['prism']} with status {item['status']} must reference at least one blocking finding")

    statuses = {item["status"] for item in batch}
    root_status = str(payload.get("status") or "")
    if "BLOQUEADO" in statuses and root_status != "BLOQUEADO":
        errors.append("ADVERSARIAL cannot downgrade a BLOQUEADO review prism")
    elif "CORRIGIR" in statuses and root_status == "SATISFEITO":
        errors.append("ADVERSARIAL cannot be SATISFEITO while a review prism requires correction")

    errors.extend(review_batch_runtime_binding_errors(payload, batch))
    return errors


def consolidate_findings(findings: list[dict[str, Any]], review_batch: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fix_now, backlog = partition_findings(findings)
    normalized_batch = normalize_review_batch(review_batch)
    fix_uids = {_finding_uid(item) for item in fix_now}
    fix_uids.discard("")
    if normalized_batch:
        if len(fix_uids) != len(fix_now):
            raise ReviewBatchError("batched blocking findings require globally unique finding_uid values")
        affected_prisms = sorted(
            {
                item["prism"]
                for item in normalized_batch
                if fix_uids & set(item["finding_uids"])
            }
        )
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
