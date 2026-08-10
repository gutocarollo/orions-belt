#!/usr/bin/env python3
"""Deterministic P1-P6 evaluation for Context Delivery.

P1-P3 are derived from the repository and diff. P4-P5 are evidence gates
resolved during execution. P6 is derived from the declared task shape. The
module never asks a model to estimate facts that Git or provider receipts can
compute directly.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

CODE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".java", ".js", ".jsx", ".mjs",
    ".php", ".py", ".rb", ".rs", ".swift", ".ts", ".tsx", ".vue",
}


class PredicateError(ValueError):
    """A deterministic predicate could not be evaluated safely."""


def _run(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as exc:
        output = getattr(exc, "output", "")
        raise PredicateError(f"git {' '.join(args)} failed: {str(output).strip() or exc}") from exc


def _resolve_commit(root: Path, value: str, label: str) -> str:
    """Resolve one commit-ish before using it in a diff range.

    `subprocess` already prevents shell injection, but a revision beginning with
    `-` can still be interpreted as a Git option. Resolve each endpoint
    independently, reject control characters/options/range syntax, and use only
    the resulting 40-character object IDs in later commands.
    """
    ref = str(value).strip()
    if not ref or len(ref) > 1024:
        raise PredicateError(f"{label} must be a non-empty Git commit-ish")
    if ref.startswith("-") or ".." in ref or any(ord(char) < 32 or ord(char) == 127 for char in ref):
        raise PredicateError(f"unsafe {label}: {value!r}")
    resolved = _run(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", resolved):
        raise PredicateError(f"{label} did not resolve to a full commit SHA: {value!r}")
    return resolved.lower()


def _split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def evaluate_repository_predicates(
    root: Path,
    *,
    base_ref: str,
    head_ref: str = "HEAD",
    core_paths: str | list[str] | None = None,
    data_write_patterns: str | None = None,
    task_shape: str,
    claims_completeness: bool = False,
) -> dict[str, dict[str, Any]]:
    """Compute P1, P2, P3 and P6 from Git and the task declaration.

    P4 (symbol ambiguity) and P5 (provider freshness) begin UNKNOWN because
    their truth depends on runtime tool output. CONTEXT-DELIVERY must resolve
    them before a claim that depends on them can be authorized.
    """
    root = root.resolve()
    if not (root / ".git").exists():
        raise PredicateError(f"not a Git repository: {root}")
    task_shape = task_shape.upper().strip()
    base_sha = _resolve_commit(root, base_ref, "base_ref")
    head_sha = _resolve_commit(root, head_ref, "head_ref")
    revision_range = f"{base_sha}...{head_sha}"
    names_text = _run(root, "diff", "--name-only", revision_range, "--")
    changed = sorted({line.strip() for line in names_text.splitlines() if line.strip()})
    code_files = [path for path in changed if Path(path).suffix.lower() in CODE_SUFFIXES]
    configured_core = _split_csv(core_paths)
    core_hits = [path for path in changed if any(path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/") for prefix in configured_core)]

    patch = ""
    write_hits: list[str] = []
    if data_write_patterns:
        try:
            pattern = re.compile(data_write_patterns, re.IGNORECASE)
        except re.error as exc:
            raise PredicateError(f"invalid data-write pattern: {exc}") from exc
        patch = _run(root, "diff", "--unified=0", revision_range, "--")
        current_path = ""
        for line in patch.splitlines():
            if line.startswith("+++ b/"):
                current_path = line[6:]
            elif line.startswith("+") and not line.startswith("+++") and pattern.search(line[1:]):
                write_hits.append(current_path or "<unknown>")
        write_hits = sorted(set(write_hits))

    high_radius = bool(core_hits or len(code_files) >= 3 or write_hits or claims_completeness)
    return {
        "P1": {
            "name": "touches_shared_core",
            "status": bool(core_hits),
            "source": "git-diff",
            "command": f"git diff --name-only {revision_range} --",
            "requested_refs": {"base": base_ref, "head": head_ref},
            "resolved_refs": {"base": base_sha, "head": head_sha},
            "evidence": core_hits,
        },
        "P2": {
            "name": "multi_file_change",
            "status": len(code_files) >= 3,
            "source": "git-diff",
            "command": f"git diff --name-only {revision_range} --",
            "requested_refs": {"base": base_ref, "head": head_ref},
            "resolved_refs": {"base": base_sha, "head": head_sha},
            "evidence": code_files,
            "measured": len(code_files),
            "threshold": 3,
        },
        "P3": {
            "name": "database_write",
            "status": bool(write_hits),
            "source": "git-diff",
            "command": f"git diff --unified=0 {revision_range} --",
            "requested_refs": {"base": base_ref, "head": head_ref},
            "resolved_refs": {"base": base_sha, "head": head_sha},
            "evidence": write_hits,
        },
        "P4": {
            "name": "symbol_ambiguous",
            "status": "UNKNOWN",
            "source": "runtime-tool-receipt",
            "command": None,
            "evidence": [],
        },
        "P5": {
            "name": "graph_fresh",
            "status": "UNKNOWN",
            "source": "runtime-provider-receipt",
            "command": None,
            "evidence": [],
        },
        "P6": {
            "name": "dynamic_state_or_control_flow",
            "status": task_shape == "DYNAMIC_STATE_FLOW",
            "source": "task-shape",
            "command": None,
            "evidence": [task_shape],
        },
        "derived": {
            "name": "high_radius",
            "status": high_radius,
            "source": "P1|P2|P3|completeness",
            "command": None,
            "evidence": [
                *(["P1"] if core_hits else []),
                *(["P2"] if len(code_files) >= 3 else []),
                *(["P3"] if write_hits else []),
                *(["claims_completeness"] if claims_completeness else []),
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--core-paths", default="")
    parser.add_argument("--data-write-patterns", default="")
    parser.add_argument("--task-shape", required=True)
    parser.add_argument("--claims-completeness", action="store_true")
    args = parser.parse_args()
    value = evaluate_repository_predicates(
        Path(args.root),
        base_ref=args.base,
        head_ref=args.head,
        core_paths=args.core_paths,
        data_write_patterns=args.data_write_patterns,
        task_shape=args.task_shape,
        claims_completeness=args.claims_completeness,
    )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
