#!/usr/bin/env python3
"""Generate the Agents Council mirror from the canonical Claude skill."""

from __future__ import annotations

import argparse
from pathlib import Path


def council_paths(root: Path) -> tuple[Path, Path]:
    name = ""
    config = root / ".harness" / "harness.conf"
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            if line.startswith("HARNESS_COUNCIL_SKILL_NAME="):
                name = line.split("=", 1)[1].split("#", 1)[0].strip()
                break
    if not name:
        candidates = sorted((root / ".claude" / "skills").glob("*-delivery-council/SKILL.md"))
        candidates += sorted((root / ".agents" / "skills").glob("*-delivery-council/SKILL.md"))
        if len(candidates) == 1:
            name = candidates[0].parent.name
    name = name or "project-delivery-council"
    relative = Path("skills") / name / "SKILL.md"
    return root / ".claude" / relative, root / ".agents" / relative


def sync_council(root: Path, *, check: bool) -> bool:
    source, target = council_paths(root)
    if not source.is_file() or not target.is_file():
        return False
    different = source.read_bytes() != target.read_bytes()
    if different and not check:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    return different


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    drift = sync_council(args.root.resolve(), check=args.check)
    if args.check and drift:
        print("council-runtime-drift")
        return 1
    print("council-surfaces-ok" if not drift else "council-surface-generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
