#!/usr/bin/env python3
"""Append and validate Council loop events in the installed project."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from _tooling_conf import get_config, project_root
from council_runtime import TransitionError, apply_transition
from objective_control import ObjectiveControlError, record_deferred


ROOT = project_root()
RUNS_DIR = ROOT / get_config("HARNESS_LEDGER_DIR", ".harness/runs/agent-swarm")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
CONSUMED_PARENT = {"replan-consumed": "replan-request", "fix-consumed": "fix-request"}
EVENT_STATUSES = {
    ("planning", "review"): {"SATISFEITO", "REPLANEJAR", "SABATINAR", "BLOQUEADO"},
    ("planning", "replan-request"): {"REPLANEJAR"},
    ("planning", "replan-consumed"): {"REPLANEJAR"},
    ("execution", "review"): {"SATISFEITO", "CORRIGIR", "BLOQUEADO"},
    ("execution", "fix-request"): {"CORRIGIR"},
    ("execution", "fix-consumed"): {"CORRIGIR"},
}
COUNCIL_EVENTS = ("ANCHOR", "PHASE-PLAN", "ITEM-PLAN", "SLICE", "VALIDATION", "LOCAL-COMMIT", "QUALITY", "SIMPLIFICATION", "ADVERSARIAL", "DELIVERY")


def persist_deferred(run_id: str, event_payload: dict[str, Any]) -> None:
    findings = event_payload.get("deferred_findings", [])
    if not findings:
        return
    runs = ROOT / ".harness" / "runs"
    active = runs / "ACTIVE"
    if not active.is_file() or active.read_text(encoding="utf-8").strip() != run_id:
        raise ObjectiveControlError("DEFER_RUN requires this run to be the active Council run")
    run_path = runs / run_id / "RUN.md"
    for finding in findings:
        record_deferred(run_path, {**finding["impact"], "reason": finding["reason"], "review_after": finding["review_after"]})


def verify_repository_transition(event: str, state: dict[str, Any], root: Path) -> None:
    if event == "LOCAL-COMMIT":
        sha = state["commits"][-1]
        if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=root, capture_output=True).returncode:
            raise SystemExit(f"invalid Council transition: local commit does not exist: {sha}")
        actual = set(subprocess.check_output(["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha], cwd=root, text=True).splitlines())
        if actual != set(state["commit_files"][sha]):
            raise SystemExit(f"invalid Council transition: local commit files differ from validated slice: {sha}")
        expected_hashes = {item["path"]: item["sha256"] for item in state["validation_evidence"]["file_hashes"]}
        actual_hashes = {path: hashlib.sha256(subprocess.check_output(["git", "show", f"{sha}:{path}"], cwd=root)).hexdigest() for path in actual}
        if actual_hashes != expected_hashes:
            raise SystemExit(f"invalid Council transition: commit content differs from validated file hashes: {sha}")
    if event == "DELIVERY":
        if state.get("mutation_mode") == "WORKSPACE_WRITE":
            source_root = Path(__file__).resolve().parents[2]
            sys.path.insert(0, str(source_root))
            from engine.integration.council_pipeline import IntegrationError, verify_repository_evidence
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            try:
                verify_repository_evidence({"state": state, "evidence": {"git_sha": head}}, root)
            except IntegrationError as exc:
                raise SystemExit(f"invalid Council transition: {exc}") from exc
        state["delivery_verified"] = True


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ledger_path(run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise SystemExit("run-id may contain only letters, digits, dot, underscore and hyphen")
    return RUNS_DIR / run_id / "loop.jsonl"


def validate_entry(entry: Any, expected_run_id: str, expected_seq: int) -> None:
    if not isinstance(entry, dict):
        raise SystemExit("ledger event must be a JSON object")
    required = {"ts", "run_id", "seq", "loop", "round", "event", "status", "payload"}
    missing = sorted(required - set(entry))
    if missing:
        raise SystemExit("ledger event missing fields: " + ", ".join(missing))
    if set(entry) - (required | {"parent_seq"}):
        raise SystemExit("ledger event contains undeclared fields")
    if entry["run_id"] != expected_run_id or not RUN_ID_RE.fullmatch(str(entry["run_id"])):
        raise SystemExit("ledger event run_id differs from its ledger")
    if entry["seq"] != expected_seq:
        raise SystemExit(f"ledger seq={entry['seq']} expected {expected_seq}")
    if entry["loop"] not in {"planning", "execution"}:
        raise SystemExit("ledger loop must be planning|execution")
    if not isinstance(entry["round"], int) or isinstance(entry["round"], bool) or entry["round"] < 1:
        raise SystemExit("ledger round must be a positive integer")
    if not isinstance(entry["payload"], dict):
        raise SystemExit("ledger payload must be an object")
    allowed = EVENT_STATUSES.get((entry["loop"], entry["event"]))
    if allowed is not None and entry["status"] not in allowed:
        raise SystemExit(f"invalid status {entry['status']!r} for {entry['loop']}:{entry['event']}")


def read_entries(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{number}: invalid JSON: {exc}") from exc
        validate_entry(entry, run_id, len(entries) + 1)
        if entries and entry["round"] < entries[-1]["round"]:
            raise SystemExit(f"{path}:{number}: round regressed")
        parent_seq = entry.get("parent_seq")
        if parent_seq is not None and (not isinstance(parent_seq, int) or parent_seq < 1 or parent_seq >= entry["seq"]):
            raise SystemExit(f"{path}:{number}: invalid parent_seq")
        if entry["event"] in CONSUMED_PARENT:
            if parent_seq is None:
                raise SystemExit(f"{path}:{number}: consumed event requires parent_seq")
            parent = entries[parent_seq - 1]
            if parent["loop"] != entry["loop"] or parent["event"] != CONSUMED_PARENT[entry["event"]]:
                raise SystemExit(f"{path}:{number}: parent does not reference matching request")
        entries.append(entry)
    return entries


def pending_parent(entries: list[dict[str, Any]], loop: str, event: str) -> int | None:
    wanted = CONSUMED_PARENT.get(event)
    if wanted is None:
        return None
    consumed = {entry.get("parent_seq") for entry in entries}
    for entry in reversed(entries):
        if entry["loop"] == loop and entry["event"] == wanted and entry["seq"] not in consumed:
            return int(entry["seq"])
    raise SystemExit(f"{event} requires an unconsumed {wanted} parent")


def payload(raw: str | None) -> dict[str, Any]:
    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise SystemExit("payload must be a JSON object")
    return value


def append(args: argparse.Namespace) -> None:
    path = ledger_path(args.run_id)
    state_path = path.parent / "council-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("append requires a persisted WORKSPACE_WRITE Council run") from exc
    if state.get("mutation_mode") != "WORKSPACE_WRITE":
        raise SystemExit("append requires a persisted WORKSPACE_WRITE Council run")
    event_payload = payload(args.payload_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        entries = read_entries(path, args.run_id)
        parent_seq = pending_parent(entries, args.loop, args.event)
        entry = {"ts": utc_now(), "run_id": args.run_id, "seq": len(entries) + 1,
                 "loop": args.loop, "round": args.round, "event": args.event,
                 "status": args.status, "payload": event_payload}
        if parent_seq is not None:
            entry["parent_seq"] = parent_seq
        validate_entry(entry, args.run_id, len(entries) + 1)
        if entries and args.round < entries[-1]["round"]:
            raise SystemExit("round cannot regress")
        persist_deferred(args.run_id, event_payload)
        stream.seek(0, 2)
        stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
    print(path.relative_to(ROOT))


def summary(args: argparse.Namespace) -> None:
    path = ledger_path(args.run_id)
    if not path.exists():
        raise SystemExit(f"ledger not found: {path}")
    entries = read_entries(path, args.run_id)
    counts: dict[str, int] = {}
    last_status: dict[str, str] = {}
    for entry in entries:
        key = f"{entry['loop']}:{entry['event']}"
        counts[key] = counts.get(key, 0) + 1
        last_status[entry["loop"]] = entry["status"]
    print(json.dumps({"run_id": args.run_id, "counts": counts, "last_status": last_status}, indent=2, sort_keys=True))


def transition(args: argparse.Namespace) -> None:
    folder = ledger_path(args.run_id).parent
    event_payload = payload(args.payload_json)
    if args.council_event == "ANCHOR" and event_payload.get("mutation_mode") == "READ_ONLY":
        raise SystemExit("read-only Council runs are inline and cannot mutate the ledger")
    folder.mkdir(parents=True, exist_ok=True)
    event_path = folder / "council-events.jsonl"
    state_path = folder / "council-state.json"
    required_path = state_path.with_suffix(".required-next")
    if required_path.exists() and args.council_event != "VALIDATION":
        raise SystemExit("invalid Council transition: VALIDATION is required after the last edit")
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
                    run_id=args.run_id,
                    replaying=True,
                )
            if state and state.get("mutation_mode") == "READ_ONLY":
                raise TransitionError("read-only Council runs are inline and cannot mutate the ledger")
            if args.council_event == "VALIDATION":
                checked = event_payload.get("checked_files", [])
                for name in checked:
                    if not subprocess.check_output(["git", "status", "--porcelain", "--", name], cwd=ROOT, text=True).strip():
                        raise TransitionError(f"VALIDATION must precede LOCAL-COMMIT; checked file is already clean: {name}")
                for command in event_payload.get("commands", []):
                    process = subprocess.run(command.get("command", ""), cwd=ROOT, shell=True)
                    if process.returncode != 0:
                        raise TransitionError(f"validation command failed with exit {process.returncode}: {command.get('command')}")
                    command["exit_code"] = process.returncode
                event_payload["executor"] = "agent_swarm_ledger"
                event_payload["validated_at"] = utc_now()
                event_payload["file_hashes"] = [{"path": name, "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()} for name in checked]
            item = {"seq": len(events) + 1, "ts": utc_now(), "event": args.council_event, "payload": event_payload}
            state = apply_transition(
                state,
                item["event"],
                item["payload"],
                repository_root=ROOT,
                run_id=args.run_id,
            )
            if args.council_event in {"QUALITY", "ADVERSARIAL"}:
                persist_deferred(args.run_id, event_payload)
        except (TransitionError, KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"invalid Council transition: {exc}") from exc
        verify_repository_transition(args.council_event, state, ROOT)
        stream.seek(0, 2)
        stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.council_event == "VALIDATION" and required_path.exists():
            required_path.unlink()
    print(state_path.relative_to(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("append")
    add.add_argument("--run-id", required=True)
    add.add_argument("--loop", choices=("planning", "execution"), required=True)
    add.add_argument("--round", type=int, required=True)
    add.add_argument("--event", choices=("review", "replan-request", "replan-consumed", "fix-request", "fix-consumed", "validation", "final"), required=True)
    add.add_argument("--status", required=True)
    add.add_argument("--payload-json")
    add.set_defaults(func=append)
    show = commands.add_parser("summary")
    show.add_argument("--run-id", required=True)
    show.set_defaults(func=summary)
    move = commands.add_parser("transition")
    move.add_argument("--run-id", required=True)
    move.add_argument("--event", dest="council_event", choices=COUNCIL_EVENTS, required=True)
    move.add_argument("--payload-json", required=True)
    move.set_defaults(func=transition)
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
