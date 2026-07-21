#!/usr/bin/env python3
"""CLI validator for one graph transition."""

from __future__ import annotations

import argparse

try:
    from .runtime import GraphError, find_transition, load_graph
except ImportError:  # direct `python3 engine/graph/validate_transition.py`
    from runtime import GraphError, find_transition, load_graph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("outcome")
    parser.add_argument("--graph")
    args = parser.parse_args()
    try:
        find_transition(load_graph(args.graph), args.source, args.target, args.outcome)
    except (GraphError, ValueError) as exc:
        print(f"INVALID: {exc}")
        return 2
    print(f"VALID: {args.source} --{args.outcome}--> {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
