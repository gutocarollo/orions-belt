from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "templates/.harness/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from council_profile import choose_profile  # noqa: E402


class CouncilProfilePolicyTest(unittest.TestCase):
    def test_auto_begins_direct_without_material_floor(self):
        result = choose_profile()
        self.assertEqual("DIRECT", result["effective_profile"])
        self.assertEqual([], result["hard_full_signals"])

    def test_ai_can_choose_light_without_new_deterministic_bureaucracy(self):
        result = choose_profile(requested_profile="AUTO", ai_choice="LIGHT")
        self.assertEqual("LIGHT", result["effective_profile"])

    def test_material_high_assurance_signal_sets_only_narrow_full_floor(self):
        result = choose_profile(
            requested_profile="AUTO",
            ai_choice="DIRECT",
            signals={"production_or_deploy": True},
        )
        self.assertEqual("FULL", result["effective_profile"])
        self.assertEqual(["production_or_deploy"], result["hard_full_signals"])

    def test_medium_low_and_unreachable_findings_go_to_backlog(self):
        result = choose_profile(
            requested_profile="AUTO",
            ai_choice="DIRECT",
            findings=[
                {"id": "M1", "severity": "MEDIUM", "reachable_in_current_task": True},
                {"id": "H1", "severity": "HIGH", "reachable_in_current_task": False},
            ],
        )
        self.assertEqual("DIRECT", result["effective_profile"])
        self.assertEqual([], result["fix_now"])
        self.assertEqual(["M1", "H1"], [item["id"] for item in result["backlog"]])

    def test_reachable_high_is_fix_now_but_does_not_force_full(self):
        result = choose_profile(
            requested_profile="AUTO",
            ai_choice="LIGHT",
            findings=[{"id": "H1", "severity": "HIGH", "reachable_in_current_task": True}],
        )
        self.assertEqual("LIGHT", result["effective_profile"])
        self.assertEqual(["H1"], [item["id"] for item in result["fix_now"]])
        self.assertTrue(result["requires_profile_reassessment"])

    def test_policy_is_injected_after_the_legacy_council_body(self):
        selector = (ROOT / "templates/.harness/skills-shared/delivery-council/SKILL.md.jinja").read_text()
        self.assertIn("council-execution-profiles.", selector)
        self.assertGreater(
            selector.index("council-execution-profiles."),
            selector.index("delivery-council/SKILL."),
        )

    def test_prompt_renderer_exposes_auto_direct_light_full(self):
        source = (ROOT / "engine/contract/scripts/render_prompt.py").read_text()
        self.assertIn('EXECUTION_PROFILE = ("AUTO", "DIRECT", "LIGHT", "FULL")', source)
        self.assertIn('f"EXECUTION_PROFILE={args.execution_profile}"', source)


if __name__ == "__main__":
    unittest.main()
