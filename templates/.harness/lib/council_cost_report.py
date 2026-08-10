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


def build_report(root: Path, *, run_id: str | None = None, profile: str | None = None) -> dict[str, Any]:
    runs = root / ".harness/runs"
    lifecycle_paths = sorted((runs / "subagents").glob("*/*.jsonl")) if (runs / "subagents").is_dir() else []
    tool_paths = sorted((runs / "context-tools").glob("*/tools.jsonl")) if (runs / "context-tools").is_dir() else []
    lifecycle, tools = _rows(lifecycle_paths), _rows(tool_paths)
    if run_id:
        lifecycle = [row for row in lifecycle if str(row.get("run_id") or "") == run_id]
        tools = [row for row in tools if str(row.get("run_id") or "") == run_id]
    results = [row for row in lifecycle if row.get("event") == "AgentToolResult"]
    starts = [row for row in lifecycle if row.get("event") == "SubagentStart"]
    posts = [row for row in tools if row.get("event") == "PostToolUse"]
    input_tokens, output_tokens, durations = [], [], []
    for row in results:
        iv = _usage_value(row.get("usage"), "input_tokens", "inputTokens")
        ov = _usage_value(row.get("usage"), "output_tokens", "outputTokens")
        if iv is not None: input_tokens.append(iv)
        if ov is not None: output_tokens.append(ov)
        duration = row.get("duration_ms")
        if isinstance(duration, (int, float)) and duration >= 0: durations.append(float(duration))
    models = Counter(str(row.get("model") or row.get("configured_model") or "unknown") for row in starts)
    roles = Counter(str(row.get("agent_type") or "unknown") for row in starts)
    ledger_bytes = sum(path.stat().st_size for path in lifecycle_paths + tool_paths if path.is_file())
    return {
        "schema_version": "1.0", "run_id": run_id or "ALL", "profile": (profile or "UNKNOWN").upper(), "blocking": False,
        "observed": {
            "subagents_started": len(starts), "agent_results": len(results), "tool_calls": len(posts),
            "models": dict(sorted(models.items())), "roles": dict(sorted(roles.items())),
            "token_usage": {"input_tokens": sum(input_tokens), "output_tokens": sum(output_tokens), "records_with_input_tokens": len(input_tokens), "records_with_output_tokens": len(output_tokens), "source": "OBSERVED" if input_tokens or output_tokens else "UNAVAILABLE"},
            "duration": {"subagent_duration_ms": round(sum(durations), 3), "records_with_duration": len(durations), "source": "OBSERVED" if durations else "UNAVAILABLE"},
            "ledger_bytes": ledger_bytes,
        },
        "limitations": [
            "Parent-model tokens are unavailable unless the runtime emits them into receipts.",
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
