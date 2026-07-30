#!/usr/bin/env python3
"""SessionStart hook — warns when the project edited INSIDE an orions-belt marked block.

WHY (adopter report, 2026-07-30). Three files are reconciled by `marked-block` strategy
(`.claude/CLAUDE.md`, `AGENTS.md`, `.gitignore` in a typical install). For those, the region between
`<!-- orions-belt:begin ... -->` and `<!-- orions-belt:end -->` is REPLACED wholesale on the next
apply, while everything above and below survives. The 170-odd `owned` paths are protected by a
fail-closed conflict in the apply engine; these are not, by design.

So an edit made inside the block is live today and gone after the next `harness-init` — with no
error, because from the engine's point of view nothing went wrong. A real adopter deleted a
frontend design-token canon from inside the block of a pure-Python backend and had no way to learn,
before running the installer, that the deletion was temporary.

`harness-install.sh` now asks for explicit approval and itemizes exactly this class of write, which
catches it at INSTALL time. This hook catches it earlier — at authoring time, in the session where
the edit was made — so the fix (move the text above/below the markers, or turn the capability off in
`.harness/answers.yml`) happens while the intent is still fresh.

Precision matters more than coverage here: the comparison is against
`last_applied_block_sha256` in `.harness/install-manifest.json`, which records the hash of the BLOCK
REGION alone. Comparing whole-file hashes would fire on every legitimate edit to the project's own
prose above the markers — a signal that cries wolf teaches the agent to ignore it, which is the
failure mode this hook exists to prevent, not to reproduce.

Fail-open by construction: any missing file, unreadable manifest or absent block prints nothing and
exits 0. A SessionStart hook must never be able to break a session.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

# Two marker syntaxes, because `.gitignore` has no comment form that starts with `<`: Markdown uses
# `<!-- orions-belt:begin ... -->` and `.gitignore` uses `# orions-belt:begin ...` (merge_docs.py
# BEGIN_RE/END_MARK and GITIGNORE_BEGIN_RE/GITIGNORE_END_MARK respectively). Handling only the HTML
# form silently skipped `.gitignore` — measured on a real install: 2 of 3 marked-block files got a
# block hash and the third got none, which would have left that file unguarded without any error.
_MARKERS = (
    (re.compile(rb"<!-- orions-belt:begin.*?-->", re.S), b"<!-- orions-belt:end -->"),
    (re.compile(rb"^# orions-belt:begin.*$", re.M), b"# orions-belt:end"),
)


def block_region(content: bytes) -> bytes | None:
    """The bytes BETWEEN the orions-belt markers, or None when the file carries no block."""
    for begin_re, end_mark in _MARKERS:
        begin = begin_re.search(content)
        if begin is None:
            continue
        end = content.find(end_mark, begin.end())
        if end == -1:
            continue
        return content[begin.end():end]
    return None


def main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    manifest_path = root / ".harness" / "install-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    files = manifest.get("files")
    if not isinstance(files, dict):
        return 0

    edited: list[str] = []
    unknown: list[str] = []
    for rel, entry in sorted(files.items()):
        if not isinstance(entry, dict) or entry.get("strategy") != "marked-block":
            continue
        if entry.get("orphaned"):
            continue
        try:
            content = (root / rel).read_bytes()
        except OSError:
            continue
        block = block_region(content)
        if block is None:
            continue
        recorded = entry.get("last_applied_block_sha256")
        if not isinstance(recorded, str):
            # Manifest predates block hashing: cannot decide, so say nothing rather than guess.
            unknown.append(rel)
            continue
        if hashlib.sha256(block).hexdigest() != recorded:
            edited.append(rel)

    if not edited and not unknown:
        return 0

    print("<harness-marked-block-guard>")
    if edited:
        print("The generated block was edited IN PLACE in the following file(s):")
        for rel in edited:
            print(f"  - {rel}")
        print("Everything between `<!-- orions-belt:begin ... -->` and `<!-- orions-belt:end -->`")
        print("is REPLACED by the next `harness-init`/`copier update`. These edits are temporary.")
        print("To keep them: move the text ABOVE or BELOW the markers (that region is the")
        print("project's and is never touched), or turn the capability off in .harness/answers.yml")
        print("so the block stops being rendered at all. The installer will also itemize this file")
        print("and ask for approval before writing — it will not overwrite silently.")
    if unknown:
        print("Block hash not recorded yet for: " + ", ".join(unknown))
        print("(manifest written before block-level hashing; the next apply records it)")
    print("</harness-marked-block-guard>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
