#!/usr/bin/env python3
"""Materialize Codex context-agent receipts from the runtime transcript.

Some Codex builds expose custom subagents but do not emit their lifecycle or
nested tool calls through project hooks. This adapter runs after ``wait_agent``
and derives receipts only from the completed child transcript. The verifier
re-hashes that transcript and checks its session, role, model and completion
metadata, so agent prose is never accepted as execution evidence.
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
from pathlib import Path
from typing import Any

from context_receipt_fields import definition_ids
from context_evidence import repository_fingerprint
from secure_runtime_io import open_locked_text

SOURCE = "codex-transcript-v1"
CONTEXT_SUFFIXES = ("-context-scout", "-context-shard")
MAX_EXCERPT = 16384


class TranscriptReceiptError(ValueError):
    """The requested Codex child transcript is absent or incomplete."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def _excerpt(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text[:MAX_EXCERPT]


def _methods(tool_name: str, tool_input: Any) -> list[str]:
    lower = tool_name.lower()
    text = _excerpt(tool_input).lower()
    command = ""
    if lower in {"bash", "exec_command", "shell", "terminal"} and isinstance(tool_input, dict):
        command = str(tool_input.get("command") or tool_input.get("cmd") or tool_input.get("script") or "").lower()
    methods: list[str] = []
    if lower in {"read", "read_file", "readfile"} or re.search(r"(?:^|[;&|]\s*)(?:cat|head|tail|sed\s+-n)\b", command):
        methods.append("targeted-read")
        if re.search(r"(?:^|[\"'/])docs/", text + command):
            methods.append("canonical-docs")
    if lower in {"grep", "grep_files", "glob", "list_files", "search_files"} or re.search(r"(?:^|\s)(?:rg|grep)(?:\s|$)", command):
        methods.append("rg")
    if lower.startswith("mcp__codegraph__") or "codegraph" in lower or re.search(r"(?:^|\s)codegraph(?:\s|$)", command):
        if "status" in lower or re.search(r"(?:^|\s)codegraph\s+status(?:\s|$)", command):
            methods.append("codegraph-status")
        else:
            methods.append("codegraph")
    if lower.startswith("mcp__serena__") or "lsp" in lower or "typescript-lsp" in lower:
        methods.append("lsp")
    if lower.startswith("mcp__") and any(token in lower for token in ("postgres", "database", "sql", "salesforce")):
        methods.append("live-state")
    return list(dict.fromkeys(methods))


def _read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TranscriptReceiptError(f"{path}:{number}: invalid Codex JSONL: {exc}") from exc
        if not isinstance(event, dict):
            raise TranscriptReceiptError(f"{path}:{number}: Codex event must be an object")
        events.append(event)
    return events


