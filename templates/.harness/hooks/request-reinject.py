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
    # Blocks start at a "## [" heading. Return the ANCHOR block AND every
    # `amendment` block — the directive promises "original objective + explicitly
    # agreed amendments", so it must actually carry them (G1). Skip the preamble
    # blockquote (index 0, before the first heading), which also contains the word
    # "ANCHOR" — match the heading line, never a bare occurrence.
    blocks: list[str] = []
    for i, chunk in enumerate(text.split("\n## [")):
        if i == 0:
            continue
        head = chunk.split("\n", 1)[0].rstrip()
        if head.endswith("ANCHOR") or head.endswith("amendment"):
            blocks.append(("## [" + chunk).rstrip())
    return "\n\n".join(blocks) if blocks else None


def newest_ledger_mtime(reqdir: Path) -> float:
    return max(
        (p.stat().st_mtime for p in reqdir.glob("session-*.md")), default=0.0
    )


def main() -> int:
    try:
        reqdir = resolve_root() / ".harness" / "requests"
        current = reqdir / "CURRENT-TASK.md"
        stale_note = ""
        if current.is_file():
            body = current.read_text(encoding="utf-8", errors="replace").strip()
            source = "CURRENT-TASK.md (agent-curated)"
            # G2: a CURRENT-TASK.md left over from a finished task would re-inject a
            # DEAD objective with blocking authority — the very drift this fights.
            # If the ledger has materially newer activity, flag it as maybe-stale.
            if newest_ledger_mtime(reqdir) - current.stat().st_mtime > 3600:
                stale_note = (
                    "\nSTALENESS WARNING: the request ledger has newer activity than this "
                    "CURRENT-TASK.md — it may describe a PREVIOUS task. Re-confirm against "
                    ".harness/requests/session-*.md, or let the Delivery Council rewrite it "
                    "at Flow step 0. A finished task's anchor must be cleared, not re-injected.\n"
                )
        else:
            body = anchor_from_ledger(reqdir) if reqdir.is_dir() else None
            source = "request ledger ANCHOR + amendments"
        if not body:
            return 0
        print(
            "<original-request-anchor source=\"" + source + "\">\n"
            "Re-anchor to the user's ORIGINAL objective below. Context compaction may have\n"
            "paraphrased it away. Before any completion claim, plan review or adversarial\n"
            "verification, confront the work against THIS (original objective + explicitly\n"
            "agreed amendments) — never only against the derived/intermediate plan. Silent\n"
            "objective or scope substitution is a BLOCKING defect.\n"
            + stale_note
            + "\n"
            + body
            + "\n</original-request-anchor>"
        )
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
