"""Contract tests for the relaxed Gauntlet orchestration profile.

These tests deliberately inspect the template sources.  Render-level parity is
already covered by the repository's Copier E2E suites; this file protects the
small policy surface that selects one orchestrator without changing the
existing deterministic hooks, wiki, request anchor, or marathon runtime.
"""

from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
COPIER = ROOT / "copier.yml"
SHARED = TEMPLATES / ".harness/skills-shared/gauntlet-loop"
CLAUDE = (
    TEMPLATES
    / "{% if use_claude %}.claude{% endif %}"
    / "skills"
    / "{% if use_gauntlet_loop %}gauntlet-loop{% endif %}"
    / "SKILL.md.jinja"
)
CODEX = (
    TEMPLATES
    / ".agents/skills"
    / "{% if use_codex and use_gauntlet_loop %}gauntlet-loop{% endif %}"
    / "SKILL.md.jinja"
)
CLAUDE_COUNCIL = (
    TEMPLATES
    / "{% if use_claude %}.claude{% endif %}"
    / "skills"
    / "{% if use_delivery_council %}{{ project_name }}-delivery-council{% endif %}"
    / "SKILL.md.jinja"
)
CODEX_COUNCIL = (
    TEMPLATES
    / ".agents/skills"
    / "{% if use_codex and use_delivery_council %}{{ project_name }}-delivery-council{% endif %}"
    / "SKILL.md.jinja"
)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def yaml_question(config: str, name: str) -> str:
    """Return one top-level Copier question without a backtracking regex."""
    start = config.index(f"{name}:\n")
    remainder = config[start:]
    match = re.search(r"(?m)^[a-zA-Z_][a-zA-Z0-9_]*:\n", remainder[len(name) + 2 :])
    if match is None:
        return remainder
    return remainder[: len(name) + 2 + match.start()]


class GauntletProfileContractTest(unittest.TestCase):
    def test_relaxed_profile_is_default_and_council_is_opt_in(self) -> None:
        config = read(COPIER)
        self.assertIn("    default: true", yaml_question(config, "use_gauntlet_loop"))
        self.assertIn("    default: false", yaml_question(config, "use_delivery_council"))
        self.assertIn("use_delivery_council and use_gauntlet_loop", config)

        required = yaml_question(config, "harness_required_skills")
        self.assertIn("gauntlet-loop", required)
        self.assertIn("use_delivery_council", required)

        council_name = yaml_question(config, "harness_council_skill_name")
        self.assertIn("use_delivery_council", council_name)
        self.assertTrue(CLAUDE_COUNCIL.is_file())
        self.assertTrue(CODEX_COUNCIL.is_file())

    def test_shared_skill_and_runtime_wrappers_use_one_source(self) -> None:
        for path in (
            SHARED / "SKILL.md.jinja",
            SHARED / "SKILL.en.md.jinja",
            SHARED / "SKILL.pt.md.jinja",
            CLAUDE,
            CODEX,
        ):
            self.assertTrue(path.is_file(), path)

        selector = read(SHARED / "SKILL.md.jinja")
        self.assertIn('SKILL." ~ harness_language ~ ".md.jinja"', selector)
        include = "templates/.harness/skills-shared/gauntlet-loop/SKILL.md.jinja"
        self.assertIn(include, read(CLAUDE))
        self.assertIn(include, read(CODEX))

    def test_three_cycles_have_explicit_artifacts_and_one_plan_review(self) -> None:
        for language in ("en", "pt"):
            skill = read(SHARED / f"SKILL.{language}.md.jinja")
            with self.subTest(language=language):
                for token in (
                    "METAPROMPT.md",
                    "planning-and-task-breakdown",
                    "PLAN.md",
                    "PLAN-REVIEW.md",
                    "APPROVAL.sha256",
                    "exactly one independent plan review",
                ):
                    self.assertIn(token, skill)

                self.assertLess(skill.index("METAPROMPT.md"), skill.index("PLAN.md"))
                self.assertLess(skill.index("PLAN.md"), skill.index("APPROVAL.sha256"))

    def test_execution_is_adaptive_not_a_fixed_council_loop(self) -> None:
        blocking = {"BLOCKING", "CRITICAL", "HIGH", "REQUIRED"}
        nonblocking = {"MEDIUM", "LOW", "OPTIONAL", "NIT", "FYI"}

        for language in ("en", "pt"):
            skill = read(SHARED / f"SKILL.{language}.md.jinja")
            with self.subTest(language=language):
                self.assertIn("deterministic verification", skill)
                self.assertIn("conditional critic", skill)
                self.assertIn("BACKLOG.md", skill)
                self.assertIn("same critic", skill)
                self.assertIn("no fixed round count", skill)
                self.assertIn("never invoke", skill)
                self.assertIn("delivery-council", skill)
                for severity in blocking | nonblocking:
                    self.assertIn(severity, skill)

                self.assertNotRegex(skill, r"(?i)(?:maximum|maximo|maximo de|max)\s+[123]\s+round")

    def test_existing_durable_capabilities_are_preserved(self) -> None:
        for language in ("en", "pt"):
            skill = read(SHARED / f"SKILL.{language}.md.jinja")
            with self.subTest(language=language):
                for capability in (
                    "request anchor",
                    "repo-wiki-curator",
                    "marathon",
                    "prova-de-conclusao",
                ):
                    self.assertIn(capability, skill)

    def test_framework_only_files_are_excluded_from_consumer_render(self) -> None:
        config = read(COPIER)
        self.assertIn('"/.harness/skills-shared/gauntlet-loop/SKILL.md"', config)
        self.assertIn('"/tests/test_gauntlet_profile.py"', config)


if __name__ == "__main__":
    unittest.main()
