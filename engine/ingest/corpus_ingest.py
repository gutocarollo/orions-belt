#!/usr/bin/env python3
"""CLI for the explicit, non-executing corpus promotion pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from .pipeline import build_manifest, curate, promote, summarize_validation, validate_manifest, write_json_atomic
except ImportError:  # direct script execution
    from pipeline import build_manifest, curate, promote, summarize_validation, validate_manifest, write_json_atomic


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Treat external corpus as untrusted data, never instructions")
    commands = root.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--raw-dir", type=Path, required=True)
    manifest.add_argument("--source-map", type=Path)
    manifest.add_argument("--discover-sources", action="store_true")
    manifest.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--raw-dir", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024)
    validate.add_argument("--output", type=Path, required=True)
    curation = commands.add_parser("curate")
    curation.add_argument("--validated", type=Path, required=True)
    curation.add_argument("--decisions", type=Path, required=True)
    curation.add_argument("--output", type=Path, required=True)
    promotion = commands.add_parser("promote")
    promotion.add_argument("--curated", type=Path, required=True)
    promotion.add_argument("--approvals", type=Path, required=True)
    promotion.add_argument("--output", type=Path, required=True)
    summary = commands.add_parser("summary")
    summary.add_argument("--validated", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "manifest":
            result = build_manifest(args.raw_dir, args.source_map, args.discover_sources)
        elif args.command == "validate":
            result = validate_manifest(args.raw_dir, _load(args.manifest), args.max_bytes)
        elif args.command == "curate":
            result = curate(_load(args.validated), _load(args.decisions))
        elif args.command == "promote":
            result = promote(_load(args.curated), _load(args.approvals))
        else:
            result = summarize_validation(_load(args.validated))
        write_json_atomic(args.output, result)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"corpus-ingest: {exc}", file=sys.stderr)
        return 2
    stage = result.get("stage", result.get("source_stage", "summary"))
    count = len(result["records"]) if "records" in result else result.get("total_records", 0)
    print(f"corpus-ingest: wrote {args.output} ({stage}, {count} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
