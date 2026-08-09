#!/usr/bin/env python3
"""Objective-focused gates shared by Council planning, review and delivery."""

from __future__ import annotations

from collections import deque
from pathlib import Path
import re
import subprocess
from typing import Any


class ObjectiveControlError(ValueError):
    """Raised when declared evidence cannot support a Council decision."""


WEIGHTS = {"objective_impact": 30, "journey_reachability": 25, "acceptance_impact": 20, "irreversibility": 15, "dependency_urgency": 10}
TEST_CLASSES = ("functional", "quality", "regression")
CODE_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".bash",
    ".zsh", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".c", ".h",
    ".cc", ".cpp", ".cs", ".swift", ".scala", ".vue", ".svelte",
    ".jinja",
}
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
MAX_PORTION_LINES = 120
NO_OP_EVIDENCE_COMMANDS = {":", "true", "/bin/true", "/usr/bin/true"}


def assess_impact(value: dict[str, Any]) -> dict[str, Any]:
    """Calculate the only severity disposition accepted by Council."""
    for field in ("id", "evidence_status", "graph_nodes"):
        if not value.get(field):
            raise ObjectiveControlError(f"impact assessment requires {field}")
    evidence = value.get("evidence")
    if not isinstance(evidence, dict) or any(not evidence.get(field) for field in ("path", "line", "contains")):
        raise ObjectiveControlError("impact assessment requires a concrete repository locator in evidence")
    evidence_path = Path(str(evidence["path"]))
    if evidence_path.is_absolute() or ".." in evidence_path.parts:
        raise ObjectiveControlError("impact evidence path must be repository-relative")
    if not isinstance(evidence["line"], int) or isinstance(evidence["line"], bool) or evidence["line"] < 1:
        raise ObjectiveControlError("impact evidence line must be a positive integer")
    if value["evidence_status"] not in {"REAL", "UNVERIFIED", "REFUTED"}:
        raise ObjectiveControlError("evidence_status must be REAL, UNVERIFIED or REFUTED")
    for field in ("on_critical_path", "affects_current_phase", "validated_workaround"):
        if not isinstance(value.get(field), bool):
            raise ObjectiveControlError(f"impact assessment requires boolean {field}")
    for field in WEIGHTS:
        rating = value.get(field)
        if not isinstance(rating, int) or isinstance(rating, bool) or not 0 <= rating <= 4:
            raise ObjectiveControlError(f"{field} must be an integer from 0 to 4")

    score = round(sum(value[field] * weight for field, weight in WEIGHTS.items()) / 4, 2)
    real = value["evidence_status"] == "REAL"
    no_workaround = not value["validated_workaround"]
    hard_safety = bool(value.get("hard_safety_boundary")) and value["irreversibility"] == 4
    if real and no_workaround and value["on_critical_path"] and (score >= 85 or hard_safety):
        disposition = "CRITICAL_BLOCK"
    elif real and no_workaround and value["affects_current_phase"] and score >= 70:
        disposition = "HIGH_FIX_NOW"
    else:
        disposition = "DEFER_RUN"
    if "score" in value and float(value["score"]) != score:
        raise ObjectiveControlError(f"declared score {value['score']} differs from calculated score {score}")
    if "disposition" in value and value["disposition"] != disposition:
        raise ObjectiveControlError(f"declared disposition {value['disposition']} differs from calculated disposition {disposition}")
    return {**value, "score": score, "disposition": disposition}


