#!/usr/bin/env python3
"""Append and inspect agent-harness loop ledger events.

Port of `agent-swarm/codex/scripts/agent_swarm_ledger.py` — PARAMETERIZED
(explicit instruction of plan F1): `RUNS_DIR = ROOT / ".agent-swarm" /
"runs"` (ROOT = agent-swarm repo) became `HARNESS_LEDGER_DIR` read via
`engine/_tooling_conf.py`, resolved against the TARGET PROJECT root (not
this package) via `project_root()` — same reason as `validate_skills.py`:
the execution ledger belongs to the installed project, not to the engine.

The default of `HARNESS_LEDGER_DIR` in `templates/.harness/harness.conf.jinja`
is `${HARNESS_RUNS_DIR}/agent-swarm` — it reuses the run-state directory
that marathon already uses (`.claude/runs`) instead of introducing a second
parallel `.agent-swarm/` root directory (deliberate unification; see the
commit for this change). If `HARNESS_LEDGER_DIR` is not configured, it falls
back to the original literal value `.agent-swarm/runs` (fail-open, behavior
identical to the source script when there is no central config)."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # engine/
from _tooling_conf import get_config, project_root  # noqa: E402
from contract.scripts.mini_schema_validate import validate_instance  # noqa: E402


ROOT = project_root()
RUNS_DIR = ROOT / get_config("HARNESS_LEDGER_DIR", ".agent-swarm/runs")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "ledger-event.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
CONSUMED_PARENT = {"replan-consumed": "replan-request", "fix-consumed": "fix-request"}
EVENT_STATUSES = {
    ("planning", "review"): {"SATISFEITO", "REPLANEJAR", "SABATINAR", "BLOQUEADO"},
    ("planning", "replan-request"): {"REPLANEJAR"},
    ("planning", "replan-consumed"): {"REPLANEJAR"},
    ("execution", "review"): {"SATISFEITO", "CORRIGIR", "BLOQUEADO"},
    ("execution", "fix-request"): {"CORRIGIR"},
    ("execution", "fix-consumed"): {"CORRIGIR"},
}


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_payload(raw: str | None) -> dict[str, Any]:
    if raw is None:
        raw = sys.stdin.read().strip() if not sys.stdin.isatty() else "{}"
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("payload must be a JSON object")
    return payload


def ledger_path(run_id: str) -> pathlib.Path:
    if not RUN_ID_RE.match(run_id):
        raise SystemExit("run-id may contain only letters, digits, dot, underscore and hyphen")
    return RUNS_DIR / run_id / "loop.jsonl"


def read_and_validate(path: pathlib.Path, run_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        errors = validate_instance(entry, SCHEMA)
        if errors:
            raise SystemExit(f"{path}:{line_number}: schema violation: {'; '.join(errors)}")
        expected_seq = len(entries) + 1
        if entry["seq"] != expected_seq:
            raise SystemExit(f"{path}:{line_number}: seq={entry['seq']} expected {expected_seq}")
        if entry["run_id"] != run_id:
            raise SystemExit(f"{path}:{line_number}: run_id differs from ledger directory")
        if entries and entry["round"] < entries[-1]["round"]:
            raise SystemExit(f"{path}:{line_number}: round regressed")
        parent_seq = entry.get("parent_seq")
        if parent_seq is not None and parent_seq >= entry["seq"]:
            raise SystemExit(f"{path}:{line_number}: parent_seq must reference an earlier event")
        if entry["event"] in CONSUMED_PARENT:
            if parent_seq is None:
                raise SystemExit(f"{path}:{line_number}: {entry['event']} requires parent_seq")
            parent = entries[parent_seq - 1]
            if parent["event"] != CONSUMED_PARENT[entry["event"]] or parent["loop"] != entry["loop"]:
                raise SystemExit(f"{path}:{line_number}: parent_seq does not reference matching request")
            if parent["round"] > entry["round"]:
                raise SystemExit(f"{path}:{line_number}: parent round is after child round")
        allowed = EVENT_STATUSES.get((entry["loop"], entry["event"]))
        if allowed is not None and entry["status"] not in allowed:
            raise SystemExit(f"{path}:{line_number}: status {entry['status']!r} invalid for {entry['loop']}:{entry['event']}")
        entries.append(entry)
    return entries


def infer_parent_seq(entries: list[dict[str, Any]], event: str, loop: str) -> int | None:
    required_parent = CONSUMED_PARENT.get(event)
    if required_parent is None:
        return None
    for entry in reversed(entries):
        if entry["loop"] == loop and entry["event"] == required_parent:
            already_consumed = any(item.get("parent_seq") == entry["seq"] for item in entries)
            if not already_consumed:
                return int(entry["seq"])
    raise SystemExit(f"{event} requires an unconsumed {required_parent} parent")


def append_event(args: argparse.Namespace) -> None:
    path = ledger_path(args.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        entries = read_and_validate(path, args.run_id)
        parent_seq = args.parent_seq
        inferred = infer_parent_seq(entries, args.event, args.loop)
        if parent_seq is None:
            parent_seq = inferred
        elif inferred is not None and parent_seq != inferred:
            raise SystemExit(f"parent-seq={parent_seq} does not identify the pending {CONSUMED_PARENT[args.event]}")
        entry = {
            "ts": utc_now(),
            "run_id": args.run_id,
            "seq": len(entries) + 1,
            "loop": args.loop,
            "round": args.round,
            "event": args.event,
            "status": args.status,
            "payload": parse_payload(args.payload_json),
        }
        if parent_seq is not None:
            entry["parent_seq"] = parent_seq
        errors = validate_instance(entry, SCHEMA)
        if errors:
            raise SystemExit("ledger event schema violation: " + "; ".join(errors))
        allowed = EVENT_STATUSES.get((args.loop, args.event))
        if allowed is not None and args.status not in allowed:
            raise SystemExit(f"status {args.status!r} invalid for {args.loop}:{args.event}; expected {sorted(allowed)}")
        if entries and args.round < entries[-1]["round"]:
            raise SystemExit("round cannot regress")
        handle.seek(0, 2)
        handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)
    print(path.relative_to(ROOT))


def summarize(args: argparse.Namespace) -> None:
    path = ledger_path(args.run_id)
    if not path.exists():
        raise SystemExit(f"ledger not found: {path}")
    entries = read_and_validate(path, args.run_id)
    counts: dict[str, int] = {}
    last_status: dict[str, str] = {}
    for entry in entries:
        key = f"{entry['loop']}:{entry['event']}"
        counts[key] = counts.get(key, 0) + 1
        last_status[entry["loop"]] = entry["status"]
    print(json.dumps({"run_id": args.run_id, "counts": counts, "last_status": last_status}, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    append = subparsers.add_parser("append", help="append one ledger event")
    append.add_argument("--run-id", required=True)
    append.add_argument("--loop", required=True, choices=("planning", "execution"))
    append.add_argument("--round", required=True, type=int)
    append.add_argument(
        "--event",
        required=True,
        choices=(
            "review",
            "replan-request",
            "replan-consumed",
            "fix-request",
            "fix-consumed",
            "validation",
            "final",
        ),
    )
    append.add_argument("--status", required=True)
    append.add_argument("--parent-seq", type=int, help="parent request seq; inferred for *-consumed events")
    append.add_argument("--payload-json")
    append.set_defaults(func=append_event)

    summary = subparsers.add_parser("summary", help="summarize one run ledger")
    summary.add_argument("--run-id", required=True)
    summary.set_defaults(func=summarize)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
