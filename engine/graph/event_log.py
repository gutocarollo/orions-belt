#!/usr/bin/env python3
"""Validated, process-safe JSONL append for control-graph events."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
from typing import Any

try:
    from .runtime import GraphError, apply_event, load_graph, replay
except ImportError:
    from runtime import GraphError, apply_event, load_graph, replay


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GraphError(f"{path}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise GraphError(f"{path}:{number}: event must be an object")
        events.append(value)
    return events


def append_event(path: Path, event: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Validate complete history and append one event under an exclusive lock.

    An exact redelivery is a no-op. Reuse of an event_id with different
    content fails in the reducer, preventing an ambiguous audit trail.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        events: list[dict[str, Any]] = []
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GraphError(f"{path}:{number}: invalid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise GraphError(f"{path}:{number}: event must be an object")
            events.append(parsed)
        state = replay(events, graph) if events else None
        result = apply_event(state, event, graph)
        if state is None or result != state:
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("event", type=Path, help="JSON file containing one event")
    parser.add_argument("--graph")
    args = parser.parse_args()
    try:
        value = json.loads(args.event.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise GraphError("event JSON root must be an object")
        state = append_event(args.log, value, load_graph(args.graph))
    except (OSError, json.JSONDecodeError, GraphError, ValueError) as exc:
        print(f"APPEND FAILED: {exc}")
        return 2
    print(json.dumps(state, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
