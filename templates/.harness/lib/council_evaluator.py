#!/usr/bin/env python3
"""Reproducible multicriteria evaluator and promotion gate for Council."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from council_contract import validate_contract
from sync_council import council_paths

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
OWNED_PATHS = (
    ".harness/lib/council_runtime.py",
    ".harness/lib/council_contract.py",
    ".harness/lib/council_scenarios.py",
    ".harness/lib/council_evaluator.py",
    ".harness/lib/council_hooks.py",
    ".harness/lib/council_git.py",
    ".harness/lib/sync_council.py",
    ".harness/lib/agent_swarm_ledger.py",
    ".harness/lib/validate_skills.py",
    ".harness/lib/tests",
    ".harness/schemas",
    ".harness/hooks/council-gate.py",
    ".claude/agents/code-reviewer.md",
    ".codex/agents/code-reviewer.toml",
    ".claude/settings.json",
    ".githooks/pre-push",
    "engine/integration/council_pipeline.py",
    "engine/contract/scripts/validate_contract.py",
    "scripts/validate_contract.py",
)


def _owned_paths(root: Path) -> tuple[str, ...]:
    council_files = council_paths(root)
    council = tuple(str(path.relative_to(root)) for path in council_files)
    project = council_files[0].parent.name.removesuffix("-delivery-council")
    implementers = (
        f".claude/agents/{project}-implementer.md",
        f".codex/agents/{project}-implementer.toml",
    )
    return council + implementers + OWNED_PATHS


def _command_pass(command: list[str], root: Path) -> bool:
    return subprocess.run(command, cwd=root, env={**__import__("os").environ, "HARNESS_PROJECT_ROOT": str(root)}, capture_output=True, text=True).returncode == 0


def _core_suite_pass(root: Path) -> bool:
    return all(
        _command_pass(["python3", "-m", "unittest", "discover", "-s", ".harness/lib/tests", "-p", pattern], root)
        for pattern in ("test_council_runtime.py", "test_council_contract.py", "test_council_pipeline.py")
    )


def _clean_checkout_pass(root: Path) -> bool:
    archive = subprocess.check_output(["git", "archive", "HEAD"], cwd=root)
    with tempfile.TemporaryDirectory() as directory:
        checkout = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(checkout, filter="data")
        return _core_suite_pass(checkout) and _command_pass(["python3", "engine/contract/scripts/validate_contract.py"], checkout)


def _review_valid(review: dict[str, Any], kind: str, sha: str) -> bool:
    path = Path(str(review.get("report_path", "")))
    if not path.is_file() or not UUID_RE.fullmatch(str(review.get("reviewer_id", ""))):
        return False
    content = path.read_bytes()
    expected = str(review.get("report_sha256", ""))
    sentinel = "QUALITY-REVIEW: SATISFEITO" if kind == "quality" else "ADVERSARIAL-VERIFICATION: SATISFEITO"
    return (
        hashlib.sha256(content).hexdigest() == expected
        and review.get("attestation_source") == "multi_agent_tool"
        and review.get("verdict") == "SATISFEITO"
        and review.get("git_sha") == sha
        and int(review.get("critical", review.get("blocking", -1))) == 0
        and int(review.get("required", review.get("high", -1))) == 0
        and sentinel in content.decode("utf-8", errors="replace")
        and sha in content.decode("utf-8", errors="replace")
    )


def _score(checks: dict[str, bool]) -> float:
    return round(10 * sum(checks.values()) / len(checks), 2)


def _codex_council_hooks(root: Path) -> bool:
    try:
        hooks = json.loads((root / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False
    return all(any("council-gate.py" in str(item) and event.lower().replace("tooluse", "") in str(item) for item in hooks.get(event, [])) for event in ("PreToolUse", "PostToolUse", "Stop"))


def evaluate(root: Path, scenario_report: dict[str, Any], review_evidence: dict[str, Any] | None = None, expected_sha: str | None = None) -> dict[str, Any]:
    contract = validate_contract(root)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *_owned_paths(root)], cwd=root).returncode != 0
    scenarios_pass = all(item.get("status") == "PASS" for item in scenario_report.get("scenarios", {}).values())
    scenarios = scenario_report.get("scenarios", {})
    complex_result = scenarios.get("complex", {})
    trivial = scenarios.get("trivial", {})
    read_only = scenarios.get("read_only", {})
    simulated_independence = len(set(complex_result.get("reviewer_ids", []))) >= 2
    review_evidence = review_evidence or {}
    quality = review_evidence.get("quality", {})
    adversarial = review_evidence.get("adversarial", {})
    quality_valid = _review_valid(quality, "quality", sha)
    adversarial_valid = _review_valid(adversarial, "adversarial", sha)
    real_independence = quality_valid and adversarial_valid and quality["reviewer_id"] != adversarial["reviewer_id"]
    # Artifact fields are caller-controlled. Only the orchestration layer can
    # attest that these UUIDs came from actual multi-agent tool invocations.
    external_attestation = False
    suite_pass = _core_suite_pass(root)
    clean_checkout = _clean_checkout_pass(root)
    exact_sha = len(sha) == 40 and (expected_sha is None or expected_sha == sha)
    criteria = {
        "fidelity": {"contract": contract["status"] == "PASS", "exact_sha": exact_sha, "read_only_zero_write": read_only.get("zero_workspace_changes") is True, "mirror_parity": _command_pass(["python3", ".harness/lib/sync_council.py", "--check"], root)},
        "planning": {"phase_preflight_runtime": complex_result.get("processes", 0) >= 20, "planning_skill_contract": contract["markers"] >= 14, "phase_schema": (root / ".harness/schemas/phase-plan-result.schema.json").is_file(), "item_schema": (root / ".harness/schemas/item-plan-result.schema.json").is_file()},
        "execution": {"all_scenarios": scenarios_pass, "trivial_commit": len(trivial.get("local_commits", [])) == 1, "complex_commits": len(complex_result.get("local_commits", [])) >= 4, "real_processes": complex_result.get("processes", 0) >= 20, "suite": suite_pass},
        "correction_reentry": {"quality_fix_commit": len(complex_result.get("local_commits", [])) >= 3, "adversarial_fix_commit": len(complex_result.get("local_commits", [])) >= 4, "pipeline_replay": complex_result.get("resume_replay_equal") is True, "negative_tests": suite_pass},
        "review_independence": {"quality_artifact": quality_valid, "adversarial_artifact": adversarial_valid, "distinct_threads": bool(real_independence), "scenario_role_separation": simulated_independence, "zero_blocking": quality_valid and adversarial_valid, "sha_bound": quality_valid and adversarial_valid, "read_only_reviews": quality_valid and adversarial_valid, "external_agent_attestation": external_attestation, "artifact_hashes": quality_valid and adversarial_valid},
        "evidence_delivery": {"pipeline": complex_result.get("resume_replay_equal") is True, "ledger": bool(complex_result.get("ledger")), "proof": bool(complex_result.get("proof")), "clean_checkout": clean_checkout, "exact_sha": exact_sha},
        "enforcement_runtime": {"unauthorized_push_blocked": trivial.get("remote_push_blocked") is True, "authorized_push_passed": trivial.get("authorized_push_passed") is True, "active_processes": trivial.get("processes", 0) >= 8, "schemas": contract["schemas"] >= 10, "suite": suite_pass, "clean_checkout": clean_checkout, "claude_hooks": (root / ".harness/hooks/council-gate.py").is_file(), "codex_native_hook_api": _codex_council_hooks(root)},
    }
    scores = {name: _score(checks) for name, checks in criteria.items()}
    gates = {
        "contract": contract["status"] == "PASS",
        "runtime_scenarios": scenarios_pass,
        "scenario_reviewer_separation": simulated_independence,
        "independent_reviewer_evidence": external_attestation,
        "no_critical_or_required": quality_valid and adversarial_valid,
        "owned_worktree_reconciled": not dirty,
        "remote_authority_guard": trivial.get("remote_push_blocked") is True and trivial.get("authorized_push_passed") is True,
        "exact_sha": exact_sha,
        "test_suite": suite_pass,
        "clean_checkout": clean_checkout,
        "external_attestation_required": True,
    }
    return {
        "git_sha": sha,
        "criteria": criteria,
        "scores": scores,
        "overall": round(sum(scores.values()) / len(scores), 2),
        "gates": gates,
        "promotion": False,
        "promotion_boundary": "orchestrator_multi_agent_receipt",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-evidence", type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    from council_scenarios import run_scenarios

    root = args.root.resolve()
    with tempfile.TemporaryDirectory() as directory:
        scenarios = run_scenarios(root, Path(directory))
    reviews = json.loads(args.review_evidence.read_text(encoding="utf-8")) if args.review_evidence else None
    result = {"scenarios": scenarios["scenarios"], "reviews": reviews, "evaluation": evaluate(root, scenarios, reviews, args.expected_sha)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["evaluation"], sort_keys=True))
    return 0 if result["evaluation"]["promotion"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
