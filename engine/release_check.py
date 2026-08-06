#!/usr/bin/env python3
"""Single release gate with bounded subprocesses and JSON output.

This orchestrator does not duplicate test logic: every gate invokes the
repository's real validator/test entry point. A gate timeout is a failure,
and all selected gates run so the report contains the complete failure set.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
MAX_CAPTURE = 16_000


@dataclass(frozen=True)
class Gate:
    name: str
    command: tuple[str, ...]
    timeout_seconds: int = 120


GATES: tuple[Gate, ...] = (
    Gate("contract", ("python3", "engine/contract/scripts/validate_contract.py"), 180),
    Gate("graph_schema", ("python3", "engine/graph/validate_graph.py"), 30),
    Gate("graph_tests", ("python3", "-m", "unittest", "discover", "-s", "engine/graph/tests", "-v"), 60),
    Gate("evals", ("python3", "engine/evals/run_evals.py"), 60),
    Gate("eval_tests", ("python3", "-m", "unittest", "discover", "-s", "engine/evals/tests", "-v"), 60),
    Gate("observability_tests", ("python3", "-m", "unittest", "discover", "-s", "engine/observability/tests", "-v"), 60),
    Gate("knowledge_tests", ("python3", "-m", "unittest", "discover", "-s", "engine/knowledge/tests", "-v"), 60),
    Gate("ingest_tests", ("python3", "-m", "unittest", "discover", "-s", "engine/ingest/tests", "-v"), 60),
    Gate("corpus_freshness", ("python3", "engine/ingest/check_freshness.py"), 180),
    Gate("proof_tests", ("python3", "templates/.harness/lib/tests/test_proof_evidence.py", "-v"), 60),
    Gate("evidence_tests", ("python3", "-m", "unittest", "discover", "-s", "engine/evidence/tests", "-v"), 60),
    Gate("integration_tests", ("python3", "-m", "unittest", "discover", "-s", "engine/integration/tests", "-v"), 60),
    Gate("schema_negative_tests", ("python3", "-m", "unittest", "discover", "-s", "engine/tests", "-p", "test_schema_negative.py", "-v"), 60),
    Gate("template_python", ("python3", "-m", "unittest", "discover", "-s", "templates/tests", "-p", "test_*.py", "-v"), 180),
    Gate("template_shell", ("python3", "engine/release_check.py", "--internal-template-shell"), 900),
    Gate("docs", ("python3", "engine/lint/docs_wiki_lint.py"), 180),
    Gate("readme_freshness", ("python3", "engine/lint/readme_freshness.py"), 30),
    Gate("references", ("python3", "engine/lint/ref_integrity.py", "--since", "HEAD"), 180),
    Gate("template_boundary", ("python3", "-m", "unittest", "engine.tests.test_template_boundary", "-v"), 60),
    Gate("distribution_boundary", ("python3", "-m", "unittest", "engine.tests.test_distribution_boundary", "-v"), 60),
    Gate("diff_check", ("git", "diff", "--check", "HEAD", "--"), 30),
)


def _captured(value: str) -> str:
    if len(value) <= MAX_CAPTURE:
        return value
    return value[:MAX_CAPTURE] + f"\n...[truncated {len(value) - MAX_CAPTURE} chars]"


def run_gate(gate: Gate, root: Path = ROOT) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            gate.command, cwd=root, capture_output=True, text=True,
            timeout=gate.timeout_seconds, check=False,
        )
        return {
            "name": gate.name, "status": "PASS" if proc.returncode == 0 else "FAIL",
            "exit_code": proc.returncode, "timed_out": False,
            "duration_seconds": round(time.monotonic() - started, 3),
            "command": list(gate.command), "stdout": _captured(proc.stdout), "stderr": _captured(proc.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "name": gate.name, "status": "FAIL", "exit_code": None, "timed_out": True,
            "duration_seconds": round(time.monotonic() - started, 3),
            "command": list(gate.command), "stdout": _captured(stdout), "stderr": _captured(stderr),
        }
    except OSError as exc:
        return {
            "name": gate.name, "status": "FAIL", "exit_code": None, "timed_out": False,
            "duration_seconds": round(time.monotonic() - started, 3),
            "command": list(gate.command), "stdout": "", "stderr": str(exc),
        }


def run_gates(gates: Sequence[Gate], root: Path = ROOT) -> dict[str, Any]:
    started = time.monotonic()
    results = [run_gate(gate, root) for gate in gates]
    passed = sum(item["status"] == "PASS" for item in results)
    return {
        "schema_version": "1.0", "status": "PASS" if passed == len(results) else "FAIL",
        "passed": passed, "failed": len(results) - passed, "total": len(results),
        "duration_seconds": round(time.monotonic() - started, 3), "gates": results,
    }


def run_template_shell_tests() -> int:
    tests = sorted((ROOT / "templates" / "tests").glob("test_*.sh"))
    if not tests:
        print("no template shell tests found", file=sys.stderr)
        return 2
    failures = 0
    for test in tests:
        try:
            proc = subprocess.run(["bash", str(test)], cwd=ROOT, timeout=300, check=False)
            if proc.returncode != 0:
                failures += 1
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(f"{test.name}: {exc}", file=sys.stderr)
            failures += 1
    return 0 if failures == 0 else 2


def _select(names: list[str]) -> list[Gate]:
    if not names:
        return list(GATES)
    requested = {item for value in names for item in value.split(",") if item}
    known = {gate.name for gate in GATES}
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(f"unknown gates: {', '.join(unknown)}")
    return [gate for gate in GATES if gate.name in requested]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", action="append", default=[], help="gate name or comma-separated names")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--internal-template-shell", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.internal_template_shell:
        return run_template_shell_tests()
    if args.list:
        print("\n".join(gate.name for gate in GATES))
        return 0
    try:
        report = run_gates(_select(args.only))
    except ValueError as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
