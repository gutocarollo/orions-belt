#!/usr/bin/env python3
"""Append auditable Claude/Codex context-subagent lifecycle events."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

LIB = Path(__file__).resolve().parents[1] / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
from context_evidence import repository_fingerprint  # noqa: E402
from secure_runtime_io import open_locked_text  # noqa: E402

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
        match = re.search(rb'(?m)^model\s*=\s*["\']([^"\']+)["\']', content)
        if not match:
            raise ValueError(f"missing Codex agent model: {path.relative_to(root)}")
        model = match.group(1).decode()
    return path.relative_to(root).as_posix(), hashlib.sha256(content).hexdigest(), model


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=("claude", "codex"), required=True)
    parser.add_argument("--observe-agent-tool", action="store_true")
    return parser.parse_args()


def _extract_metrics(payload: dict[str, Any], response: dict[str, Any]) -> tuple[Any, Any]:
    usage = response.get("usage") or payload.get("usage")
    duration = response.get("durationMs") or response.get("duration_ms") or payload.get("duration_ms")
    return usage, duration


def main() -> int:
    try:
        args = _args()
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be an object")
        hook_event = str(payload.get("hook_event_name", ""))
        response: dict[str, Any] = {}

        if args.observe_agent_tool:
            if hook_event != "PostToolUse" or str(payload.get("tool_name", "")) not in {"Agent", "Task", "spawn_agent"}:
                return 0
            tool_input = payload.get("tool_input") or {}
            if not isinstance(tool_input, dict):
                return 0
            agent_type = str(tool_input.get("subagent_type") or tool_input.get("agent_type") or tool_input.get("role") or "")
            if not agent_type.endswith(CONTEXT_SUFFIXES):
                return 0
            response = payload.get("tool_response") or {}
            if not isinstance(response, dict):
                raise ValueError("context agent PostToolUse requires structured tool_response")
            agent_id = str(response.get("agentId") or response.get("agent_id") or response.get("id") or "")
            model = str(response.get("resolvedModel") or response.get("resolved_model") or response.get("model") or "")
            if not agent_id:
                raise ValueError("context agent PostToolUse requires agentId")
            event = "AgentToolResult"
        else:
            event = hook_event
            if event not in {"SubagentStart", "SubagentStop"}:
                return 0
            agent_type = str(payload.get("agent_type") or payload.get("agentType") or "")
            if not agent_type.endswith(CONTEXT_SUFFIXES):
                return 0
            agent_id = str(payload.get("agent_id") or payload.get("agentId") or "")
            # Both current runtimes expose the active model in common hook
            # context. The verifier requires this observation for Codex too.
            model = str(payload.get("model") or "")
            if not agent_id:
                raise ValueError("context lifecycle event requires agent_id")

        root = _root(payload)
        definition_path, definition_sha, configured_model = _definition(root, args.runtime, agent_type)
        session_id = _slug(str(payload.get("session_id") or "unknown"))
        run_id = _active_run(root, payload)
        repository_binding = _repository_binding(root, run_id, payload)
        message = payload.get("last_assistant_message")
        usage, duration = _extract_metrics(payload, response)
        record = {
            "ts": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "runtime": args.runtime,
            "run_id": run_id,
            "repository_fingerprint": repository_binding,
            "event": event,
            "session_id": str(payload.get("session_id") or ""),
            "turn_id": payload.get("turn_id"),
            "agent_id": agent_id,
            "agent_type": agent_type,
            "model": model or None,
            "configured_model": configured_model,
            "agent_definition_path": definition_path,
            "agent_definition_sha256": definition_sha,
            "permission_mode": payload.get("permission_mode"),
            "transcript_path": payload.get("transcript_path"),
            "agent_transcript_path": payload.get("agent_transcript_path"),
            "last_message_chars": len(message) if isinstance(message, str) else 0,
            "last_message_sha256": hashlib.sha256(message.encode()).hexdigest() if isinstance(message, str) else None,
            "usage": usage,
            "duration_ms": duration,
        }
        with open_locked_text(
            root,
            (".harness", "runs", "subagents", session_id),
            f"{_slug(agent_id)}.jsonl",
        ) as (path, stream):
            stream.seek(0)
            existing = [json.loads(line) for line in stream if line.strip()]
            duplicate = any(
                item.get("runtime") == args.runtime
                and item.get("run_id") == run_id
                and item.get("session_id") == record["session_id"]
                and item.get("agent_id") == agent_id
                and item.get("event") == event
                for item in existing
            )
            stream.seek(0, 2)
            if not duplicate:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
        if event == "SubagentStart":
            relative = path.relative_to(root).as_posix()
            context = (
                f"CONTEXT-DELIVERY receipt: agent_id={agent_id}; agent_type={agent_type}; "
                f"runtime={args.runtime}; lifecycle_receipt_path={relative}. "
                "Hash the receipt only after SubagentStop and any AgentToolResult record."
            )
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": context}}))
        else:
            print("{}")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"subagent lifecycle ledger failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
