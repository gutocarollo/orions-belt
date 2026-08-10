#!/usr/bin/env python3
"""AI-first execution-profile policy for Orion's Belt.

DIRECT and LIGHT are intentionally soft orchestration profiles. FULL is the
only profile that requires the enforceable Council state machine. Deterministic
logic here provides only a narrow safety floor; scope/complexity trade-offs stay
with the orchestrating model.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

PROFILES = ("AUTO", "DIRECT", "LIGHT", "FULL")
RANK = {"DIRECT": 0, "LIGHT": 1, "FULL": 2}
PROFILE_BUDGETS = {
    "DIRECT": {"max_subagents": 0, "max_parallel_subagents": 0, "max_reviewers": 0, "context_turn_budget": 0, "context_strategy": "targeted-inline"},
    "LIGHT": {"max_subagents": 2, "max_parallel_subagents": 2, "max_reviewers": 1, "context_turn_budget": 8, "context_strategy": "inline-or-one-cheap-scout"},
    "FULL": {"max_subagents": 4, "max_parallel_subagents": 4, "max_reviewers": 3, "context_turn_budget": 16, "context_strategy": "context-delivery"},
}
HARD_FULL_SIGNALS = (
    "production_or_deploy",
    "destructive_or_irreversible",
    "data_migration_or_backfill",
    "security_privacy_or_credentials",
    "irreversible_business_decision",
    "explicit_high_assurance",
)
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH"}


class ProfileError(ValueError):
    """Invalid profile request or signal bundle."""


def _profile(value: str, *, allow_auto: bool) -> str:
    normalized = str(value or "").upper().strip()
    allowed = PROFILES if allow_auto else PROFILES[1:]
    if normalized not in allowed:
        raise ProfileError(f"unsupported execution profile: {value!r}")
    return normalized


def choose_profile(*, requested_profile: str = "AUTO", ai_choice: str | None = None, signals: dict[str, Any] | None = None, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    requested = _profile(requested_profile, allow_auto=True)
    proposed = _profile(ai_choice or "DIRECT", allow_auto=False) if requested == "AUTO" else requested
    signal_map = {key: bool(value) for key, value in (signals or {}).items()}
    hard_signals = [key for key in HARD_FULL_SIGNALS if signal_map.get(key)]
    minimum = "FULL" if hard_signals else "DIRECT"
    effective = proposed if RANK[proposed] >= RANK[minimum] else minimum
    fix_now, backlog = [], []
    for raw in findings or []:
        item = dict(raw)
        severity = str(item.get("severity") or "LOW").upper()
        reachable = bool(item.get("reachable_in_current_task", True))
        item["severity"], item["reachable_in_current_task"] = severity, reachable
        (fix_now if severity in BLOCKING_SEVERITIES and reachable else backlog).append(item)
    return {
        "requested_profile": requested,
        "ai_choice": proposed,
        "minimum_profile": minimum,
        "effective_profile": effective,
        "hard_full_signals": hard_signals,
        "budgets": dict(PROFILE_BUDGETS[effective]),
        "fix_now": fix_now,
        "backlog": backlog,
        "requires_profile_reassessment": bool(fix_now),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", help="JSON object; stdin when omitted")
    args = parser.parse_args()
    raw = args.input_json if args.input_json is not None else input()
    request = json.loads(raw)
    if not isinstance(request, dict):
        raise SystemExit("input must be a JSON object")
    try:
        result = choose_profile(**request)
    except (ProfileError, TypeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
