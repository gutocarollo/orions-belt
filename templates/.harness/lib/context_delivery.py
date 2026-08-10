#!/usr/bin/env python3
"""Route and persist CONTEXT-PLAN/CONTEXT-DELIVERY for an active Council."""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
from typing import Any

from _tooling_conf import get_config, get_config_csv, project_root
from council_runtime import TransitionError, apply_transition, bind_context_payload
from context_routing import route_context, route_from_repository

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
                state = apply_transition(
                    state,
                    item["event"],
                    item["payload"],
                    repository_root=ROOT,
                    run_id=run_id,
                    replaying=True,
                )
            if state is None or state.get("mutation_mode") != "WORKSPACE_WRITE":
                raise TransitionError("context transition requires WORKSPACE_WRITE")
            payload = bind_context_payload(state, event, payload, ROOT, run_id=run_id)
            item = {"seq": len(events) + 1, "event": event, "payload": payload}
            state = apply_transition(state, event, payload, repository_root=ROOT, run_id=run_id)
        except (TransitionError, KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"invalid Council context transition: {exc}") from exc
        stream.seek(0, 2)
        stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state_path


def _configured_port(key: str) -> bool:
    raw = str(get_config(key, "0")).strip()
    try:
        return int(raw) > 0
    except ValueError:
        return bool(raw and raw.lower() not in {"false", "no", "none", "off"})


def _route_payload(request: dict[str, Any], *, use_repository: bool) -> dict[str, Any]:
    request = dict(request)
    runtime = str(request.pop("runtime", "claude"))
    project = get_config("PROJECT_NAME", ROOT.name)
    if runtime == "claude":
        request.setdefault("allowed_agent_types", [f"{project}-context-scout"])
        request.setdefault("allowed_models", [get_config("HARNESS_CLAUDE_CONTEXT_SCOUT_MODEL", "sonnet")])
    elif runtime == "codex":
        request.setdefault("allowed_agent_types", [f"{project}-context-scout"])
        request.setdefault("allowed_models", [get_config("HARNESS_CODEX_CONTEXT_SCOUT_MODEL", "gpt-5.6-terra")])
    else:
        raise SystemExit("runtime must be claude or codex")
    request.setdefault("canonical_docs", get_config_csv("HARNESS_ENTRY_DOCS", []))
    request.setdefault("codegraph_available", get_config("HARNESS_CONTEXT_PROVIDER", "none") == "codegraph")
    request.setdefault("lsp_available", get_config("HARNESS_LSP_PROVIDER", "none") != "none")
    request.setdefault("live_state_available", _configured_port("HARNESS_MCP_DB_DEV_PORT"))
    if use_repository:
        request.setdefault("core_paths", get_config("HARNESS_CORE_PATHS", ""))
        request.setdefault("data_write_patterns", get_config("HARNESS_DATA_WRITE_PATTERNS", ""))
        return route_from_repository(ROOT, **request)
    return route_context(**request)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    route = sub.add_parser("route")
    route.add_argument("--input-json", required=True)
    route.add_argument("--repository", action="store_true", help="compute P1-P3 from the Git diff")
    move = sub.add_parser("transition")
    move.add_argument("--run-id", required=True)
    move.add_argument("--event", choices=sorted(CONTEXT_EVENTS), required=True)
    move.add_argument("--payload-json", required=True)
    args = parser.parse_args()
    if args.command == "route":
        print(json.dumps(_route_payload(_load_payload(args.input_json), use_repository=args.repository), indent=2, sort_keys=True))
    else:
        print(transition(args.run_id, args.event, _load_payload(args.payload_json)).relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
