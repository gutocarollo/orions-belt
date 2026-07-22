#!/usr/bin/env python3
"""request-reinject.py — SessionStart hook (both runtimes).

Re-surfaces the ORIGINAL REQUEST ANCHOR into context at session start — and
especially on `compact`/`resume`, where a summary has just replaced the verbatim
objective with a lossy paraphrase. This is the counter-measure to the single
most recurring drift: losing the primary objective under a pile of later
affirmations. It prints, verbatim:

  1. `.harness/requests/CURRENT-TASK.md` if present — the agent-curated anchor
     for the active task (original objective + explicitly-agreed amendments); OR
  2. the ANCHOR entry of the newest `.harness/requests/session-*.md` ledger.

It is context injection only (SessionStart stdout becomes model context); it
never blocks. Fail-open: any error -> exit 0 with no output.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def resolve_root() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if root:
        return Path(root)
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except Exception:
        pass
    return Path.cwd()


def anchor_from_ledger(reqdir: Path) -> str | None:
    ledgers = sorted(
        reqdir.glob("session-*.md"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not ledgers:
        return None
    text = ledgers[0].read_text(encoding="utf-8", errors="replace")
    # Blocks start at a "## [" heading; the ANCHOR block's heading ends with
    # " ANCHOR". (The intro blockquote also contains the word "ANCHOR", so match
    # the heading line, never a bare occurrence.)
    for chunk in text.split("\n## ["):
        head = chunk.split("\n", 1)[0]
        if head.rstrip().endswith("ANCHOR"):
            return ("## [" + chunk).strip()
    return None


def main() -> int:
    try:
        reqdir = resolve_root() / ".harness" / "requests"
        current = reqdir / "CURRENT-TASK.md"
        if current.is_file():
            body = current.read_text(encoding="utf-8", errors="replace").strip()
            source = "CURRENT-TASK.md (agent-curated)"
        else:
            body = anchor_from_ledger(reqdir) if reqdir.is_dir() else None
            source = "request ledger ANCHOR"
        if not body:
            return 0
        print(
            "<original-request-anchor source=\"" + source + "\">\n"
            "Re-anchor to the user's ORIGINAL objective below. Context compaction may have\n"
            "paraphrased it away. Before any completion claim, plan review or adversarial\n"
            "verification, confront the work against THIS (original objective + explicitly\n"
            "agreed amendments) — never only against the derived/intermediate plan. Silent\n"
            "objective or scope substitution is a BLOCKING defect.\n\n"
            + body
            + "\n</original-request-anchor>"
        )
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
