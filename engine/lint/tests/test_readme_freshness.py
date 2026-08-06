#!/usr/bin/env python3
"""Fixture-isolated tests for readme_freshness.py — do not depend on this
repo's real current numbers (hook count, gate count, corpus counts), which
drift over time; each test builds its own minimal repo skeleton and points
the module at it via monkeypatched ROOT/README module globals."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "readme_freshness.py"
spec = importlib.util.spec_from_file_location("readme_freshness", MODULE_PATH)
readme_freshness = importlib.util.module_from_spec(spec)
sys.modules["readme_freshness"] = readme_freshness
spec.loader.exec_module(readme_freshness)


def _build_repo(root: Path, hook_count_claim: str = "5 hook scripts shipped (3 install by default, 2 are stack-conditional)",
                 gate_count_claim: str = "currently 20 gates, all local",
                 corpus_claim: str = "134 records (4,158,372 bytes), 80 validated, 54 quarantined",
                 real_gates: int = 20, real_corpus: tuple = (134, 4158372, 80, 54)) -> None:
    (root / "README.md").write_text(
        f"| hooks | {hook_count_claim} |\nfail-closed release check — {gate_count_claim} — measure the system.\n"
        f"only manifest/validation evidence: {corpus_claim}, 118 with a source URL.\n",
        encoding="utf-8",
    )
    engine = root / "engine"
    (engine / "release_check.py").parent.mkdir(parents=True, exist_ok=True)
    (engine / "release_check.py").write_text("GATES = (\n" + "\n".join(f'    Gate("g{i}", (), 1),' for i in range(real_gates)) + "\n)\n", encoding="utf-8")
    ingest_evidence = engine / "ingest" / "evidence"
    ingest_evidence.mkdir(parents=True, exist_ok=True)
    (ingest_evidence / "firecrawl-summary.json").write_text(json.dumps({
        "total_records": real_corpus[0], "total_bytes": real_corpus[1],
        "accepted": real_corpus[2], "quarantined": real_corpus[3],
    }), encoding="utf-8")

    hooks_dir = root / "templates" / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    unconditional = ["completion-gate.py", "git-doctor.sh", "lessons-inject.sh"]
    conditional = ["ui-evidence-gate.sh", "ds-gate-posttool.sh"]
    for name in unconditional:
        (hooks_dir / f"{name}.jinja" if not name.endswith(".py") else hooks_dir / name).write_text("", encoding="utf-8")
    for name in conditional:
        (hooks_dir / ("{% if flag %}" + name + "{% endif %}.jinja")).write_text("", encoding="utf-8")

    claude_dir = root / "templates" / "{% if use_claude %}.claude{% endif %}"
    claude_dir.mkdir(parents=True, exist_ok=True)
    codex_dir = root / "templates" / "{% if use_codex %}.codex{% endif %}"
    codex_dir.mkdir(parents=True, exist_ok=True)
    all_scripts = unconditional + conditional
    refs = "\n".join(f'"command": "bash .harness/hooks/{s}"' if not s.endswith(".py") else f'"command": "python3 .harness/hooks/{s}"' for s in all_scripts)
    (claude_dir / "settings.json.jinja").write_text(refs, encoding="utf-8")
    (codex_dir / "hooks.json.jinja").write_text(refs, encoding="utf-8")


class ReadmeFreshnessTest(unittest.TestCase):
    def _run(self, root: Path):
        readme_freshness.ROOT = root
        readme_freshness.README = root / "README.md"
        return readme_freshness.main()

    def test_matching_claims_pass(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="readme-freshness-ok-"))
        _build_repo(root)
        self.assertEqual(0, self._run(root))

    def test_wrong_hook_count_fails(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="readme-freshness-hooks-"))
        _build_repo(root, hook_count_claim="99 hook scripts shipped (95 install by default, 4 are stack-conditional)")
        self.assertEqual(1, self._run(root))

    def test_wrong_gate_count_fails(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="readme-freshness-gates-"))
        _build_repo(root, gate_count_claim="currently 999 gates, all local")
        self.assertEqual(1, self._run(root))

    def test_wrong_corpus_numbers_fail(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="readme-freshness-corpus-"))
        _build_repo(root, corpus_claim="134 records (4,158,372 bytes), 999 validated, 54 quarantined")
        self.assertEqual(1, self._run(root))

    def test_missing_readme_is_a_skip_not_a_failure(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="readme-freshness-missing-"))
        root.mkdir(parents=True, exist_ok=True)
        self.assertEqual(0, self._run(root))

    def test_runtime_registration_mismatch_is_flagged(self) -> None:
        # Claude and Codex must register the same hook set; a divergence is real drift,
        # not something the numeric-claim comparison alone would catch cleanly.
        root = Path(tempfile.mkdtemp(prefix="readme-freshness-mismatch-"))
        _build_repo(root)
        codex_hooks = root / "templates" / "{% if use_codex %}.codex{% endif %}" / "hooks.json.jinja"
        codex_hooks.write_text('"command": "bash .harness/hooks/completion-gate.py"', encoding="utf-8")
        self.assertEqual(1, self._run(root))


if __name__ == "__main__":
    unittest.main()
