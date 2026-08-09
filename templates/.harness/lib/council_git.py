#!/usr/bin/env python3
"""Authority-checked executor for Council local and remote Git delivery actions."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from council_runtime import remote_action_allowed


def load_authority(path: Path | None) -> dict[str, object]:
    if path is None or not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("authorization evidence must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("local-commit", "push", "merge-main"))
    parser.add_argument("--authorization", type=Path, default=Path(os.environ["COUNCIL_REMOTE_AUTHORIZATION"]) if os.environ.get("COUNCIL_REMOTE_AUTHORIZATION") else None)
    raw = sys.argv[1:]
    separator = raw.index("--") if "--" in raw else len(raw)
    args = parser.parse_args(raw[:separator])
    authority = load_authority(args.authorization)
    if not remote_action_allowed(args.action, authority):
        raise SystemExit(f"BLOCKED: Council {args.action} requires explicit remote authorization evidence")
    command = raw[separator + 1:] if separator < len(raw) else []
    if args.action == "push" and "--no-verify" in command:
        raise SystemExit("BLOCKED: Council push forbids --no-verify")
    if not command:
        print(f"council-git: {args.action} authorized")
        return 0
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
