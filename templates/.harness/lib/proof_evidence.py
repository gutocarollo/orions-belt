#!/usr/bin/env python3
"""Execute proof commands and verify the resulting local evidence manifest.

This raises the completion gate from prose lint to command-backed attestation.
It is intentionally not a cryptographic trust boundary: a process that can edit
the repository can still forge files. When the risk policy requires separation,
use an independent executor; hosted CI is one optional adapter, not a dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def _is_python_executable(name: str) -> bool:
    return re.fullmatch(r"python(?:3(?:\.\d+)?)?", name) is not None


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_sha(root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "NO_GIT"


def _workspace_sha(root: Path, excluded: set[str] | None = None) -> str:
    """Bind evidence to tracked diffs and untracked file bytes, not only HEAD."""
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root, capture_output=True,
    )
    diff = subprocess.run(["git", "diff", "--binary", "HEAD", "--"], cwd=root, capture_output=True)
    excluded = excluded or set()
    entries = [entry for entry in status.stdout.split(b"\0") if entry]
    kept = []
    for entry in entries:
        rel = entry[3:].decode("utf-8", errors="surrogateescape")
        if rel in excluded or "__pycache__/" in rel or rel.endswith((".pyc", ".pyo")):
            continue
        kept.append(entry)
    digest = hashlib.sha256(b"\0".join(kept) + b"\0" + diff.stdout)
    for entry in kept:
        if not entry.startswith(b"?? "):
            continue
        rel = entry[3:].decode("utf-8", errors="surrogateescape")
        path = root / rel
        if path.is_file() and not path.is_symlink() and not rel.startswith(".harness/evidence/"):
            digest.update(rel.encode("utf-8", errors="surrogateescape"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _root() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(proc.stdout.strip()).resolve() if proc.returncode == 0 else Path.cwd().resolve()


def run(args: argparse.Namespace) -> int:
    root = _root()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        raise SystemExit("proof_evidence run requires a command after --")
    executable = Path(command[0]).name
    allowed = {
        "test": {"python", "python3", "pytest", "unittest", "bash", "sh", "npm", "pnpm", "yarn", "make"},
        "static": {"rg", "grep", "git"},
        "endpoint": {"curl"},
        "visual": {"python", "python3", "npm", "pnpm", "yarn", "npx"},
    }
    python_allowed = args.type in {"test", "visual"} and _is_python_executable(executable)
    if executable not in allowed[args.type] and not python_allowed:
        raise SystemExit(f"command {executable!r} is not valid for evidence type {args.type!r}")
    started = datetime.now(timezone.utc)
    proc = subprocess.run(command, cwd=root, capture_output=True, text=True)
    ended = datetime.now(timezone.utc)
    output = (proc.stdout + proc.stderr).encode("utf-8", errors="replace")
    decoded_output = output.decode("utf-8", errors="replace")
    semantic_valid = _semantic_valid(args.type, command, decoded_output, proc.returncode)
    record = {
        "id": args.id,
        "evidence_type": args.type,
        "argv": command,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "exit_code": proc.returncode,
        "semantic_valid": semantic_valid,
        "output_sha256": _sha(output),
        "output_bytes": len(output),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "git_sha": _git_sha(root),
        "workspace_sha256": _workspace_sha(root, {Path(args.manifest).as_posix()}),
        "manifest_path": Path(args.manifest).as_posix(),
        "recorded_at": ended.isoformat(),
        "records": [record],
    }
    destination = (root / args.manifest).resolve()
    if root not in destination.parents:
        raise SystemExit("manifest must stay inside the repository")
    raw_destination = root / args.manifest
    if raw_destination.is_symlink():
        raise SystemExit("manifest must not be a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and not destination.is_symlink():
        try:
            previous = json.loads(destination.read_text(encoding="utf-8"))
            if previous.get("schema_version") == SCHEMA_VERSION and previous.get("git_sha") == manifest["git_sha"]:
                records = [row for row in previous.get("records", []) if row.get("id") != args.id]
                manifest["records"] = records + [record]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sys.stdout.buffer.write(output)
    return proc.returncode if proc.returncode != 0 else (0 if semantic_valid else 2)


def _semantic_valid(kind: str, command: list[str], output: str, exit_code: int) -> bool:
    if exit_code != 0:
        return False
    if kind == "test":
        executable = Path(command[0]).name
        is_unittest = _is_python_executable(executable) and command[1:3] == ["-m", "unittest"] and not any(arg in {"-h", "--help"} for arg in command)
        if is_unittest and re.search(r"\bRan\s+[1-9]\d*\s+tests?\b", output) and re.search(r"^OK\b", output, re.M):
            return True
        is_pytest = executable in {"pytest", "py.test"} and not any(arg in {"-h", "--help"} for arg in command)
        if is_pytest and re.search(r"\b[1-9]\d*\s+passed\b", output, re.I):
            return True
        try:
            report = json.loads(output)
            is_release = _is_python_executable(executable) and len(command) > 1 and Path(command[1]).name == "release_check.py"
            return is_release and report.get("schema_version") == "1.0" and report.get("status") == "PASS" and int(report.get("total", 0)) > 0 and int(report.get("failed", 1)) == 0 and len(report.get("gates", [])) == int(report["total"])
        except (ValueError, TypeError, json.JSONDecodeError):
            return False
    if kind == "static":
        return bool(output.strip())
    if kind == "endpoint":
        return bool(re.search(r"\b2\d\d\b", output))
    if kind == "visual":
        return bool(output.strip()) and any(token in output.lower() for token in ("manifest", ".json", ".png"))
    return False


def verify_manifest(path: Path, root: Path | None = None) -> tuple[bool, str]:
    root = (root or _root()).resolve()
    try:
        resolved = path.resolve()
        if root not in resolved.parents or resolved.is_symlink():
            return False, "evidence path escapes repository or is a symlink"
        data = json.loads(resolved.read_text(encoding="utf-8"))
        recorded = datetime.fromisoformat(data["recorded_at"])
        age = datetime.now(timezone.utc) - recorded.astimezone(timezone.utc)
        records = data["records"]
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return False, f"invalid evidence manifest: {exc}"
    if data.get("schema_version") != SCHEMA_VERSION:
        return False, "unsupported evidence schema"
    if data.get("git_sha") != _git_sha(root):
        return False, "evidence git_sha does not match HEAD"
    manifest_rel = data.get("manifest_path")
    if not isinstance(manifest_rel, str) or data.get("workspace_sha256") != _workspace_sha(root, {manifest_rel}):
        return False, "evidence workspace fingerprint is stale"
    if age.total_seconds() < -60 or age.total_seconds() > 8 * 3600:
        return False, "evidence is not from the current execution window"
    if not isinstance(records, list) or not records:
        return False, "evidence has no command records"
    if any(not isinstance(row, dict) or not row.get("argv") or not isinstance(row.get("semantic_valid"), bool) or row.get("evidence_type") not in {"test", "static", "endpoint", "visual"} for row in records):
        return False, "evidence contains a malformed command"
    ids = [row.get("id") for row in records]
    if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
        return False, "evidence item IDs are missing or duplicated"
    return True, f"{len(records)} command record(s) verified"


def summary(path: Path, root: Path | None = None) -> tuple[int, int, list[str]]:
    ok, reason = verify_manifest(path, root)
    if not ok:
        raise ValueError(reason)
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data["records"]
    gaps = [row["id"] for row in records if row["exit_code"] != 0 or not row["semantic_valid"]]
    return len(records) - len(gaps), len(records), gaps


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--id", required=True)
    runner.add_argument("--manifest", required=True)
    runner.add_argument("--type", required=True, choices=("test", "static", "endpoint", "visual"))
    runner.add_argument("command", nargs=argparse.REMAINDER)
    verifier = sub.add_parser("verify")
    verifier.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.action == "run":
        return run(args)
    ok, reason = verify_manifest(Path(args.manifest))
    print(reason)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
