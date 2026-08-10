#!/usr/bin/env python3
"""Legacy-era MCP stdio transport probe for provider regression tests.

This intentionally exercises the 2025-11-25 initialize/tools-list contract used
by CodeGraph's documented stdio server. Real Claude/Codex smoke tests remain the
authoritative proof that the installed host version can consume that provider.
"""
from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _read_response(proc: subprocess.Popen[str], request_id: int, timeout: float) -> dict[str, Any]:
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    seen: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise RuntimeError(f"MCP server exited rc={proc.returncode}: {stderr[-4000:]}")
        events = selector.select(max(0.0, deadline - time.monotonic()))
        if not events:
            continue
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"non-JSON MCP stdout: {line!r}") from exc
        if not isinstance(message, dict):
            raise RuntimeError(f"MCP message is not an object: {message!r}")
        seen.append(message)
        if message.get("id") == request_id:
            if "error" in message:
                raise RuntimeError(f"MCP request {request_id} failed: {message['error']}")
            return message
    raise RuntimeError(f"timeout waiting for MCP response id={request_id}; seen={seen[-5:]}")


def _send(proc: subprocess.Popen[str], message: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("server command is required after --")

    proc = subprocess.Popen(
        command,
        cwd=args.cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env={**os.environ, "NO_COLOR": "1"},
    )
    try:
        _send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "orions-belt-context-smoke", "version": "1.0.0"},
            },
        })
        initialize = _read_response(proc, 1, args.timeout)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = _read_response(proc, 2, args.timeout)
        tools = listed.get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            raise RuntimeError("tools/list result lacks tools array")
        names = sorted(str(item.get("name")) for item in tools if isinstance(item, dict) and item.get("name"))
        if not names:
            raise RuntimeError("MCP server returned no tools")
        output = {
            "probeMode": "legacy-mcp-stdio-2025-11-25",
            "serverInfo": initialize.get("result", {}).get("serverInfo"),
            "protocolVersion": initialize.get("result", {}).get("protocolVersion"),
            "tools": names,
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
