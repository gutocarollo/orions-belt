#!/usr/bin/env python3
"""Itemize an install plan for EXPLICIT human consent, before anything is written.

WHY THIS EXISTS (adopter report, 2026-07-30). The apply engine is already fail-closed for `owned`
files: a locally modified one raises `locally modified since the last harness apply` and aborts the
whole install without touching the target (`install_apply.py`, the `owned` branch of `build_plan`).
That protects the large majority — measured in a real adopter: 170 of 188 tracked paths.

The remaining classes are NOT protected, by design, and that is what surprised the adopter:

  * `marked-block` (`.claude/CLAUDE.md`, `AGENTS.md`, `.gitignore`) — the region BETWEEN the
    `<!-- orions-belt:begin ... -->` / `<!-- orions-belt:end -->` markers is REPLACED wholesale by
    the freshly rendered block. Content above and below survives; content the project wrote INSIDE
    the markers is discarded with no conflict, no prompt and no diff.
  * `structured-json` (`.claude/settings.json`) — semantically merged, hook by hook.

So a re-install could hand back canon the project had deliberately removed (the adopter's case: a
frontend design-token block re-appearing in a pure backend), and nothing in the flow ever asked.
`--dry-run` existed, but it was opt-in: the default path planned and applied in one breath.

WHAT THIS ADDS: the plan is computed with `--dry-run` FIRST, itemized here, and the apply only runs
after explicit approval. Default is REFUSE — a non-interactive caller without `--yes` gets a
non-zero exit and an untouched target, because "no answer" must never read as "yes".

Exit codes (consumed by harness-install.sh):
  0  nothing would change (every action is `unchanged`) — no consent needed
  10 mutating actions exist — consent required
  2  the plan file is missing or unreadable
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Strategies whose write REPLACES project-authored content without a conflict check. These are the
# ones a human must see itemized; `owned` cannot reach this point with local edits (the engine
# already aborts), and `preserve`/`seed` never overwrite.
SILENT_RECONCILE = {"marked-block", "structured-json"}
MUTATING = {"create", "update", "merge"}


def load_plan(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"install-consent: cannot read the plan at {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: install_consent.py <plan.json> [target]", file=sys.stderr)
        return 2
    plan_path = Path(sys.argv[1])
    target = sys.argv[2] if len(sys.argv) > 2 else "(target)"
    plan = load_plan(plan_path)

    files = [f for f in plan.get("files", []) if isinstance(f, dict)]
    mutating = [f for f in files if f.get("action") in MUTATING]
    if not mutating:
        print(f"install-consent: plan touches nothing in {target} (all {len(files)} paths unchanged).")
        return 0

    replace = [f for f in mutating if f.get("strategy") in SILENT_RECONCILE]
    rest: dict[str, list[dict]] = {}
    for f in mutating:
        if f.get("strategy") in SILENT_RECONCILE:
            continue
        rest.setdefault(f"{f.get('strategy')}/{f.get('action')}", []).append(f)

    print()
    print(f"install-consent: the harness wants to write {len(mutating)} path(s) in {target}.")
    print("Nothing has been written yet — this is the plan, not the result.")

    if replace:
        print()
        print("  REPLACES CONTENT THE PROJECT MAY HAVE AUTHORED — read these one by one:")
        for f in sorted(replace, key=lambda x: str(x.get("path"))):
            path, strategy, action = f.get("path"), f.get("strategy"), f.get("action")
            if strategy == "marked-block":
                what = ("the region between the orions-belt markers is REPLACED by the rendered "
                        "block; text above/below the markers is kept")
            else:
                what = "merged key by key into the existing JSON"
            print(f"    - {path}  [{strategy}, {action}]")
            print(f"        {what}")
        print()
        print("  If you deliberately removed canon from inside a marked block, approving this")
        print("  brings it back. Move what you want to keep ABOVE or BELOW the markers first, or")
        print("  turn the capability off in .harness/answers.yml so the block is not rendered.")

    if rest:
        print()
        print("  Ownership-checked writes (the engine aborts instead of clobbering a local edit):")
        for key in sorted(rest):
            items = rest[key]
            head = ", ".join(str(i.get("path")) for i in items[:4])
            more = f" (+{len(items) - 4} more)" if len(items) > 4 else ""
            print(f"    - {key}: {len(items)} path(s) — {head}{more}")

    counts = plan.get("counts", {})
    if counts:
        print()
        print("  plan counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print()
    return 10


if __name__ == "__main__":
    raise SystemExit(main())