def _meta(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events or events[0].get("type") != "session_meta" or not isinstance(events[0].get("payload"), dict):
        raise TranscriptReceiptError("Codex child transcript lacks session_meta")
    return events[0]["payload"]


def _definition(root: Path, agent_type: str) -> tuple[str, str, str]:
    path = root / ".codex/agents" / f"{agent_type}.toml"
    if not path.is_file():
        raise TranscriptReceiptError(f"missing Codex agent definition: {path.relative_to(root)}")
    content = path.read_bytes()
    match = re.search(rb'(?m)^model\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        raise TranscriptReceiptError(f"missing Codex agent model: {path.relative_to(root)}")
    model = match.group(1).decode()
    return path.relative_to(root).as_posix(), hashlib.sha256(content).hexdigest(), model


def _codex_sessions(parent_transcript: Path | None) -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve() / "sessions"
    if parent_transcript:
        for candidate in parent_transcript.resolve().parents:
            if candidate.name == "sessions":
                return candidate
    return Path.home() / ".codex/sessions"


def _candidate_paths(sessions: Path, parent_transcript: Path | None) -> list[Path]:
    if parent_transcript and parent_transcript.parent.is_dir():
        local = sorted(parent_transcript.parent.glob("*.jsonl"))
        if local:
            return local
    return sorted(sessions.rglob("*.jsonl"))


def _find_children(root: Path, session_id: str, parent_transcript: Path | None) -> list[tuple[Path, list[dict[str, Any]]]]:
    sessions = _codex_sessions(parent_transcript)
    if not sessions.is_dir():
        raise TranscriptReceiptError(f"Codex sessions directory is absent: {sessions}")
    found: list[tuple[Path, list[dict[str, Any]]]] = []
    for path in _candidate_paths(sessions, parent_transcript):
        try:
            events = _read_events(path)
            meta = _meta(events)
        except (OSError, TranscriptReceiptError):
            continue
        role = str(meta.get("agent_role") or "")
        cwd = Path(str(meta.get("cwd") or ".")).resolve()
        if str(meta.get("session_id") or "") != session_id or not role.endswith(CONTEXT_SUFFIXES) or cwd != root:
            continue
        if not any(event.get("type") == "event_msg" and (event.get("payload") or {}).get("type") == "task_complete" for event in events):
            raise TranscriptReceiptError(f"Codex context child has not completed: {path}")
        found.append((path.resolve(), events))
    if not found:
        raise TranscriptReceiptError(f"no completed Codex context child found for session {session_id}")
    return found


def _json_argument(script: str, tool: str) -> dict[str, Any] | None:
    marker = f"tools.{tool}("
    start = script.find(marker)
    if start < 0:
        return None
    remainder = script[start + len(marker):].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(remainder)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _read_only_shell(command: str) -> bool:
    """Accept only conservative inspection commands from a context child."""
    if not command.strip() or any(token in command for token in ("`", "$(", ">", "<", "\n", ";", "&", "|")):
        return False
    allowed = {"cat", "head", "tail", "sed", "rg", "grep", "find", "ls", "pwd", "wc", "stat"}
    git_allowed = {"status", "diff", "show", "log", "rev-parse", "ls-files", "grep"}
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    executable = Path(parts[0]).name
    arguments = parts[1:]
    if any(value.startswith("/") or value == ".." or value.startswith("../") or "/../" in value for value in arguments):
        return False
    if executable not in allowed | {"git", "codegraph"}:
        return False
    if executable == "git":
        if not arguments or arguments[0] not in git_allowed:
            return False
        if any(value in {"--output", "--ext-diff", "--textconv"} or value.startswith("--output=") for value in arguments[1:]):
            return False
    elif executable == "codegraph":
        if arguments != ["status"]:
            return False
    elif executable == "sed" and any(value == "-i" or value.startswith("--in-place") for value in arguments):
        return False
    elif executable == "find" and any(
        value in {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprintf", "-fprint", "-fls"}
        for value in arguments
    ):
        return False
    elif executable == "rg" and any(value == "--pre" or value.startswith("--pre=") for value in arguments):
        return False
    return True


def _active_run(root: Path) -> str:
    active = root / ".harness/runs/ACTIVE"
    return active.read_text(encoding="utf-8").strip() if active.is_file() else ""


def _repository_binding(root: Path, run_id: str) -> str:
    state_path = root / ".harness/runs/agent-swarm" / run_id / "council-state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        value = str(state.get("repository_fingerprint") or "")
        if value:
            return value
    return repository_fingerprint(root)


def _assert_read_only(events: list[dict[str, Any]]) -> None:
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") == "event_msg" and payload.get("type") == "mcp_tool_call_end":
            if payload.get("read_only_hint") is not True:
                raise TranscriptReceiptError("Codex context child used an MCP tool without read_only_hint=true")
        if event.get("type") != "response_item":
            continue
        if payload.get("type") == "function_call":
            raise TranscriptReceiptError(f"Codex context child used unsupported function tool: {payload.get('name')}")
        if payload.get("type") != "custom_tool_call" or payload.get("name") != "exec":
            continue
        script = str(payload.get("input") or "")
        called = re.findall(r"\btools\.([A-Za-z0-9_]+)\s*\(", script)
        for tool in called:
            if tool == "exec_command":
                args = _json_argument(script, tool)
                command = str((args or {}).get("cmd") or (args or {}).get("command") or "")
                if not _read_only_shell(command):
                    raise TranscriptReceiptError(f"Codex context child used non-read-only shell command: {command}")
            elif not tool.startswith("mcp__"):
                raise TranscriptReceiptError(f"Codex context child used unsupported nested tool: {tool}")


def _timestamp_ns(value: Any, offset: int = 0) -> int:
    text = str(value or "")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1_000_000_000) + offset
    except ValueError:
        return offset


def _tool_pair(
    *, run_id: str, repository_binding: str, session_id: str, agent_id: str, agent_type: str, transcript: Path,
    transcript_sha: str, model: str, call_id: str, tool_name: str,
    tool_input: Any, response: Any, timestamp: Any,
) -> list[dict[str, Any]]:
    methods = _methods(tool_name, tool_input)
    if not methods:
        return []
    common = {
        "source": SOURCE,
        "runtime": "codex",
        "run_id": run_id,
        "repository_fingerprint": repository_binding,
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "transcript_path": str(transcript),
        "transcript_sha256": transcript_sha,
        "model": model,
        "tool_use_id": call_id,
        "tool_name": tool_name,
        "methods": methods,
        "input_sha256": hashlib.sha256(_canonical_json(tool_input)).hexdigest(),
        "input_excerpt": _excerpt(tool_input),
    }
    pre = {
        **common, "event": "PreToolUse", "success": False,
        "output_sha256": None, "response_excerpt": "", "error_excerpt": "",
        "definition_ids": [],
        "time_ns": _timestamp_ns(timestamp), "ts": timestamp,
    }
    post = {
        **common, "event": "PostToolUse", "success": True,
        "output_sha256": hashlib.sha256(_canonical_json(response)).hexdigest(),
        "response_excerpt": _excerpt(response), "error_excerpt": "",
        "definition_ids": definition_ids(response),
        "time_ns": _timestamp_ns(timestamp, 1), "ts": timestamp,
    }
    return [pre, post]


def _extract_tools(path: Path, events: list[dict[str, Any]], run_id: str, repository_binding: str, session_id: str, agent_id: str, agent_type: str, model: str) -> list[dict[str, Any]]:
    transcript_sha = _sha256(path)
    custom: dict[str, tuple[Any, dict[str, Any]]] = {}
    records: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") == "response_item" and payload.get("type") == "custom_tool_call" and payload.get("name") == "exec":
            custom[str(payload.get("call_id") or "")] = (event.get("timestamp"), payload)
        elif event.get("type") == "response_item" and payload.get("type") == "custom_tool_call_output":
            call_id = str(payload.get("call_id") or "")
            origin = custom.get(call_id)
            if not origin:
                continue
            timestamp, call = origin
            script = str(call.get("input") or "")
            args = _json_argument(script, "exec_command")
            if args is None:
                continue
            tool_input = {"command": args.get("cmd") or args.get("command") or ""}
            records.extend(_tool_pair(
                run_id=run_id, repository_binding=repository_binding, session_id=session_id, agent_id=agent_id, agent_type=agent_type,
                transcript=path, transcript_sha=transcript_sha, model=model,
                call_id=call_id, tool_name="Bash", tool_input=tool_input,
                response=payload.get("output"), timestamp=timestamp,
            ))
        elif event.get("type") == "event_msg" and payload.get("type") == "mcp_tool_call_end":
            invocation = payload.get("invocation") or {}
            server = str(invocation.get("server") or "")
            tool = str(invocation.get("tool") or "")
            if not server or not tool:
                continue
            records.extend(_tool_pair(
                run_id=run_id, repository_binding=repository_binding, session_id=session_id, agent_id=agent_id, agent_type=agent_type,
                transcript=path, transcript_sha=transcript_sha, model=model,
                call_id=str(payload.get("call_id") or ""),
                tool_name=f"mcp__{server}__{tool}", tool_input=invocation.get("arguments"),
                response=payload.get("result"), timestamp=event.get("timestamp"),
            ))
    return records


def _append_tools(root: Path, session_id: str, records: list[dict[str, Any]]) -> Path:
    with open_locked_text(
        root, (".harness", "runs", "context-tools", session_id), "tools.jsonl"
    ) as (path, stream):
        stream.seek(0)
        existing = [json.loads(line) for line in stream if line.strip()]
        identities = {(item.get("runtime"), item.get("run_id"), item.get("session_id"), item.get("tool_use_id"), item.get("event")) for item in existing}
        seq = len(existing)
        stream.seek(0, 2)
        for record in records:
            identity = (record["runtime"], record["run_id"], record["session_id"], record["tool_use_id"], record["event"])
            if identity in identities:
                continue
            seq += 1
            record["seq"] = seq
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            identities.add(identity)
        stream.flush()
    return path


def _lifecycle(root: Path, path: Path, events: list[dict[str, Any]], session_id: str) -> tuple[Path, dict[str, Any]]:
    _assert_read_only(events)
    meta = _meta(events)
    agent_id = str(meta.get("id") or "")
    agent_type = str(meta.get("agent_role") or "")
    if not agent_id or not agent_type.endswith(CONTEXT_SUFFIXES):
        raise TranscriptReceiptError("Codex context child identity is incomplete")
    turn = next((event.get("payload") or {} for event in events if event.get("type") == "turn_context"), {})
    model = str(turn.get("model") or "")
    if not model:
        raise TranscriptReceiptError(f"Codex context child lacks resolved model: {path}")
    complete_event = next(
        event for event in reversed(events)
        if event.get("type") == "event_msg" and (event.get("payload") or {}).get("type") == "task_complete"
    )
    complete = complete_event.get("payload") or {}
    token_event = next(
        (event for event in reversed(events) if event.get("type") == "event_msg" and (event.get("payload") or {}).get("type") == "token_count"),
        None,
    )
    usage = (((token_event or {}).get("payload") or {}).get("info") or {}).get("total_token_usage") or {}
    usage = {"input_tokens": int(usage.get("input_tokens") or 0), "output_tokens": int(usage.get("output_tokens") or 0)}
    definition_path, definition_sha, configured_model = _definition(root, agent_type)
    transcript_sha = _sha256(path)
    run_id = _active_run(root)
    if not run_id:
        raise TranscriptReceiptError("Codex context receipt capture requires an active Council run")
    repository_binding = _repository_binding(root, run_id)
    common = {
        "source": SOURCE, "runtime": "codex", "run_id": run_id, "session_id": session_id,
        "repository_fingerprint": repository_binding,
        "agent_id": agent_id, "agent_type": agent_type, "model": model,
        "configured_model": configured_model, "agent_definition_path": definition_path,
        "agent_definition_sha256": definition_sha, "agent_transcript_path": str(path),
        "transcript_sha256": transcript_sha,
    }
    message = str(complete.get("last_agent_message") or "")
    records = [
        {**common, "event": "SubagentStart", "ts": meta.get("timestamp"), "usage": None, "duration_ms": None},
        {
            **common, "event": "AgentToolResult", "ts": complete_event.get("timestamp"),
            "usage": usage, "duration_ms": int(complete.get("duration_ms") or 0),
            "last_message_chars": len(message),
            "last_message_sha256": hashlib.sha256(message.encode()).hexdigest(),
        },
        {**common, "event": "SubagentStop", "ts": complete_event.get("timestamp"), "usage": None, "duration_ms": None},
    ]
    with open_locked_text(
        root, (".harness", "runs", "subagents", session_id), f"{agent_id}.jsonl"
    ) as (receipt, stream):
        stream.seek(0)
        stream.truncate()
        stream.write("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records))
        stream.flush()
    tools = _extract_tools(path, events, run_id, repository_binding, session_id, agent_id, agent_type, model)
    if not tools:
        raise TranscriptReceiptError(f"Codex context child has no attributable tool calls: {path}")
    tool_path = _append_tools(root, session_id, tools)
    return receipt, {
        "agent_id": agent_id, "agent_type": agent_type, "model": model,
        "lifecycle_receipt": receipt.relative_to(root).as_posix(),
        "tool_receipt": tool_path.relative_to(root).as_posix(),
        "transcript_path": str(path), "transcript_sha256": transcript_sha,
        "tool_calls": len(tools) // 2,
    }


def capture(root: Path, session_id: str, parent_transcript: Path | None = None) -> dict[str, Any]:
    resolved_root = root.resolve()
    if not session_id:
        raise TranscriptReceiptError("--session-id is required")
    children = _find_children(resolved_root, session_id, parent_transcript)
    agents = [_lifecycle(resolved_root, path, events, session_id)[1] for path, events in children]
    return {"source": SOURCE, "session_id": session_id, "agents": agents}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=".")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--parent-transcript")
    args = parser.parse_args()
    try:
        result = capture(
            Path(args.repository), args.session_id,
            Path(args.parent_transcript).resolve() if args.parent_transcript else None,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TranscriptReceiptError, json.JSONDecodeError) as exc:
        print(f"Codex context receipt capture failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
