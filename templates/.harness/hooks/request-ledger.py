#!/usr/bin/env python3
"""request-ledger.py — UserPromptSubmit hook (both runtimes).

Appends every non-trivial user prompt VERBATIM (+ UTC timestamp) to
`.harness/requests/session-<id>.md`, an append-only record of what the user
ACTUALLY asked. This is the anchor against the single most recurring drift:
the original objective gets lossy-compressed by context compaction (and a
review subagent starts with a ZEROED context that never saw it), so audits end
up validating the derived/intermediate plan instead of the real request — the
"reviewed the wrong thing correctly" failure. The delivery-council and
adversarial-review skills read this ledger so every review confronts the
ORIGINAL objective + explicitly-agreed amendments, not the drifted plan.

The FIRST entry of a session ledger is the ANCHOR; later entries are amendments
(the user's explicitly-agreed changes). It never classifies intent — it records
verbatim, because a missed objective is catastrophic while an extra line is not.

Fail-open: any error -> exit 0 with no output. Never blocks the turn.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Trivial acks are not requests worth anchoring (continue/ok/yes/go/thanks ...).
TRIVIAL = re.compile(
    r"^(ok(ay)?|sim|n[aã]o|yes|no|yep|nope|vai|v[aá]|go|continue?|continua(r)?"
    r"|prossiga|segue|siga|proceed|thx|thanks?|obrigad[oa]|blz|beleza|isso|exato"
    r"|perfeito|\W*)$",
    re.IGNORECASE,
)
MIN_LEN = 12


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


def fence(text: str) -> str:
    """Verbatim block with a backtick fence long enough not to collide."""
    f = "````"
    while f in text:
        f += "`"
    return f"{f}text\n{text}\n{f}"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = (data.get("prompt") or data.get("user_prompt") or data.get("input") or "").strip()
    if not prompt or len(prompt) < MIN_LEN or TRIVIAL.match(prompt):
        return 0
    session = str(
        data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "current"
    ).replace("/", "_")[:64]
    try:
        reqdir = resolve_root() / ".harness" / "requests"
        reqdir.mkdir(parents=True, exist_ok=True)
        ledger = reqdir / f"session-{session}.md"
        new = not ledger.exists()
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        parts: list[str] = []
        if new:
            parts.append(
                f"# Request ledger — session {session}\n\n"
                "> Append-only, verbatim record of what the user asked. Immune to context\n"
                "> compaction. The delivery-council and adversarial-review skills MUST confront\n"
                "> the plan/execution against this — the ORIGINAL objective (ANCHOR) + explicitly\n"
                "> agreed amendments — never only the derived plan.\n"
            )
        kind = "ANCHOR" if new else "amendment"
        parts.append(f"\n## [{ts}] {kind}\n\n{fence(prompt)}\n")
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write("".join(parts))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
