#!/usr/bin/env python3
"""Materialize deterministic Council state and evidence from JSONL events.

The ledger is the source; state and evidence are derived outputs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".harness" / "lib"))
from council_runtime import TransitionError, apply_transition  # noqa: E402
from council_session import worktree_state  # noqa: E402
from mini_schema_validate import validate_instance  # noqa: E402
from objective_control import CODE_SUFFIXES, ObjectiveControlError, validate_execution_graph, verify_code_necessity, verify_impact_evidence  # noqa: E402


class IntegrationError(ValueError):
    pass


def _load_json(repo_root: Path, relative: str, label: str) -> dict[str, Any]:
    path = (repo_root / relative).resolve()
    if repo_root.resolve() not in path.parents:
        raise IntegrationError(f"{label} escapes repository root")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise IntegrationError(f"{label} must be a JSON object")
    return value


def _require_repository_file(repo_root: Path, reference: str, label: str) -> Path:
    relative = reference.partition("#")[0]
    path = (repo_root / relative).resolve()
    if not relative or repo_root.resolve() not in path.parents or not path.is_file():
        raise IntegrationError(f"{label} is missing or escapes repository: {reference}")
    return path


def _validate_semantic_evidence(repo_root: Path, graph: dict[str, Any], events: list[dict[str, Any]], checked_code_sha: str) -> None:
    """Resolve REAL findings and require terminal reviews bound to delivered code."""
    for item in events:
        if item["event"] not in {"QUALITY", "ADVERSARIAL"}:
            continue
        for finding in item["payload"].get("findings", []) + item["payload"].get("deferred_findings", []):
            impact = finding["impact"]
            if impact.get("evidence_status") != "REAL":
                continue
            try:
                verify_impact_evidence(repo_root, impact)
            except ObjectiveControlError as exc:
                raise IntegrationError(str(exc)) from exc

    review_edges = [edge for edge in graph["edges"] if edge["phase"] == "review"]
    if not review_edges:
        return
    verdict_lines: set[str] = set()
    sha_marker = f"CHECKED-CODE-SHA: {checked_code_sha}"
    for edge in review_edges:
        for reference in edge["evidence"]:
            path = _require_repository_file(repo_root, reference, "review evidence")
            if path.suffix == ".md":
                lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
                relative = path.relative_to(repo_root.resolve()).as_posix()
                marker_commits = subprocess.run(
                    ["git", "log", "--format=%H", "-S", sha_marker, "--", relative],
                    cwd=repo_root, capture_output=True, text=True,
                ).stdout.splitlines()
                reviewed_after_code = any(
                    commit != checked_code_sha
                    and subprocess.run(
                        ["git", "merge-base", "--is-ancestor", checked_code_sha, commit],
                        cwd=repo_root, capture_output=True,
                    ).returncode == 0
                    for commit in marker_commits
                )
                if sha_marker in lines and reviewed_after_code:
                    verdict_lines.update(lines)
    required = {
        "QUALITY-REVIEW: SATISFEITO",
        "SIMPLIFICATION: NAO_NECESSARIA",
        "ADVERSARIAL-VERIFICATION: SATISFEITO",
    }
    if not required <= verdict_lines:
        raise IntegrationError("review edge lacks SHA-bound terminal review evidence: " + ", ".join(sorted(required - verdict_lines)))


def _code_commits(repo_root: Path, base_sha: str, head_sha: str) -> list[str]:
    commits = subprocess.check_output(
        ["git", "rev-list", "--reverse", f"{base_sha}..{head_sha}"], cwd=repo_root, text=True,
    ).splitlines()
    return [
        sha for sha in commits
        if any(
            Path(name).suffix.lower() in CODE_SUFFIXES
            for name in subprocess.check_output(
                ["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-m", sha],
                cwd=repo_root, text=True,
            ).splitlines()
        )
    ]


def _replay_validation_commands(repo_root: Path, validations: dict[str, dict[str, Any]]) -> None:
    for validation in validations.values():
        for item in validation.get("commands", []):
            command = item["command"]
            process = subprocess.run(command, cwd=repo_root, shell=True, capture_output=True, text=True)
            if process.returncode:
                detail = (process.stderr or process.stdout).strip()[-500:]
                suffix = f": {detail}" if detail else ""
                raise IntegrationError(
                    f"validation command failed during delivery replay with exit {process.returncode}: {command}{suffix}"
                )


def integrate_events(events: list[dict[str, Any]], git_sha: str, repo_root: Path | None = None) -> dict[str, Any]:
    if not events:
        raise IntegrationError("event ledger is empty")
    if len(git_sha) != 40 or any(char not in "0123456789abcdef" for char in git_sha.lower()):
        raise IntegrationError("git_sha must be a full 40-character SHA")
    state = None
    for index, item in enumerate(events, 1):
        if not isinstance(item, dict) or set(item) - {"event", "payload", "seq", "ts"}:
            raise IntegrationError(f"event {index}: invalid event object")
        if item.get("seq", index) != index:
            raise IntegrationError(f"event {index}: invalid sequence")
        try:
            state = apply_transition(state, str(item.get("event", "")), item.get("payload", {}), repository_root=repo_root)
        except (TransitionError, TypeError, ValueError) as exc:
            raise IntegrationError(f"event {index}: {exc}") from exc
    assert state is not None
    reviewers = [
        str(item["payload"]["reviewer_id"])
        for item in state["history"]
        if item["event"] in {"QUALITY", "ADVERSARIAL"} and item["payload"].get("reviewer_id")
    ]
    evidence = {
        "status": "PASS" if state["stage"] == "DELIVERY" else "INCOMPLETE",
        "git_sha": git_sha,
        "event_count": len(events),
        "local_commits": state.get("commits", []),
        "reviewer_ids": reviewers,
        "final_stage": state["stage"],
    }
    return {"state": state, "evidence": evidence}


def verify_repository_evidence(result: dict[str, Any], repo_root: Path) -> None:
    state = result["state"]
    declared_sha = result["evidence"]["git_sha"]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    if declared_sha != head:
        raise IntegrationError(f"declared git_sha {declared_sha} does not equal repository HEAD {head}")
    validations: dict[str, dict[str, Any]] = {}
    pending_validation = None
    for history_item in state["history"]:
        if history_item["event"] == "VALIDATION":
            pending_validation = history_item["payload"]
        elif history_item["event"] == "LOCAL-COMMIT":
            validations[history_item["payload"]["sha"]] = pending_validation or {}
            pending_validation = None
    for sha in state.get("commits", []):
        process = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_root, capture_output=True)
        if process.returncode:
            raise IntegrationError(f"local commit does not exist in repository: {sha}")
        if subprocess.run(["git", "merge-base", "--is-ancestor", sha, declared_sha], cwd=repo_root).returncode:
            raise IntegrationError(f"local commit is not an ancestor of declared git_sha: {sha}")
        actual_files = set(subprocess.check_output(["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha], cwd=repo_root, text=True).splitlines())
        if actual_files != set(state.get("commit_files", {}).get(sha, [])):
            raise IntegrationError(f"local commit files differ from validated slice: {sha}")
        validation = validations.get(sha, {})
        expected_hashes = {item["path"]: item["sha256"] for item in validation.get("file_hashes", [])}
        actual_hashes = {path: hashlib.sha256(subprocess.check_output(["git", "show", f"{sha}:{path}"], cwd=repo_root)).hexdigest() for path in actual_files}
        if actual_hashes != expected_hashes:
            raise IntegrationError(f"commit content differs from validated file hashes: {sha}")
    baseline = sorted(state.get("worktree_baseline", []))
    if worktree_state(repo_root) != baseline:
        raise IntegrationError("repository has uncommitted drift relative to the Council ANCHOR")
    _replay_validation_commands(repo_root, validations)
    if worktree_state(repo_root) != baseline:
        raise IntegrationError("validation replay mutated the repository relative to the Council ANCHOR")
    delivery = next((item["payload"] for item in reversed(state["history"]) if item["event"] == "DELIVERY"), None)
    if state.get("mutation_mode") == "WORKSPACE_WRITE":
        if not delivery:
            raise IntegrationError("workspace run lacks DELIVERY payload")
        manifest_path = (repo_root / delivery["manifest"]).resolve()
        if repo_root.resolve() not in manifest_path.parents:
            raise IntegrationError("delivery manifest escapes repository root")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrationError(f"delivery manifest is unreadable: {manifest_path}") from exc
        schema = json.loads((ROOT / ".harness/schemas/delivery-manifest.schema.json").read_text(encoding="utf-8"))
        errors = validate_instance(manifest, schema)
        if errors:
            raise IntegrationError("delivery manifest schema violation: " + "; ".join(errors))
        graph = _load_json(repo_root, manifest["execution_graph"], "execution graph")
        report = _load_json(repo_root, manifest["code_necessity_report"], "code necessity report")
        for value, schema_name, label in ((graph, "execution-graph.schema.json", "execution graph"), (report, "code-necessity-report.schema.json", "code necessity report")):
            value_schema = json.loads((ROOT / ".harness/schemas" / schema_name).read_text(encoding="utf-8"))
            value_errors = validate_instance(value, value_schema)
            if value_errors:
                raise IntegrationError(f"{label} schema violation: " + "; ".join(value_errors))
        if graph != state.get("execution_graph"):
            raise IntegrationError("delivered execution graph differs from the Council ANCHOR")
        try:
            graph_result = validate_execution_graph(graph)
            verify_code_necessity(repo_root, report)
        except ObjectiveControlError as exc:
            raise IntegrationError(str(exc)) from exc
        edges = {edge["edge_id"]: edge for edge in graph["edges"]}
        for edge in graph["edges"]:
            for evidence in edge["evidence"]:
                _require_repository_file(repo_root, evidence, "execution graph evidence")
        _validate_semantic_evidence(repo_root, graph, state["history"], report["head_sha"])
        if report["base_sha"] != state.get("base_sha"):
            raise IntegrationError("code necessity base_sha differs from the Council ANCHOR")
        unrecorded_code = [sha for sha in _code_commits(repo_root, report["base_sha"], report["head_sha"]) if sha not in state.get("commits", [])]
        if unrecorded_code:
            raise IntegrationError("unrecorded code commit exists between Council ANCHOR and delivery: " + ", ".join(unrecorded_code))
        for sha in state.get("commits", []):
            if subprocess.run(["git", "merge-base", "--is-ancestor", sha, report["head_sha"]], cwd=repo_root).returncode:
                raise IntegrationError(f"code necessity report does not cover local commit: {sha}")
        acceptance = manifest["acceptance"]
        if {item["commit"] for item in acceptance} != set(state.get("commits", [])) or manifest.get("commits") != state.get("commits"):
            raise IntegrationError("delivery manifest must map acceptance and every local commit")
        expected_reviewers = {state["quality_reviewer_id"], state["adversarial_reviewer_id"]}
        covered_edges: set[str] = set()
        for item in acceptance:
            commit = item["commit"]
            validation = validations.get(commit, {})
            if set(item["files"]) != set(state["commit_files"][commit]) or set(item["files"]) != set(validation.get("checked_files", [])):
                raise IntegrationError(f"acceptance files differ from validated commit: {commit}")
            if item["commands"] != [command["command"] for command in validation.get("commands", [])]:
                raise IntegrationError(f"acceptance commands differ from validation evidence: {commit}")
            if set(item["reviewer_ids"]) != expected_reviewers:
                raise IntegrationError(f"acceptance reviewer_ids differ from final review threads: {commit}")
            if item["edge_id"] != state["commit_edges"][commit] or item["edge_id"] not in edges:
                raise IntegrationError(f"acceptance edge_id differs from the committed plan: {commit}")
            expected_tests = set(state["commit_tests"][commit])
            edge_tests = {test_id for ids in edges[item["edge_id"]]["tests"].values() for test_id in ids}
            if set(item["test_ids"]) != expected_tests or expected_tests != edge_tests:
                raise IntegrationError(f"acceptance test_ids differ from validation or graph edge: {commit}")
            covered_edges.add(item["edge_id"])
            for evidence in item["evidence"]:
                _require_repository_file(repo_root, evidence, "acceptance evidence")
        if not set(graph_result["critical_edges"]) <= covered_edges:
            raise IntegrationError("delivery acceptance does not cover every critical graph edge")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        events = [json.loads(line) for line in args.ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = integrate_events(events, args.git_sha, args.repo_root.resolve())
        verify_repository_evidence(result, args.repo_root.resolve())
        result["state"]["delivery_verified"] = True
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "run-state.json").write_text(json.dumps(result["state"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (args.output_dir / "evidence-manifest.json").write_text(json.dumps(result["evidence"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, IntegrationError) as exc:
        print(f"council-pipeline: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result["evidence"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
