#!/usr/bin/env python3
"""Claude hook adapter for Council guards; inactive without Council state."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2]))
LIB = ROOT / ".harness" / "lib"
if not LIB.is_dir():
    LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))
from council_hooks import post_tool_guard, pre_tool_guard, stop_guard  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=("pre", "post", "stop"))
    args = parser.parse_args()
    pointer = ROOT / ".harness" / "council-active"
    active = pointer.is_file()
    try:
        payload = json.load(sys.stdin)
        state_path = payload.get("council_state_path") or os.environ.get("COUNCIL_STATE_PATH")
        if not state_path and active:
            state_path = pointer.read_text(encoding="utf-8").strip()
        if "state" not in payload and state_path:
            payload["state"] = json.loads(Path(state_path).read_text(encoding="utf-8"))
        required_path = Path(state_path).with_suffix(".required-next") if state_path else None
        if args.event == "pre" and required_path and required_path.exists():
            print("Council requires VALIDATION before another edit", file=sys.stderr)
            return 2
        if not payload.get("state") and args.event != "post" and not active:
            return 0
        if active and not payload.get("state"):
            raise ValueError("active state missing")
        decision = {"pre": pre_tool_guard, "post": post_tool_guard, "stop": stop_guard}[args.event](payload)
    except (OSError, ValueError, TypeError) as exc:
        if active:
            print(f"BLOCKED: active Council state is unreadable: {exc}", file=sys.stderr)
            return 2
        return 0
    if not decision.get("allow", True):
        print(decision.get("reason", "Council gate blocked the transition"), file=sys.stderr)
        return 2
    if decision.get("required_next") and state_path:
        Path(state_path).with_suffix(".required-next").write_text(decision["required_next"] + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
