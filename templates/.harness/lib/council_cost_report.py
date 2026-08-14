#!/usr/bin/env python3
"""Observational Council cost report; never a delivery gate."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _usage_value(usage: Any, *keys: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _agent_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("runtime") or "unknown"),
        str(row.get("session_id") or ""),
        str(row.get("agent_id") or "unknown"),
    )


def _metric_score(row: dict[str, Any]) -> tuple[int, int]:
    usage = row.get("usage")
    completeness = int(_usage_value(usage, "input_tokens", "inputTokens") is not None) + int(
        _usage_value(usage, "output_tokens", "outputTokens") is not None
    )
    event_priority = {
        "AgentToolResult": 3,
        "SubagentStop": 2,
        "AgentToolFailure": 1,
        "SubagentStart": 0,
    }.get(str(row.get("event") or ""), 0)
    return completeness, event_priority


def build_report(root: Path, *, run_id: str | None = None, profile: str | None = None) -> dict[str, Any]:
    runs = root / ".harness/runs"
    lifecycle_paths = sorted((runs / "subagents").glob("*/*.jsonl")) if (runs / "subagents").is_dir() else []
    cost_paths = sorted((runs / "subagent-cost").glob("*/events.jsonl")) if (runs / "subagent-cost").is_dir() else []
    tool_paths = sorted((runs / "context-tools").glob("*/tools.jsonl")) if (runs / "context-tools").is_dir() else []
    lifecycle = _rows(lifecycle_paths)
    cost_rows = _rows(cost_paths)
    tools = _rows(tool_paths)
    if run_id:
        lifecycle = [row for row in lifecycle if str(row.get("run_id") or "") == run_id]
        cost_rows = [row for row in cost_rows if str(row.get("run_id") or "") == run_id]
        tools = [row for row in tools if str(row.get("run_id") or "") == run_id]

    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in lifecycle + cost_rows:
        key = (*_agent_key(row), str(row.get("event") or ""))
        merged[key] = row
    rows = list(merged.values())

    agents: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = _agent_key(row)
        state = agents.setdefault(key, {"events": set(), "model": None, "role": None, "metric_row": None})
        state["events"].add(str(row.get("event") or ""))
        model = row.get("model") or row.get("configured_model")
        role = row.get("agent_type")
        if model:
            state["model"] = str(model)
        if role:
            state["role"] = str(role)
        current = state.get("metric_row")
        if current is None or _metric_score(row) > _metric_score(current):
            state["metric_row"] = row

    input_tokens, output_tokens, durations = [], [], []
    terminal_agents = 0
    for state in agents.values():
        events = state["events"]
        if events & {"AgentToolResult", "AgentToolFailure", "SubagentStop"}:
            terminal_agents += 1
        row = state.get("metric_row") or {}
        iv = _usage_value(row.get("usage"), "input_tokens", "inputTokens")
        ov = _usage_value(row.get("usage"), "output_tokens", "outputTokens")
        if iv is not None:
            input_tokens.append(iv)
        if ov is not None:
            output_tokens.append(ov)
        duration = row.get("duration_ms")
        if isinstance(duration, (int, float)) and duration >= 0:
            durations.append(float(duration))

    models = Counter(str(state.get("model") or "unknown") for state in agents.values())
    roles = Counter(str(state.get("role") or "unknown") for state in agents.values())
    posts = [row for row in tools if row.get("event") == "PostToolUse"]
    ledger_bytes = sum(path.stat().st_size for path in lifecycle_paths + cost_paths + tool_paths if path.is_file())
    metric_scope = "ALL_SUBAGENTS" if cost_rows else ("CONTEXT_ONLY_LEGACY" if lifecycle else "UNAVAILABLE")

    return {
        "schema_version": "1.1",
        "run_id": run_id or "ALL",
        "profile": (profile or "UNKNOWN").upper(),
        "blocking": False,
        "observed": {
            "subagents_started": len(agents),
            "subagents_observed": len(agents),
            "agent_results": terminal_agents,
            "tool_calls": len(posts),
            "context_tool_calls": len(posts),
            "models": dict(sorted(models.items())),
            "roles": dict(sorted(roles.items())),
            "metric_scope": metric_scope,
            "token_usage": {
                "input_tokens": sum(input_tokens),
                "output_tokens": sum(output_tokens),
                "records_with_input_tokens": len(input_tokens),
                "records_with_output_tokens": len(output_tokens),
                "source": "OBSERVED" if input_tokens or output_tokens else "UNAVAILABLE",
            },
            "duration": {
                "subagent_duration_ms": round(sum(durations), 3),
                "records_with_duration": len(durations),
                "source": "OBSERVED" if durations else "UNAVAILABLE",
            },
            "ledger_bytes": ledger_bytes,
        },
        "limitations": [
            "Parent-model tokens are unavailable unless the runtime emits them into receipts.",
            "Runs created before the all-subagent cost ledger may remain CONTEXT_ONLY_LEGACY.",
            "tool_calls/context_tool_calls count Context Delivery tool receipts, not every runtime tool call.",
            "Missing runtime metrics remain UNAVAILABLE; they are never inferred as zero consumption.",
            "This report is observational and is not a delivery gate.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--run-id")
    parser.add_argument("--profile")
    args = parser.parse_args()
    print(json.dumps(build_report(args.root.resolve(), run_id=args.run_id, profile=args.profile), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
