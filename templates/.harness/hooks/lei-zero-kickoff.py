#!/usr/bin/env python3
"""Inject compact reuse-first guidance for implementation kickoffs."""
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
MIN_LEN = 25

PROTOCOL = """<law-zero-protocol>
LAW ZERO — reuse before invention.
- Check the repo and mature external solutions before adding a new abstraction/dependency.
- Prefer existing local patterns or validated libraries; build from scratch only when reuse is materially worse or unavailable.
- Keep migrations/cross-cutting changes sequential and validated.
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
        return 0
    if KICKOFF_RE.search(prompt):
        print(PROTOCOL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
