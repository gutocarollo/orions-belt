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
import json
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
AMENDMENT_BUDGET = 1200
DECISION_BUDGET = 2400
MAX_DECISION_CHARS = 320
DECISION_RE = re.compile(
    r"(?im)^\s*(D\d+)\s*(?:[-—:]\s*|\s+)(\S.*)$"
)
CURRENT_SOURCE_RE = re.compile(
    r"(?im)^source-ledger:\s*(session-[A-Za-z0-9_.-]+\.md)\s*$"
)


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


def event_session_id() -> str | None:
    try:
        raw = sys.stdin.read()
        value = json.loads(raw) if raw.strip() else {}
        session = str(value.get("session_id") or "").strip()
        return session.replace("/", "_")[:64] or None
    except Exception:
        return None


def select_ledger(reqdir: Path, session_id: str | None) -> Path | None:
    if session_id:
        exact = reqdir / f"session-{session_id}.md"
        if exact.is_file():
            return exact
        # A runtime-provided session id is an ownership boundary. Falling back
        # to the newest ledger here can inject another chat's objective into
        # this session before its own UserPromptSubmit ledger exists.
        return None
    ledgers = sorted(reqdir.glob("session-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return ledgers[0] if ledgers else None


def anchor_from_ledger(ledger: Path | None) -> str | None:
    if ledger is None:
        return None
    text = ledger.read_text(encoding="utf-8", errors="replace")
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
            if not DECISION_RE.search(block):
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


def decisions_from_ledger(ledger: Path | None) -> str:
    if ledger is None:
        return ""
    decision_path = ledger.with_name(ledger.stem + "-decisions.jsonl")
    latest: dict[str, dict[str, object]] = {}
    if decision_path.is_file():
        for line in decision_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
                latest[str(value["id"]).upper()] = value
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
    else:
        # Backward-compatible deterministic view for ledgers created before the
        # structured sidecar existed.
        text = ledger.read_text(encoding="utf-8", errors="replace")
        for seq, match in enumerate(DECISION_RE.finditer(text), start=1):
            latest[match.group(1).upper()] = {
                "id": match.group(1).upper(),
                "choice": match.group(2).strip(),
                "source_seq": seq,
            }
    kept: list[str] = []
    budget = DECISION_BUDGET
    ordered = sorted(latest.values(), key=lambda item: int(item.get("source_seq", 0)))
    for item in ordered[-24:]:
        choice = str(item.get("choice", "")).strip()
        if len(choice) > MAX_DECISION_CHARS:
            choice = choice[: MAX_DECISION_CHARS - 1].rstrip() + "…"
        line = f"- {item.get('id')}: {choice} [request:{item.get('source_seq')}]"
        if len(line) <= budget:
            kept.append(line)
            budget -= len(line)
    return "\n".join(kept)


def newest_ledger_mtime(reqdir: Path) -> float:
    return max(
        (p.stat().st_mtime for p in reqdir.glob("session-*.md")), default=0.0
    )


def current_matches_ledger(body: str, ledger: Path | None) -> bool:
    if ledger is None:
        return False
    match = CURRENT_SOURCE_RE.search(body)
    return bool(match and match.group(1) == ledger.name)


def main() -> int:
    try:
        reqdir = resolve_root() / ".harness" / "requests"
        ledger = select_ledger(reqdir, event_session_id()) if reqdir.is_dir() else None
        current = reqdir / "CURRENT-TASK.md"
        stale_note = ""
        if current.is_file():
            current_body = current.read_text(encoding="utf-8", errors="replace").strip()
            current_is_stale = newest_ledger_mtime(reqdir) - current.stat().st_mtime > 3600
            current_is_bound = current_matches_ledger(current_body, ledger)
            # G2: a CURRENT-TASK.md left over from a finished task would re-inject a
            # DEAD objective with blocking authority — the very drift this fights.
            # If the ledger has materially newer activity, flag it as maybe-stale.
            if current_is_stale or not current_is_bound:
                stale_note = (
                    "\nUNBOUND OR STALE CURRENT-TASK.md was ignored; only a task naming "
                    "the selected source-ledger may become session context.\n"
                )
                body = anchor_from_ledger(ledger)
                source = "request ledger ANCHOR + compact decisions"
            else:
                body = current_body
                source = "CURRENT-TASK.md (agent-curated)"
        else:
            body = anchor_from_ledger(ledger)
            source = "request ledger ANCHOR + compact decisions"
        if not body:
            return 0
        decisions = decisions_from_ledger(ledger)
        decision_block = (
            "\n<adopted-decisions>\n" + decisions + "\n</adopted-decisions>\n"
            if decisions
            else ""
        )
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
            + decision_block
            + "\n</original-request-anchor>"
        )
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
