#!/usr/bin/env python3
"""law-zero-kickoff — UserPromptSubmit hook.

When the prompt looks like a feature/refactor kickoff and does NOT mention LAW
ZERO, it injects the compact protocol as context (a UserPromptSubmit's stdout
becomes model context). Automates what the donor-harness owner used to paste by
hand every session. Origin: donor-harness friction audit, cluster 5.
Fail-open: any error → exit 0 with no output.
"""
import json
import re
import sys

KICKOFF_RE = re.compile(
    r"(?i)\b("
    r"implemente|implementar|desenvolv[ae]|crie|criar|adicione|adicionar"
    r"|monte\s+um\s+plano|nova\s+(feature|funcionalidade)"
    r"|refator[ae]|migr[ae]r?|constru[aií]"
    r"|implement|build\s+a|add\s+(a\s+)?feature"
    r")\b"
)
# short prompts ("continue", "fix it", pasted audits) are not a kickoff
MIN_LEN = 25

PROTOCOL = """<law-zero-protocol>
LAW ZERO (AGENTS.md/CLAUDE.md §0) — before implementing any non-trivial feature:
1. SEARCH for existing mature solutions (GitHub/awesome-lists via the last30days plugin when available; official docs via Context7). Investigate each feature individually.
2. Port/copy/reuse validated libs, code and patterns. Implement from scratch ONLY if nothing is reusable — and state why.
3. Check what the REPO ALREADY HAS before creating (grep the code, the dependency lockfile/manifest, the ⭐ CANONICAL REFERENCE blocks of AGENTS.md/CLAUDE.md).
4. Migrations/cross-cutting changes: SEQUENTIAL, one at a time, tested (§0.6, §14).
If the final plan reinvents something that already exists, the plan is wrong.
</law-zero-protocol>"""


def main():
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt") or ""
    except Exception:
        return 0
    if len(prompt) < MIN_LEN:
        return 0
    low = prompt.lower()
    if "lei zero" in low or "lei-zero" in low or "law zero" in low or "law-zero" in low:
        return 0  # the user already invoked the law explicitly
    if not KICKOFF_RE.search(prompt):
        return 0
    print(PROTOCOL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
