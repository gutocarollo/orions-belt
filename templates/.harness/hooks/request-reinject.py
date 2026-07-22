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
import re
import subprocess
import sys
from pathlib import Path

# Real ledger headings only: "## [YYYY-MM-DD HH:MM:SSZ] ANCHOR|amendment". Matching
# the timestamped heading (not a bare "## [") makes the block split fence-safe — a
# prompt that pastes markdown starting with "## [" no longer truncates the anchor (N2).
HEADING_RE = re.compile(r"(?m)^## \[\d{4}-\d{2}-\d{2} [\d:]+Z\] (ANCHOR|amendment)\s*$")
# Bound the re-injected amendment text so a long session does not dump dozens of
# blocks into every SessionStart (N1). The ANCHOR is always included in full.
AMENDMENT_BUDGET = 4000


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
    # Slice blocks at REAL headings (fence-safe, N2). Carry the ANCHOR in full plus
    # the user's later `amendment` entries newest-first within a char budget (N1),
    # so the reviewer sees the objective + recent changes without an unbounded dump.
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return None
    anchor_block: str | None = None
    amendments: list[str] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[m.start():end].rstrip()
        if m.group(1) == "ANCHOR" and anchor_block is None:
            anchor_block = block
        else:
            amendments.append(block)
    if anchor_block is None:
        return None
    kept: list[str] = []
    budget, omitted = AMENDMENT_BUDGET, 0
    for block in reversed(amendments):  # newest first
        if len(block) <= budget:
            kept.append(block)
            budget -= len(block)
        else:
            omitted += 1
    parts = [anchor_block]
    if omitted:
        parts.append(f"## (+{omitted} earlier amendment(s) omitted — see .harness/requests/)")
    parts.extend(reversed(kept))  # back to chronological
    return "\n\n".join(parts)


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
            "verification, confront the work against THIS — the original objective (ANCHOR)\n"
            "and the user's later messages (amendment entries: candidate clarifications/\n"
            "changes; only user-confirmed ones are agreed) — never only against the derived\n"
            "plan. Silent objective or scope substitution is a BLOCKING defect.\n"
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
