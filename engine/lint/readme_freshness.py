#!/usr/bin/env python3
"""README.md claim-freshness gate. Origin: Augusto, 2026-07-22 ("já pedi milhões
de vezes para atualizar o README... precisa ter um hook determinístico"). Not
"anything changed, touch the README" (too noisy — most commits legitimately
don't need a README change and that trigger would train `--no-verify` habits).
Instead: README.md makes a small set of SPECIFIC numeric claims (hook count,
release-gate count, corpus counts); this script recomputes each one from the
real repo state and FAILS if any diverge. Same class of guard as ds-gate.sh's
ratchet and docs_wiki_lint.py's checks — deterministic, not "AI remembers to".

Dogfood-only (this repo's own README.md), not materialized into
templates/ — a target project's README has no "134 corpus records" claim to
check; this is specific to orions-belt's own promotional/product README.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


def _fail(reason: str) -> str:
    return reason


def check_hook_count() -> list[str]:
    text = README.read_text(encoding="utf-8")
    m = re.search(
        r"(\d+) hook scripts shipped \((\d+) install by default, (\d+) are stack-conditional\)",
        text,
    )
    if not m:
        return [_fail("README no longer contains the 'N hook scripts shipped (M install by default, K stack-conditional)' claim — "
                       "update this checker's regex if the wording changed intentionally")]
    claimed_total, claimed_default, claimed_conditional = (int(g) for g in m.groups())

    claude_settings = ROOT / "templates" / "{% if use_claude %}.claude{% endif %}" / "settings.json.jinja"
    codex_hooks = ROOT / "templates" / "{% if use_codex %}.codex{% endif %}" / "hooks.json.jinja"
    ref_pattern = re.compile(r"\.harness/hooks/([\w.{}%\s-]+?\.(?:sh|py))")
    claude_scripts = set(ref_pattern.findall(claude_settings.read_text(encoding="utf-8")))
    codex_scripts = set(ref_pattern.findall(codex_hooks.read_text(encoding="utf-8")))

    failures: list[str] = []
    if claude_scripts != codex_scripts:
        only_claude = claude_scripts - codex_scripts
        only_codex = codex_scripts - claude_scripts
        failures.append(
            f"hook registration diverges between runtimes (claude-only: {sorted(only_claude)}, "
            f"codex-only: {sorted(only_codex)}) — README's single hook count assumes parity"
        )

    # Conditionality is a property of the hook's OWN file in templates/.harness/hooks/
    # (its basename is wrapped `{% if var %}name.sh{% endif %}.jinja` when stack-conditional),
    # not something reliably inferrable from the settings.json/hooks.json reference context.
    hooks_dir = ROOT / "templates" / ".harness" / "hooks"
    conditional_basenames = set()
    for f in hooks_dir.iterdir():
        if "{%" in f.name:
            m = re.search(r"%\}([\w.-]+\.(?:sh|py))\{%", f.name)
            if m:
                conditional_basenames.add(m.group(1))

    real_scripts = claude_scripts | codex_scripts
    real_total = len(real_scripts)
    real_conditional = len(real_scripts & conditional_basenames)
    real_default = real_total - real_conditional

    if (claimed_total, claimed_default, claimed_conditional) != (real_total, real_default, real_conditional):
        failures.append(
            f"README claims {claimed_total} hook scripts ({claimed_default} default, {claimed_conditional} conditional), "
            f"but {real_total} distinct scripts are registered ({real_default} default, {real_conditional} conditional) "
            f"in templates/.harness/hooks/ per settings.json.jinja/hooks.json.jinja. "
            f"Real set: {sorted(claude_scripts | codex_scripts)}"
        )
    return failures


def check_gate_count() -> list[str]:
    text = README.read_text(encoding="utf-8")
    m = re.search(r"currently (\d+) gates, all local", text)
    if not m:
        return [_fail("README no longer contains the 'currently N gates, all local' claim — "
                       "update this checker's regex if the wording changed intentionally")]
    claimed = int(m.group(1))
    release_check = (ROOT / "engine" / "release_check.py").read_text(encoding="utf-8")
    real = len(re.findall(r"\bGate\(", release_check))
    if claimed != real:
        return [f"README claims {claimed} release gates, but engine/release_check.py defines {real} Gate(...) entries"]
    return []


def check_corpus_numbers() -> list[str]:
    text = README.read_text(encoding="utf-8")
    m = re.search(
        r"(\d[\d,]*) records \((\d[\d,]*) bytes\), (\d+) validated, (\d+) quarantined",
        text,
    )
    summary_path = ROOT / "engine" / "ingest" / "evidence" / "firecrawl-summary.json"
    if not m:
        if summary_path.is_file():
            return [_fail("README no longer contains the corpus 'N records (...), M validated, K quarantined' claim "
                           "but engine/ingest/evidence/firecrawl-summary.json exists — update this checker or the claim")]
        return []
    if not summary_path.is_file():
        return [_fail("README claims specific corpus numbers, but engine/ingest/evidence/firecrawl-summary.json is missing")]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    claimed_records, claimed_bytes, claimed_validated, claimed_quarantined = (
        int(m.group(1).replace(",", "")), int(m.group(2).replace(",", "")),
        int(m.group(3)), int(m.group(4)),
    )
    real = (
        summary.get("total_records"), summary.get("total_bytes"),
        summary.get("accepted"), summary.get("quarantined"),
    )
    claimed = (claimed_records, claimed_bytes, claimed_validated, claimed_quarantined)
    if claimed != real:
        return [f"README claims corpus {claimed} (records, bytes, validated, quarantined), but firecrawl-summary.json has {real}"]
    return []


CHECKS = (check_hook_count, check_gate_count, check_corpus_numbers)


def main() -> int:
    if not README.is_file():
        print("readme-freshness: SKIP (no README.md at repo root)")
        return 0
    failures: list[str] = []
    for check in CHECKS:
        failures.extend(check())
    if failures:
        print("readme-freshness: FAIL")
        for f in failures:
            print(f"- {f}")
        return 1
    print("readme-freshness: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
