#!/usr/bin/env python3
"""Shared finding classification for proportional Council orchestration."""
from __future__ import annotations

from typing import Any

from objective_control import ObjectiveControlError, assess_impact

BLOCKING_DISPOSITIONS = {"CRITICAL_BLOCK", "HIGH_FIX_NOW"}
SEVERITY_ALIASES = {
    "CRITICAL": "CRITICAL",
    "BLOCKING": "CRITICAL",
    "HIGH": "HIGH",
    "REQUIRED": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFO": "LOW",
}


class FindingPolicyError(ValueError):
    """A finding cannot be classified without silently weakening its impact."""


def classify_finding(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one finding while preferring the canonical Council impact contract."""
    item = dict(raw)
    impact = item.get("impact")
    if isinstance(impact, dict):
        try:
            assessed = assess_impact(impact)
        except ObjectiveControlError as exc:
            raise FindingPolicyError(str(exc)) from exc
        disposition = assessed["disposition"]
        severity = {
            "CRITICAL_BLOCK": "CRITICAL",
            "HIGH_FIX_NOW": "HIGH",
            "DEFER_RUN": "LOW",
        }[disposition]
        item["impact"] = assessed
        item["severity"] = severity
        item["reachable_in_current_task"] = disposition in BLOCKING_DISPOSITIONS
        item["classification_source"] = "canonical-impact"
        item["disposition"] = disposition
        item["fix_now"] = disposition in BLOCKING_DISPOSITIONS
        return item

    severity_raw = str(item.get("severity") or "LOW").upper().strip()
    if severity_raw not in SEVERITY_ALIASES:
        raise FindingPolicyError(f"unsupported finding severity: {severity_raw!r}")
    severity = SEVERITY_ALIASES[severity_raw]
    reachable = bool(item.get("reachable_in_current_task", True))
    item["severity"] = severity
    item["reachable_in_current_task"] = reachable
    item["classification_source"] = "lightweight-severity"
    item["fix_now"] = severity in {"CRITICAL", "HIGH"} and reachable
    return item


def partition_findings(findings: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return FIX_NOW and backlog without deduplicating independent reviewers."""
    fix_now: list[dict[str, Any]] = []
    backlog: list[dict[str, Any]] = []
    for raw in findings or []:
        item = classify_finding(raw)
        (fix_now if item["fix_now"] else backlog).append(item)
    return fix_now, backlog
