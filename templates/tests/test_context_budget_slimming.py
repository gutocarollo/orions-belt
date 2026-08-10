from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CouncilContextSlimmingTest(unittest.TestCase):
    def test_context_workers_are_bounded_and_do_not_preload_full_skills(self):
        claude_scout = (ROOT / "templates/{% if use_claude %}.claude{% endif %}/agents/{{ project_name }}-context-scout.md.jinja").read_text()
        claude_shard = (ROOT / "templates/{% if use_claude and use_context_delivery %}.claude{% endif %}/agents/{{ project_name }}-context-shard.md.jinja").read_text()
        codex_scout = (ROOT / "templates/{% if use_codex %}.codex{% endif %}/agents/{{ project_name }}-context-scout.toml.jinja").read_text()
        self.assertIn("maxTurns: 16", claude_scout)
        self.assertIn("maxTurns: 6", claude_shard)
        self.assertNotIn("skills:", claude_scout)
        self.assertNotIn("skills:", claude_shard)
        self.assertLess(len(codex_scout), 3000)

    def test_prompt_kickoffs_stay_compact(self):
        exploration = (ROOT / "templates/.harness/hooks/{% if use_exploration_protocol %}exploration-kickoff.py{% endif %}.jinja").read_text()
        law = (ROOT / "templates/.harness/hooks/lei-zero-kickoff.py").read_text()
        route = re.search(r'ROUTING = """(.*?)"""', exploration, re.S)
        protocol = re.search(r'PROTOCOL = """(.*?)"""', law, re.S)
        self.assertIsNotNone(route)
        self.assertIsNotNone(protocol)
        self.assertLess(len(route.group(1)), 1800)
        self.assertLess(len(protocol.group(1)), 600)
        self.assertIn("EXPLORATION STANDARD", route.group(1))
        self.assertIn("LAW ZERO", protocol.group(1))


if __name__ == "__main__":
    unittest.main()
