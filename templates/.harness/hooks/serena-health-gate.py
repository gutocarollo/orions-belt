#!/usr/bin/env python3
"""Fail-closed health/RSS guard for optional Serena MCP calls.

The gate never kills processes. If Serena is unhealthy, the route must fall
back to CodeGraph, rg and targeted reads and record the skip.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_PATTERN = r"(?:\bserena\b|serena[_-]server|mcp[^\n]*serena)"


@dataclass(frozen=True)
class Process:
    pid: int
    rss_kb: int
    command: str


def parse_process_table(text: str, pattern: str = DEFAULT_PATTERN, own_pid: int | None = None) -> list[Process]:
    matcher = re.compile(pattern, re.IGNORECASE)
    result: list[Process] = []
    for raw in text.splitlines():
        match = re.match(r"^\s*(\d+)\s+(\d+)\s+(.*)$", raw)
        if not match:
            continue
        pid, rss_kb, command = int(match.group(1)), int(match.group(2)), match.group(3)
        if own_pid == pid:
            continue
        if matcher.search(command):
            result.append(Process(pid, rss_kb, command))
    return result


def evaluate(processes: list[Process], max_processes: int, max_rss_mb: int) -> tuple[bool, str]:
    rss_mb = sum(item.rss_kb for item in processes) / 1024
    if len(processes) > max_processes:
        return False, f"Serena process count {len(processes)} exceeds {max_processes}"
    if rss_mb > max_rss_mb:
        return False, f"Serena RSS {rss_mb:.1f} MB exceeds {max_rss_mb} MB"
    return True, f"processes={len(processes)} rss_mb={rss_mb:.1f}"


def _positive(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def main() -> int:
    try:
        raw = sys.stdin.read().strip()
        if raw and not isinstance(json.loads(raw), dict):
            raise ValueError("hook input must be an object")
        process = subprocess.run(["ps", "-axo", "pid=,rss=,command="], check=True, capture_output=True, text=True)
        processes = parse_process_table(
            process.stdout,
            os.environ.get("SERENA_PROCESS_PATTERN", DEFAULT_PATTERN),
            os.getpid(),
        )
        ok, reason = evaluate(
            processes,
            _positive("SERENA_MAX_PROCESSES", 2),
            _positive("SERENA_MAX_RSS_MB", 4096),
        )
        if not ok:
            raise ValueError(reason)
        health_url = os.environ.get("SERENA_HEALTH_URL", "").strip()
        if health_url:
            with urllib.request.urlopen(health_url, timeout=2) as response:  # nosec: operator-configured URL
                if not 200 <= int(getattr(response, "status", 200)) < 300:
                    raise ValueError(f"Serena health URL returned {response.status}")
        print("{}")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError, re.error, urllib.error.URLError) as exc:
        print(f"BLOCKED: {exc}. Serena is optional; use the declared fallback.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
