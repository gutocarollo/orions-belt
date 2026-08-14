#!/usr/bin/env python3
"""Append lightweight, non-blocking cost/lifecycle receipts for every completed subagent.

This ledger is observational for cost reporting and also provides the minimal
runtime identity receipt consumed by FULL review batches. It never stores
prompts, responses or tool payload excerpts. Telemetry failures remain
fail-open; a FULL batch that requires an identity receipt must simply choose
SINGLE or obtain a valid receipt instead of fabricating one.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

LIB = Path(__file__).resolve().parents[1] / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
from secure_runtime_io import open_locked_text  # noqa: E402

AGENT_TOOLS = {"Agent", "Task", "spawn_agent"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _root(payload: dict[str, Any]) -> Path:
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(os.environ["CLAUDE_PROJECT_DIR"]).resolve()
    cwd = Path(str(payload.get("cwd") or Path.cwd())).resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".harness").is_dir() or (candidate / ".git").exists():
            return candidate
    return cwd


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")[:160] or "unknown"


def _runtime(requested: str, payload: dict[str, Any]) -> str:
    if requested in {"claude", "codex"}:
        return requested
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    if os.environ.get("CLAUDE_PROJECT_DIR") or tool_name in {"Agent", "Task"}:
        return "claude"
    return "codex"


def _active_run(root: Path, payload: dict[str, Any]) -> str:
    explicit = str(payload.get("run_id") or "").strip()
    if explicit:
        return explicit
    pointer = root / ".harness/council-active"
    if not pointer.is_file():
        return ""
    try:
        state_path = Path(pointer.read_text(encoding="utf-8").strip())
    except OSError:
        return ""
    if not state_path.is_absolute():
        state_path = (root / state_path).resolve()
    return state_path.parent.name if state_path.name == "council-state.json" else ""


def _usage(payload: dict[str, Any], response: dict[str, Any]) -> Any:
    return response.get("usage") or payload.get("usage")


def _duration(payload: dict[str, Any], response: dict[str, Any]) -> Any:
    for source in (response, payload):
        for key in ("durationMs", "duration_ms"):
            value = source.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return value
    return None


def _snapshot_sha(root: Path, payload: dict[str, Any], response: dict[str, Any]) -> str | None:
    for source in (response, payload):
        value = str(source.get("snapshot_sha") or source.get("head_sha") or "").strip().lower()
        if SHA_RE.fullmatch(value):
            return value
    try:
        process = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = process.stdout.strip().lower()
    return value if process.returncode == 0 and SHA_RE.fullmatch(value) else None


def record_event(payload: dict[str, Any], requested_runtime: str = "auto", root: Path | None = None) -> Path | None:
    if not isinstance(payload, dict):
        return None
    hook_event = str(payload.get("hook_event_name") or "")
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    response = payload.get("tool_response") if "tool_response" in payload else payload.get("toolResponse")
    response = response if isinstance(response, dict) else {}
    tool_input = payload.get("tool_input") if "tool_input" in payload else payload.get("toolInput")
    tool_input = tool_input if isinstance(tool_input, dict) else {}

    if hook_event in {"PostToolUse", "PostToolUseFailure"}:
        if tool_name not in AGENT_TOOLS:
            return None
        event = "AgentToolResult" if hook_event == "PostToolUse" else "AgentToolFailure"
        agent_type = str(tool_input.get("subagent_type") or tool_input.get("agent_type") or tool_input.get("role") or "unknown")
        observed_id = str(response.get("agentId") or response.get("agent_id") or response.get("id") or payload.get("agent_id") or "")
        tool_use_id = str(payload.get("tool_use_id") or payload.get("toolUseId") or "")
        agent_id = observed_id or (f"tool:{tool_use_id}" if tool_use_id else "unknown")
        agent_id_source = "runtime" if observed_id else "tool_use_id"
        model = str(response.get("resolvedModel") or response.get("resolved_model") or response.get("model") or payload.get("model") or "")
    elif hook_event in {"SubagentStart", "SubagentStop"}:
        event = hook_event
        agent_type = str(payload.get("agent_type") or payload.get("agentType") or "unknown")
        agent_id = str(payload.get("agent_id") or payload.get("agentId") or "unknown")
        agent_id_source = "runtime"
        model = str(payload.get("model") or "")
    else:
        return None

    resolved_root = (root or _root(payload)).resolve()
    runtime = _runtime(requested_runtime, payload)
    session_id = _slug(str(payload.get("session_id") or "unknown"))
    record = {
        "ts": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "time_ns": time.time_ns(),
        "runtime": runtime,
        "run_id": _active_run(resolved_root, payload),
        "session_id": str(payload.get("session_id") or ""),
        "event": event,
        "agent_id": agent_id,
        "agent_id_source": agent_id_source,
        "agent_type": agent_type,
        "model": model or None,
        "snapshot_sha": _snapshot_sha(resolved_root, payload, response),
        "usage": _usage(payload, response),
        "duration_ms": _duration(payload, response),
    }
    with open_locked_text(
        resolved_root,
        (".harness", "runs", "subagent-cost", session_id),
        "events.jsonl",
    ) as (path, stream):
        stream.seek(0, 2)
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=("auto", "claude", "codex"), default="auto")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        record_event(payload, args.runtime)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