def validate_execution_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Prove that graph edges and their phase tests connect start to goal."""
    for field in ("objective", "start_node", "goal_node", "nodes", "edges"):
        if not graph.get(field):
            raise ObjectiveControlError(f"execution graph requires {field}")
    nodes = graph["nodes"]
    if not isinstance(nodes, list) or len(nodes) != len(set(nodes)):
        raise ObjectiveControlError("execution graph nodes must be a unique list")
    if graph["start_node"] not in nodes or graph["goal_node"] not in nodes:
        raise ObjectiveControlError("execution graph endpoints must exist in nodes")

    adjacency: dict[str, list[tuple[str, str]]] = {node: [] for node in nodes}
    reverse: dict[str, list[str]] = {node: [] for node in nodes}
    edge_ids: set[str] = set()
    critical_edges: list[dict[str, Any]] = []
    for edge in graph["edges"]:
        required = ("edge_id", "from", "to", "critical", "phase", "item", "tests", "evidence")
        missing = [field for field in required if field not in edge]
        if missing:
            raise ObjectiveControlError(f"execution edge missing {', '.join(missing)}")
        if edge["edge_id"] in edge_ids:
            raise ObjectiveControlError(f"duplicate edge_id {edge['edge_id']}")
        edge_ids.add(edge["edge_id"])
        if edge["from"] not in adjacency or edge["to"] not in adjacency:
            raise ObjectiveControlError(f"edge {edge['edge_id']} references an unknown node")
        tests = edge["tests"]
        for test_class in TEST_CLASSES:
            if not isinstance(tests.get(test_class), list) or not tests[test_class]:
                raise ObjectiveControlError(f"edge {edge['edge_id']} requires {test_class} tests")
        if not isinstance(edge["evidence"], list) or not edge["evidence"]:
            raise ObjectiveControlError(f"edge {edge['edge_id']} requires evidence")
        adjacency[edge["from"]].append((edge["to"], edge["edge_id"]))
        reverse[edge["to"]].append(edge["from"])
        if edge["critical"]:
            critical_edges.append(edge)

    path = _edge_path(adjacency, graph["start_node"], graph["goal_node"])
    if path is None:
        raise ObjectiveControlError("execution graph has no path from start_node to goal_node")
    from_start = _reachable({node: [target for target, _ in values] for node, values in adjacency.items()}, graph["start_node"])
    to_goal = _reachable(reverse, graph["goal_node"])
    for edge in critical_edges:
        if edge["from"] not in from_start or edge["to"] not in to_goal:
            raise ObjectiveControlError(f"critical edge {edge['edge_id']} is outside every start-to-goal path")
    return {"status": "PASS", "critical_path": path, "critical_edges": [edge["edge_id"] for edge in critical_edges], "nodes": len(nodes), "edges": len(edge_ids)}


def _edge_path(adjacency: dict[str, list[tuple[str, str]]], start: str, goal: str) -> list[str] | None:
    queue = deque([(start, [])])
    seen = {start}
    while queue:
        node, path = queue.popleft()
        if node == goal:
            return path
        for target, edge_id in adjacency[node]:
            if target not in seen:
                seen.add(target)
                queue.append((target, path + [edge_id]))
    return None


def _reachable(adjacency: dict[str, list[str]], start: str) -> set[str]:
    found = {start}
    queue = deque([start])
    while queue:
        for target in adjacency[queue.popleft()]:
            if target not in found:
                found.add(target)
                queue.append(target)
    return found


def record_deferred(run_path: Path, assessment: dict[str, Any]) -> bool:
    """Append one DEFER_RUN item to the existing RUN section, idempotently."""
    decision = assess_impact(assessment)
    if decision["disposition"] != "DEFER_RUN":
        raise ObjectiveControlError("only DEFER_RUN findings may be recorded as non-blocking")
    try:
        content = run_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ObjectiveControlError(f"RUN is unreadable: {run_path}") from exc
    heading = "## Pendências não bloqueantes"
    if content.count(heading) != 1:
        raise ObjectiveControlError("RUN must contain exactly one non-blocking pending section")
    if f"`{decision['id']}`" in content:
        return False
    entry = (
        f"- `{decision['id']}` — DEFER_RUN score {decision['score']:.2f}; "
        f"nodes={','.join(decision['graph_nodes'])}; evidence={decision['evidence']['path']}:{decision['evidence']['line']}; "
        f"reason={assessment.get('reason', 'outside the current critical path')}; "
        f"review_after={assessment.get('review_after', 'next applicable phase')}."
    )
    start = content.index(heading) + len(heading)
    end = content.find("\n## ", start)
    end = len(content) if end == -1 else end
    section = content[start:end].replace("\n- Nenhuma no início do run.", "")
    updated = content[:start] + section.rstrip() + "\n" + entry + "\n" + content[end:].lstrip("\n")
    run_path.write_text(updated, encoding="utf-8")
    return True


def verify_code_necessity(root: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Require every line added to a code file to have one semantic receipt."""
    base = str(report.get("base_sha", ""))
    head = str(report.get("head_sha", ""))
    actual_head = _git(root, "rev-parse", "HEAD").strip()
    if len(base) != 40 or len(head) != 40:
        raise ObjectiveControlError("code necessity report must bind full base_sha and head_sha values")
    if base == head:
        raise ObjectiveControlError("code necessity base_sha and head_sha must be distinct")
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=root).returncode:
        raise ObjectiveControlError("code necessity base_sha is not an ancestor of head_sha")
    if subprocess.run(["git", "merge-base", "--is-ancestor", head, actual_head], cwd=root).returncode:
        raise ObjectiveControlError("code necessity head_sha is not an ancestor of current HEAD")
    later_code = _added_code_lines(_git(root, "diff", "--unified=0", "--no-color", f"{head}..{actual_head}", "--"))
    if later_code:
        raise ObjectiveControlError("code necessity report is stale because code was added after head_sha")
    added = _added_code_lines(_git(root, "diff", "--unified=0", "--no-color", f"{base}..{head}", "--"))
    covered: set[tuple[str, int]] = set()
    blobs: dict[str, list[str]] = {}
    verified_commands: set[str] = set()

    def blob_lines(path: str, label: str) -> list[str]:
        candidate = Path(path)
        if not path or candidate.is_absolute() or ".." in candidate.parts:
            raise ObjectiveControlError(f"{label} must be a safe repository-relative path")
        if path not in blobs:
            process = subprocess.run(
                ["git", "show", f"{head}:{path}"], cwd=root, capture_output=True, text=True
            )
            if process.returncode:
                raise ObjectiveControlError(f"{label} does not exist at head_sha: {path}")
            blobs[path] = process.stdout.splitlines()
        return blobs[path]

    required_fields = ("path", "start_line", "end_line", "purpose", "objective", "inputs", "outputs", "evidence", "simpler_alternative", "necessity")
    for portion in report.get("portions", []):
        if any(field not in portion or portion[field] in ("", []) for field in required_fields):
            raise ObjectiveControlError("every code portion requires purpose, objective, I/O, evidence, alternative and necessity")
        start, end = portion["start_line"], portion["end_line"]
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            raise ObjectiveControlError("code portion line range is invalid")
        if end - start + 1 > MAX_PORTION_LINES:
            raise ObjectiveControlError(f"code portion exceeds the reviewable maximum of {MAX_PORTION_LINES} lines")
        source_lines = blob_lines(portion["path"], "code portion path")
        if end > len(source_lines):
            raise ObjectiveControlError(f"code portion range exceeds head_sha blob: {portion['path']}:{end}")
        portion_lines = {(portion["path"], line) for line in range(start, end + 1)}
        if not portion_lines & added:
            raise ObjectiveControlError("every code portion must include at least one added code line")
        for evidence in portion["evidence"]:
            if not isinstance(evidence, dict) or any(not evidence.get(field) for field in ("path", "line", "contains", "command")):
                raise ObjectiveControlError("every evidence receipt requires path, line, contains and command")
            evidence_lines = blob_lines(evidence["path"], "evidence path")
            line = evidence["line"]
            if not isinstance(line, int) or isinstance(line, bool) or not 1 <= line <= len(evidence_lines):
                raise ObjectiveControlError(f"evidence line is outside head_sha blob: {evidence['path']}:{line}")
            if evidence["contains"] not in evidence_lines[line - 1]:
                raise ObjectiveControlError(f"evidence marker is absent at {evidence['path']}:{line}")
            command = evidence["command"]
            if not isinstance(command, str) or " ".join(command.split()) in NO_OP_EVIDENCE_COMMANDS:
                raise ObjectiveControlError("evidence command cannot be a no-op")
            if command not in verified_commands:
                process = subprocess.run(command, cwd=root, shell=True, capture_output=True, text=True)
                if process.returncode:
                    raise ObjectiveControlError(f"evidence command failed with exit {process.returncode}: {command}")
                verified_commands.add(command)
        covered.update(portion_lines & added)
    missing = sorted(added - covered)
    if missing:
        sample = ", ".join(f"{path}:{line}" for path, line in missing[:10])
        raise ObjectiveControlError(f"uncovered added code lines: {sample}")
    return {"status": "PASS", "added_code_lines": len(added), "covered_lines": len(added), "verified_commands": len(verified_commands)}


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True)


def _added_code_lines(diff: str) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    path: str | None = None
    line_number: int | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git a/"):
            match = re.match(r"diff --git a/(.+) b/(.+)", line)
            path = match.group(2) if match else None
            line_number = None
        elif line.startswith("@@"):
            match = HUNK_RE.match(line)
            line_number = int(match.group(1)) if match else None
        elif line_number is not None and line.startswith("+") and not line.startswith("+++"):
            if path and Path(path).suffix.lower() in CODE_SUFFIXES:
                result.add((path, line_number))
            line_number += 1
        elif line_number is not None and not line.startswith("-"):
            line_number += 1
    return result
