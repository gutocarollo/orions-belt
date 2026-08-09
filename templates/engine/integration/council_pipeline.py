#!/usr/bin/env python3
"""Materialize deterministic Council state and evidence from JSONL events.

The ledger is the source; state and evidence are derived outputs.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".harness" / "lib"))
from council_runtime import TransitionError, apply_transition  # noqa: E402
from mini_schema_validate import validate_instance  # noqa: E402


class IntegrationError(ValueError):
    pass


def integrate_events(events: list[dict[str, Any]], git_sha: str) -> dict[str, Any]:
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
            state = apply_transition(state, str(item.get("event", "")), item.get("payload", {}))
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
    head = __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    if declared_sha != head:
        raise IntegrationError(f"declared git_sha {declared_sha} does not equal repository HEAD {head}")
    for sha in state.get("commits", []):
        process = __import__("subprocess").run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_root, capture_output=True)
        if process.returncode:
            raise IntegrationError(f"local commit does not exist in repository: {sha}")
        if __import__("subprocess").run(["git", "merge-base", "--is-ancestor", sha, declared_sha], cwd=repo_root).returncode:
            raise IntegrationError(f"local commit is not an ancestor of declared git_sha: {sha}")
        actual_files = set(__import__("subprocess").check_output(["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha], cwd=repo_root, text=True).splitlines())
        if actual_files != set(state.get("commit_files", {}).get(sha, [])):
            raise IntegrationError(f"local commit files differ from validated slice: {sha}")
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
        acceptance = manifest["acceptance"]
        if {item["commit"] for item in acceptance} != set(state.get("commits", [])) or manifest.get("commits") != state.get("commits"):
            raise IntegrationError("delivery manifest must map acceptance and every local commit")
        validations: dict[str, dict[str, Any]] = {}
        pending_validation = None
        for history_item in state["history"]:
            if history_item["event"] == "VALIDATION":
                pending_validation = history_item["payload"]
            elif history_item["event"] == "LOCAL-COMMIT":
                validations[history_item["payload"]["sha"]] = pending_validation or {}
                pending_validation = None
        expected_reviewers = {state["quality_reviewer_id"], state["adversarial_reviewer_id"]}
        for item in acceptance:
            commit = item["commit"]
            validation = validations.get(commit, {})
            if set(item["files"]) != set(state["commit_files"][commit]) or set(item["files"]) != set(validation.get("checked_files", [])):
                raise IntegrationError(f"acceptance files differ from validated commit: {commit}")
            if item["commands"] != [command["command"] for command in validation.get("commands", [])]:
                raise IntegrationError(f"acceptance commands differ from validation evidence: {commit}")
            if set(item["reviewer_ids"]) != expected_reviewers:
                raise IntegrationError(f"acceptance reviewer_ids differ from final review threads: {commit}")
            for evidence in item["evidence"]:
                evidence_path = (repo_root / evidence).resolve()
                if repo_root.resolve() not in evidence_path.parents or not evidence_path.is_file():
                    raise IntegrationError(f"acceptance evidence is missing or escapes repository: {evidence}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        events = [json.loads(line) for line in args.ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = integrate_events(events, args.git_sha)
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
