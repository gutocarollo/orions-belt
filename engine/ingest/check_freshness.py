#!/usr/bin/env python3
"""Fail-closed freshness check for committed Firecrawl ingestion evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.ingest.pipeline import build_manifest, summarize_validation, validate_manifest  # noqa: E402


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _without_clock(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "generated_at"}


def check_freshness(raw_dir: Path, evidence_dir: Path) -> list[str]:
    if not raw_dir.exists():
        return []  # conditional corpus: absence is explicitly not drift
    if not raw_dir.is_dir():
        return [f"raw corpus path is not a directory: {raw_dir}"]
    paths = {
        "manifest": evidence_dir / "firecrawl-manifest.json",
        "validated": evidence_dir / "firecrawl-validated.json",
        "summary": evidence_dir / "firecrawl-summary.json",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        return ["corpus is present but ingestion evidence is missing: " + ", ".join(missing)]
    try:
        stored_manifest = _load(paths["manifest"])
        stored_validated = _load(paths["validated"])
        stored_summary = _load(paths["summary"])
        fresh_manifest = build_manifest(raw_dir, discover_sources=True)
        fresh_validated = validate_manifest(raw_dir, stored_manifest)
        fresh_summary = summarize_validation(stored_validated)
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        return [f"cannot revalidate corpus evidence: {exc}"]
    errors: list[str] = []
    if _without_clock(fresh_manifest) != _without_clock(stored_manifest):
        errors.append("firecrawl-manifest.json drifted from raw corpus")
    if _without_clock(fresh_validated) != _without_clock(stored_validated):
        errors.append("firecrawl-validated.json drifted from raw corpus")
    if fresh_summary != stored_summary:
        errors.append("firecrawl-summary.json does not match validated evidence")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=_REPO_ROOT / ".firecrawl")
    parser.add_argument("--evidence-dir", type=Path, default=_REPO_ROOT / "engine" / "ingest" / "evidence")
    args = parser.parse_args()
    errors = check_freshness(args.raw_dir, args.evidence_dir)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, sort_keys=True))
        return 2
    status = "PASS" if args.raw_dir.exists() else "SKIP"
    print(json.dumps({"status": status, "raw_dir": str(args.raw_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
