#!/usr/bin/env python3
"""Persist CONTEXT-PLAN/CONTEXT-DELIVERY into an active Council event stream."""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
from typing import Any

from _tooling_conf import get_config, project_root
from council_runtime import TransitionError, apply_transition
from context_routing import route_context

ROOT = project_root()
RUNS_DIR = ROOT / get_config("HARNESS_LEDGER_DIR", ".harness/runs/agent-swarm")
CONTEXT_EVENTS = {"CONTEXT-PLAN", "CONTEXT-DELIVERY"}


def _load_payload(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SystemExit("payload must be a JSON object")
    return value


def _paths(run_id: str) -> tuple[Path, Path]:
    if not run_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in run_id):
        raise SystemExit("run-id may contain only letters, digits, dot, underscore and hyphen")
    folder = RUNS_DIR / run_id
    return folder / "council-events.jsonl", folder / "council-state.json"


def transition(run_id: str, event: str, payload: dict[str, Any]) -> Path:
    if event not in CONTEXT_EVENTS:
        raise SystemExit(f"unsupported context event: {event}")
    event_path, state_path = _paths(run_id)
    if not event_path.is_file() or not state_path.is_file():
        raise SystemExit("context transition requires an active persisted WORKSPACE_WRITE Council run")
    with event_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        events = [json.loads(line) for line in stream if line.strip()]
        state = None
        try:
            for item in events:
                state = apply_transition(state, item["event"], item["payload"], repository_root=ROOT)
            if state is None or state.get("mutation_mode") != "WORKSPACE_WRITE":
                raise TransitionError("context transition requires WORKSPACE_WRITE")
            item = {"seq": len(events) + 1, "event": event, "payload": payload}
            state = apply_transition(state, event, payload, repository_root=ROOT)
        except (TransitionError, KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"invalid Council context transition: {exc}") from exc
        stream.seek(0, 2)
        stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state_path


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    route = sub.add_parser("route")
    route.add_argument("--input-json", required=True)
    move = sub.add_parser("transition")
    move.add_argument("--run-id", required=True)
    move.add_argument("--event", choices=sorted(CONTEXT_EVENTS), required=True)
    move.add_argument("--payload-json", required=True)
    args = parser.parse_args()
    if args.command == "route":
        print(json.dumps(route_context(**_load_payload(args.input_json)), indent=2, sort_keys=True))
    else:
        print(transition(args.run_id, args.event, _load_payload(args.payload_json)).relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
