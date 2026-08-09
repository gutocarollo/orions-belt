#!/usr/bin/env python3
"""Single entrypoint for the installed Delivery Council contract."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".harness" / "lib"))
from council_contract import ContractError, validate_contract  # noqa: E402
from sync_council import sync_council  # noqa: E402


def main() -> int:
    try:
        if sync_council(ROOT, check=True):
            raise ContractError("Council Claude/Agents surfaces drifted")
        report = validate_contract(ROOT)
        skills = subprocess.run([sys.executable, str(ROOT / ".harness" / "lib" / "validate_skills.py")], cwd=ROOT, capture_output=True, text=True)
        if skills.returncode:
            raise ContractError(skills.stdout + skills.stderr)
    except (OSError, ContractError, json.JSONDecodeError) as exc:
        print(f"council-contract: {exc}", file=sys.stderr)
        return 1
    print("council-contract-ok " + json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
