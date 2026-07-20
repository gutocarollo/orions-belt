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
import json
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))  # engine/
from _tooling_conf import get_config, project_root  # noqa: E402


ROOT = project_root()
RUNS_DIR = ROOT / get_config("HARNESS_LEDGER_DIR", ".agent-swarm/runs")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


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


def append_event(args: argparse.Namespace) -> None:
    path = ledger_path(args.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": utc_now(),
        "run_id": args.run_id,
        "loop": args.loop,
        "round": args.round,
        "event": args.event,
        "status": args.status,
        "payload": parse_payload(args.payload_json),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
    print(path.relative_to(ROOT))


def summarize(args: argparse.Namespace) -> None:
    path = ledger_path(args.run_id)
    if not path.exists():
        raise SystemExit(f"ledger not found: {path}")
    counts: dict[str, int] = {}
    last_status: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            entry = json.loads(line)
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
