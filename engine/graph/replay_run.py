#!/usr/bin/env python3
"""Replay a JSONL event log, optionally resuming from a checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .runtime import GraphError, load_graph, replay, restore_checkpoint
except ImportError:
    from runtime import GraphError, load_graph, replay, restore_checkpoint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("--graph")
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    try:
        events = [json.loads(line) for line in args.events.read_text(encoding="utf-8").splitlines() if line.strip()]
        base = restore_checkpoint(json.loads(args.checkpoint.read_text(encoding="utf-8"))) if args.checkpoint else None
        state = replay(events, load_graph(args.graph), base)
    except (OSError, json.JSONDecodeError, GraphError, ValueError) as exc:
        print(f"REPLAY FAILED: {exc}")
        return 2
    print(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
