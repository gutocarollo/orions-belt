#!/usr/bin/env python3
"""Record actual context-tool calls emitted by Claude Code or Codex hooks.

Every evidence artifact must bind to successful runtime tool-use ids. The
ledger stores both PreToolUse and terminal records, allowing the verifier to
prove actual dependency ordering rather than trusting self-declared stages.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any

LIB = Path(__file__).resolve().parents[1] / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
from context_receipt_fields import definition_ids  # noqa: E402
from context_evidence import repository_fingerprint  # noqa: E402
from secure_runtime_io import open_locked_text  # noqa: E402

MAX_EXCERPT = 16384


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


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def _excerpt(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text[:MAX_EXCERPT]


def _shell_text(tool_name: str, tool_input: Any) -> str:
    lower = tool_name.lower()
    if lower not in {"bash", "exec_command", "shell", "terminal"}:
        return ""
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "script"):
            value = tool_input.get(key)
            if value:
                return _excerpt(value)
    return _excerpt(tool_input)


def _methods(tool_name: str, tool_input: Any) -> list[str]:
    lower = tool_name.lower()
    text = _excerpt(tool_input).lower()
    shell = _shell_text(tool_name, tool_input).lower()
    methods: list[str] = []
    if lower in {"read", "read_file", "readfile"} or re.search(
        r"(?:^|[;&|]\s*)(?:cat|head|tail|sed\s+-n)\b", shell
    ):
        methods.append("targeted-read")
        if re.search(r"(?:^|[\"'/])docs/", text + shell):
            methods.append("canonical-docs")
    if lower in {"grep", "grep_files", "glob", "list_files", "search_files"} or re.search(r"(?:^|\s)(?:rg|grep)(?:\s|$)", shell):
        methods.append("rg")
    if lower.startswith("mcp__codegraph__") or "codegraph" in lower or re.search(r"(?:^|\s)codegraph(?:\s|$)", shell):
        if "status" in lower or re.search(r"(?:^|\s)codegraph\s+status(?:\s|$)", shell):
            methods.append("codegraph-status")
        else:
            methods.append("codegraph")
    if lower.startswith("mcp__serena__") or "lsp" in lower or "typescript-lsp" in lower:
        methods.append("lsp")
    if lower.startswith("mcp__") and any(token in lower for token in ("postgres", "database", "sql", "salesforce")):
        methods.append("live-state")
    return list(dict.fromkeys(methods))


def _identity(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("agent_id") or payload.get("agentId") or ""),
        str(payload.get("agent_type") or payload.get("agentType") or ""),
        str(payload.get("agent_transcript_path") or payload.get("transcript_path") or ""),
    )


def _active_run(root: Path, payload: dict[str, Any]) -> str:
    explicit = str(payload.get("run_id") or "")
    if explicit:
        return explicit
    active = root / ".harness/runs/ACTIVE"
    return active.read_text(encoding="utf-8").strip() if active.is_file() else ""


def _repository_binding(root: Path, run_id: str, payload: dict[str, Any]) -> str:
    explicit = str(payload.get("repository_fingerprint") or "")
    if explicit:
        return explicit
    state_path = root / ".harness/runs/agent-swarm" / run_id / "council-state.json"
    if run_id and state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        value = str(state.get("repository_fingerprint") or "")
        if value:
            return value
    return repository_fingerprint(root)


def record_event(payload: dict[str, Any], runtime: str, root: Path | None = None) -> Path | None:
    """Append one canonical hook event and return the receipt path.

    Runtime hooks call this through ``main``; unit tests call it directly to
    avoid turning every evidence assertion into a slow subprocess benchmark.
    """
    if runtime not in {"claude", "codex"}:
        raise ValueError(f"unsupported runtime: {runtime}")
    if not isinstance(payload, dict):
        raise ValueError("hook input must be an object")
    event = str(payload.get("hook_event_name") or "")
    if event not in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
        return None
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    tool_input = payload.get("tool_input") if "tool_input" in payload else payload.get("toolInput")
    methods = _methods(tool_name, tool_input)
    if not methods:
        return None
    tool_use_id = str(payload.get("tool_use_id") or payload.get("toolUseId") or "")
    if not tool_use_id:
        raise ValueError("context tool receipt requires runtime tool_use_id")
    agent_id, agent_type, transcript = _identity(payload)
    response = payload.get("tool_response") if "tool_response" in payload else payload.get("toolResponse")
    resolved_root = (root or _root(payload)).resolve()
    session = _slug(str(payload.get("session_id") or "unknown"))
    run_id = _active_run(resolved_root, payload)
    repository_binding = _repository_binding(resolved_root, run_id, payload)
    record = {
        "ts": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "time_ns": time.time_ns(),
        "runtime": runtime,
        "run_id": run_id,
        "repository_fingerprint": repository_binding,
        "event": event,
        "session_id": str(payload.get("session_id") or ""),
        "turn_id": payload.get("turn_id"),
        "agent_id": agent_id,
        "agent_type": agent_type,
        "transcript_path": transcript,
        "model": payload.get("model"),
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "methods": methods,
        "success": event == "PostToolUse",
        "input_sha256": hashlib.sha256(_canonical_json(tool_input)).hexdigest(),
        "output_sha256": hashlib.sha256(_canonical_json(response)).hexdigest() if response is not None else None,
        "input_excerpt": _excerpt(tool_input),
        "response_excerpt": _excerpt(response) if event == "PostToolUse" else "",
        "definition_ids": definition_ids(response) if event == "PostToolUse" else [],
        "error_excerpt": _excerpt(payload.get("error") or response) if event == "PostToolUseFailure" else "",
    }
    with open_locked_text(
        resolved_root, (".harness", "runs", "context-tools", session), "tools.jsonl"
    ) as (path, stream):
        stream.seek(0)
        existing = [json.loads(line) for line in stream if line.strip()]
        identity = (runtime, run_id, record["session_id"], tool_use_id, event)
        if any(
            (item.get("runtime"), item.get("run_id"), item.get("session_id"), item.get("tool_use_id"), item.get("event")) == identity
            for item in existing
        ):
            return path
        record["seq"] = len(existing) + 1
        stream.seek(0, 2)
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=("claude", "codex"), required=True)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        path = record_event(payload, args.runtime)
        methods = _methods(
            str(payload.get("tool_name") or payload.get("toolName") or ""),
            payload.get("tool_input") if "tool_input" in payload else payload.get("toolInput"),
        )
        if (
            path is not None
            and payload.get("hook_event_name") == "PostToolUse"
            and methods == ["codegraph-status"]
            and not any(payload.get(key) for key in ("agent_id", "agentId", "agent_type", "agentType"))
        ):
            session_id = str(payload.get("session_id") or "")
            transcript = str(payload.get("transcript_path") or "")
            command = (
                "python3 .harness/lib/codex_context_receipts.py "
                f"--session-id {shlex.quote(session_id)}"
                + (f" --parent-transcript {shlex.quote(transcript)}" if transcript else "")
            )
            message = (
                f"CONTEXT-DELIVERY coordinator receipt: session_id={session_id}; "
                f"tool_receipt={path}. After wait_agent completes, run exactly: {command}"
            )
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}))
        else:
            print("{}")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"context tool ledger failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
