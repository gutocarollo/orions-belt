#!/usr/bin/env python3
"""Append auditable lifecycle records for context subagents."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

CONTEXT_SUFFIXES = ("-context-scout", "-context-shard")


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


def _definition(root: Path, runtime: str, agent_type: str) -> tuple[str, str, str]:
    if runtime == "claude":
        path = root / ".claude/agents" / f"{agent_type}.md"
        if not path.is_file():
            raise ValueError(f"missing Claude agent definition: {path.relative_to(root)}")
        content = path.read_bytes()
        match = re.search(rb"(?m)^model:\s*([^\s#]+)", content)
        if not match:
            raise ValueError(f"missing Claude agent model: {path.relative_to(root)}")
        model = match.group(1).decode()
    else:
        path = root / ".codex/agents" / f"{agent_type}.toml"
        if not path.is_file():
            raise ValueError(f"missing Codex agent definition: {path.relative_to(root)}")
        content = path.read_bytes()
        model = str(tomllib.loads(content.decode()).get("model", ""))
        if not model:
            raise ValueError(f"missing Codex agent model: {path.relative_to(root)}")
    return path.relative_to(root).as_posix(), hashlib.sha256(content).hexdigest(), model


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=("claude", "codex"), required=True)
    parser.add_argument("--observe-agent-tool", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        args = _args()
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be an object")
        hook_event = str(payload.get("hook_event_name", ""))
        tool_response: dict[str, Any] = {}

        if args.observe_agent_tool:
            if hook_event != "PostToolUse" or str(payload.get("tool_name", "")) not in {"Agent", "Task"}:
                return 0
            tool_input = payload.get("tool_input") or {}
            if not isinstance(tool_input, dict):
                return 0
            agent_type = str(tool_input.get("subagent_type") or tool_input.get("agent_type") or "")
            if not agent_type.endswith(CONTEXT_SUFFIXES):
                return 0
            tool_response = payload.get("tool_response") or {}
            if not isinstance(tool_response, dict):
                raise ValueError("context Agent PostToolUse requires structured tool_response")
            agent_id = str(tool_response.get("agentId") or tool_response.get("agent_id") or "")
            model = str(tool_response.get("resolvedModel") or tool_response.get("resolved_model") or "")
            if not agent_id or not model:
                raise ValueError("context Agent PostToolUse requires agentId and resolvedModel")
            event = "AgentToolResult"
        else:
            event = hook_event
            if event not in {"SubagentStart", "SubagentStop"}:
                return 0
            agent_type = str(payload.get("agent_type") or "")
            if not agent_type.endswith(CONTEXT_SUFFIXES):
                return 0
            agent_id = str(payload.get("agent_id") or "")
            model = str(payload.get("model") or "")
            if not agent_id:
                raise ValueError("context lifecycle event requires agent_id")

        root = _root(payload)
        definition_path, definition_sha, configured_model = _definition(root, args.runtime, agent_type)
        session_id = _slug(str(payload.get("session_id") or "unknown"))
        folder = root / ".harness/runs/subagents" / session_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_slug(agent_id)}.jsonl"
        message = payload.get("last_assistant_message")
        record = {
            "ts": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "runtime": args.runtime,
            "event": event,
            "session_id": str(payload.get("session_id") or ""),
            "agent_id": agent_id,
            "agent_type": agent_type,
            "model": model or None,
            "configured_model": configured_model,
            "agent_definition_path": definition_path,
            "agent_definition_sha256": definition_sha,
            "transcript_path": payload.get("transcript_path"),
            "agent_transcript_path": payload.get("agent_transcript_path"),
            "last_message_sha256": hashlib.sha256(message.encode()).hexdigest() if isinstance(message, str) else None,
            "usage": tool_response.get("usage") if tool_response else None,
        }
        with path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
        if event == "SubagentStart":
            relative = path.relative_to(root).as_posix()
            context = (
                "CONTEXT-DELIVERY receipt: preserve agent_id=" + agent_id
                + "; agent_type=" + agent_type
                + "; runtime=" + args.runtime
                + "; lifecycle_receipt_path=" + relative
                + ". The parent hashes the receipt after SubagentStop."
            )
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": context}}))
        else:
            print("{}")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"subagent lifecycle ledger failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
