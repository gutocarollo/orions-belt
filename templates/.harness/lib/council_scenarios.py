#!/usr/bin/env python3
"""End-to-end Council scenarios in isolated Git repositories and processes."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

TESTS = {"functional": ["F1"], "quality": ["Q1"], "regression": ["R1"]}


def _impact(finding_id: str) -> dict[str, Any]:
    return {"id": finding_id, "evidence_status": "REAL", "evidence": "isolated scenario", "objective_impact": 3, "journey_reachability": 3, "acceptance_impact": 3, "irreversibility": 3, "dependency_urgency": 3, "on_critical_path": False, "affects_current_phase": True, "validated_workaround": False, "graph_nodes": ["request", "done"], "score": 75, "disposition": "HIGH_FIX_NOW"}


def _finding(finding_id: str, gap: str) -> dict[str, Any]:
    return {"gap": gap, "evidence": f"{gap} review", "required_change": f"apply {gap} fix", "impact": _impact(finding_id)}


def _item_payload(phase: str, item: str, **extra: Any) -> dict[str, Any]:
    return {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": phase, "item": item, "slice": item, "validation": ["git diff --check"], "objective": "scenario delivery", "edge_id": "E1", "deliverable": f"{item} delivered", "tests": TESTS, **extra}


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)


def _must(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = _run(command, cwd, env)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _must(["git", "init", "-q"], path)
    _must(["git", "config", "user.email", "council@example.invalid"], path)
    _must(["git", "config", "user.name", "Council Scenario"], path)


def _commit(path: Path, name: str, content: str) -> str:
    (path / name).write_text(content, encoding="utf-8")
    _must(["git", "add", name], path)
    _must(["git", "commit", "-q", "-m", f"slice {name}"], path)
    return _must(["git", "rev-parse", "HEAD"], path).stdout.strip()


def _commit_existing(path: Path, files: list[str]) -> str:
    _must(["git", "add", *files], path)
    _must(["git", "commit", "-q", "-m", "validated Council slice"], path)
    return _must(["git", "rev-parse", "HEAD"], path).stdout.strip()


def _start(source: Path, target: Path, run_id: str, mode: str = "WORKSPACE_WRITE") -> dict[str, str]:
    env = {**os.environ, "HARNESS_PROJECT_ROOT": str(target)}
    _must([
        sys.executable, str(source / ".harness/lib/council_session.py"), "start",
        "--root", str(target), "--run-id", run_id, "--anchor-source", "inline-verbatim",
        "--mutation-mode", mode,
    ], target, env)
    return env


def _transition(source: Path, target: Path, run_id: str, event: str, payload: dict[str, Any], env: dict[str, str]) -> None:
    _must([
        sys.executable, str(source / ".harness/lib/agent_swarm_ledger.py"), "transition",
        "--run-id", run_id, "--event", event, "--payload-json", json.dumps(payload),
    ], target, env)


def _execute_flow(source: Path, target: Path, run_id: str, actions: list[dict[str, Any]]) -> tuple[list[str], int]:
    env = _start(source, target, run_id)
    commits: list[str] = []
    commit_file_sets: list[list[str]] = []
    commit_commands: list[list[str]] = []
    process_count = 1
    changed_files: list[str] = []
    for index, action in enumerate(actions, 1):
        event = action["event"]
        payload = dict(action["payload"])
        if event == "SLICE":
            changed_files = list(payload["changed_files"])
            (target / action["file"]).write_text(action["content"], encoding="utf-8")
        elif event == "VALIDATION":
            command = action.get("command", ["git", "diff", "--check"])
            result = _must(command, target)
            payload["commands"] = [{"command": " ".join(command), "exit_code": result.returncode}]
            payload["checked_files"] = changed_files
            payload["test_results"] = [{"id": test_id, "class": test_class, "status": "PASS"} for test_class, ids in TESTS.items() for test_id in ids]
            validated_commands = [item["command"] for item in payload["commands"]]
        elif event == "LOCAL-COMMIT":
            sha = _commit_existing(target, changed_files)
            commits.append(sha)
            commit_file_sets.append(list(changed_files))
            commit_commands.append(validated_commands)
            payload["sha"] = sha
            payload["files"] = changed_files
        elif event == "DELIVERY":
            manifest = target / action["payload"]["manifest"]
            reviewers = [item["payload"]["reviewer_id"] for item in actions if item["event"] in {"QUALITY", "ADVERSARIAL"} and item["payload"].get("status") == "SATISFEITO"]
            reviewer_ids = list(dict.fromkeys(reviewers))[-2:]
            ledger_path = f".harness/runs/agent-swarm/{run_id}/council-events.jsonl"
            acceptance = [{"criterion": "slice delivered", "phase": "scenario", "item": f"item-{index}", "slice": f"slice-{index}", "commit": sha, "files": files, "commands": commands, "evidence": [ledger_path], "reviewer_ids": reviewer_ids, "edge_id": "E1", "test_ids": [test_id for ids in TESTS.values() for test_id in ids]} for index, (sha, files, commands) in enumerate(zip(commits, commit_file_sets, commit_commands), 1)]
            graph_path = target / "execution-graph.json"
            graph_path.write_text(json.dumps({"objective": "scenario delivery", "start_node": "request", "goal_node": "done", "nodes": ["request", "done"], "edges": [{"edge_id": "E1", "from": "request", "to": "done", "critical": True, "phase": "scenario", "item": "delivery", "tests": TESTS, "evidence": [ledger_path]}]}, indent=2) + "\n", encoding="utf-8")
            report_path = target / "code-necessity.json"
            report_path.write_text(json.dumps({"base_sha": commits[-1], "head_sha": commits[-1], "portions": []}, indent=2) + "\n", encoding="utf-8")
            manifest.write_text(json.dumps({"acceptance": acceptance, "commits": commits, "execution_graph": graph_path.name, "code_necessity_report": report_path.name}, indent=2) + "\n", encoding="utf-8")
        _transition(source, target, run_id, event, payload, env)
        process_count += 1
        if index == len(actions) // 2:
            state = target / ".harness/runs/agent-swarm" / run_id / "council-state.json"
            json.loads(state.read_text(encoding="utf-8"))
    return commits, process_count


def _base_actions(prefix: str) -> list[dict[str, Any]]:
    return [
        {"event": "PHASE-PLAN", "payload": {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": prefix, "items": [prefix], "objective": "scenario delivery", "edge_id": "E1", "entry_node": "request", "exit_node": "done", "tests": TESTS}},
        {"event": "ITEM-PLAN", "payload": _item_payload(prefix, prefix)},
        {"event": "SLICE", "payload": {"skill": "incremental-implementation", "slice": prefix, "changed_files": [f"{prefix}.txt"]}, "file": f"{prefix}.txt", "content": f"{prefix}\n"},
        {"event": "VALIDATION", "payload": {"status": "PASS"}},
        {"event": "LOCAL-COMMIT", "payload": {}},
    ]


def run_scenarios(root: Path, workspace: Path) -> dict[str, Any]:
    read_only = workspace / "read-only"
    _init_repo(read_only)
    _commit(read_only, "baseline.txt", "baseline\n")
    before = _must(["git", "status", "--porcelain"], read_only).stdout
    read_ledger = workspace / "read-only-events.jsonl"
    read_ledger.write_text("\n".join(json.dumps(item) for item in [
        {"event": "ANCHOR", "payload": {"mutation_mode": "READ_ONLY", "anchor_source": "inline"}},
        {"event": "DELIVERY", "payload": {"status": "SATISFEITO", "manifest": "inline-report"}},
    ]) + "\n", encoding="utf-8")
    _must([sys.executable, str(root / "engine/integration/council_pipeline.py"), str(read_ledger), "--git-sha", _must(["git", "rev-parse", "HEAD"], read_only).stdout.strip(), "--repo-root", str(read_only), "--output-dir", str(workspace / "read-proof")], read_only)
    after = _must(["git", "status", "--porcelain"], read_only).stdout

    trivial = workspace / "trivial"
    remote = workspace / "remote.git"
    _init_repo(trivial)
    _must(["git", "init", "--bare", "-q", str(remote)], workspace)
    _must(["git", "remote", "add", "origin", str(remote)], trivial)
    trivial_actions = _base_actions("trivial") + [
        {"event": "QUALITY", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "77777777-7777-4777-8777-777777777777", "round": 1}},
        {"event": "SIMPLIFICATION", "payload": {"status": "NAO_NECESSARIA", "reason": "single clear slice", "validations": []}},
        {"event": "ADVERSARIAL", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "88888888-8888-4888-8888-888888888888", "round": 1}},
        {"event": "DELIVERY", "payload": {"status": "SATISFEITO", "manifest": "trivial-delivery.json"}},
    ]
    trivial_commits, trivial_processes = _execute_flow(root, trivial, "trivial-e2e", trivial_actions)
    blocked_push = _run(["git", "push", "origin", "HEAD:main"], trivial)
    auth = workspace / "remote-auth.json"
    auth.write_text(json.dumps({"remote_authorized": True, "authorized_by": "scenario-owner", "authorization_evidence": "scenario-explicit"}), encoding="utf-8")
    authorized_push = _run(["git", "push", "origin", "HEAD:main"], trivial, {**os.environ, "COUNCIL_REMOTE_AUTHORIZATION": str(auth)})

    complex_repo = workspace / "complex"
    _init_repo(complex_repo)
    complex_actions = _base_actions("phase-1") + _base_actions("phase-2") + [
        {"event": "QUALITY", "payload": {"status": "CORRIGIR", "critical": 0, "required": 1, "reviewer_id": "55555555-5555-4555-8555-555555555555", "round": 1, "findings": [_finding("QF1", "quality")]}},
        {"event": "ITEM-PLAN", "payload": _item_payload("phase-2", "quality-fix", fix_kind="quality", consumes_review_round=1)},
        {"event": "SLICE", "payload": {"skill": "incremental-implementation", "slice": "quality-fix", "changed_files": ["quality-fix.txt"]}, "file": "quality-fix.txt", "content": "quality fix\n"},
        {"event": "VALIDATION", "payload": {"status": "PASS"}},
        {"event": "LOCAL-COMMIT", "payload": {}},
        {"event": "QUALITY", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "55555555-5555-4555-8555-555555555555", "round": 2}},
        {"event": "SIMPLIFICATION", "payload": {"status": "NAO_NECESSARIA", "reason": "already minimal", "validations": []}},
        {"event": "ADVERSARIAL", "payload": {"status": "CORRIGIR", "critical": 0, "required": 1, "reviewer_id": "66666666-6666-4666-8666-666666666666", "round": 1, "findings": [_finding("AF1", "adversarial")]}},
        {"event": "ITEM-PLAN", "payload": _item_payload("phase-2", "adversarial-fix", fix_kind="adversarial", consumes_review_round=1)},
        {"event": "SLICE", "payload": {"skill": "incremental-implementation", "slice": "adversarial-fix", "changed_files": ["adversarial-fix.txt"]}, "file": "adversarial-fix.txt", "content": "adversarial fix\n"},
        {"event": "VALIDATION", "payload": {"status": "PASS"}},
        {"event": "LOCAL-COMMIT", "payload": {}},
        {"event": "QUALITY", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "55555555-5555-4555-8555-555555555555", "round": 3}},
        {"event": "SIMPLIFICATION", "payload": {"status": "NAO_NECESSARIA", "reason": "already minimal", "validations": []}},
        {"event": "ADVERSARIAL", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "66666666-6666-4666-8666-666666666666", "round": 2}},
        {"event": "DELIVERY", "payload": {"status": "SATISFEITO", "manifest": "complex-delivery.json"}},
    ]
    complex_commits, complex_processes = _execute_flow(root, complex_repo, "complex-e2e", complex_actions)
    complex_state = json.loads((complex_repo / ".harness/runs/agent-swarm/complex-e2e/council-state.json").read_text(encoding="utf-8"))
    ledger = complex_repo / ".harness/runs/agent-swarm/complex-e2e/council-events.jsonl"
    proof = workspace / "complex-proof"
    pipeline = _run([sys.executable, str(root / "engine/integration/council_pipeline.py"), str(ledger), "--git-sha", _must(["git", "rev-parse", "HEAD"], complex_repo).stdout.strip(), "--repo-root", str(complex_repo), "--output-dir", str(proof)], complex_repo)

    return {"scenarios": {
        "read_only": {"status": "PASS" if before == after else "FAIL", "zero_workspace_changes": before == after},
        "trivial": {"status": "PASS" if blocked_push.returncode != 0 and authorized_push.returncode == 0 else "FAIL", "local_commits": trivial_commits, "remote_push_blocked": blocked_push.returncode != 0, "authorized_push_passed": authorized_push.returncode == 0, "processes": trivial_processes},
        "complex": {"status": "PASS" if complex_state["stage"] == "DELIVERY" and pipeline.returncode == 0 else "FAIL", "local_commits": complex_commits, "resume_replay_equal": pipeline.returncode == 0, "reviewer_ids": [complex_state["quality_reviewer_id"], complex_state["adversarial_reviewer_id"]], "processes": complex_processes, "ledger": str(ledger), "proof": str(proof)},
    }}
