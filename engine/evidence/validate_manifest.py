#!/usr/bin/env python3
"""CLI for evidence manifest validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .manifest import EvidenceValidationError, assert_valid_manifest, canonical_hash
except ImportError:
    from manifest import EvidenceValidationError, assert_valid_manifest, canonical_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--verify-files", action="store_true")
    args = parser.parse_args()
    try:
        value = json.loads(args.manifest.read_text(encoding="utf-8"))
        assert_valid_manifest(value, args.manifest.parent, args.verify_files)
    except (OSError, json.JSONDecodeError, EvidenceValidationError) as exc:
        print(f"INVALID: {exc}")
        return 2
    print(f"VALID: {value['report_id']} sha256:{canonical_hash(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
