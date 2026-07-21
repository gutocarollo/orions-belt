import copy
import json
import tempfile
import unittest
from pathlib import Path

from engine.evidence.generate_report import render_report
from engine.evidence.manifest import EvidenceValidationError, assert_valid_manifest, canonical_hash, validate_manifest


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class EvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_fixture_references_and_local_hash_are_valid(self) -> None:
        assert_valid_manifest(self.manifest, FIXTURE_DIR, verify_files=True)
        self.assertEqual(64, len(canonical_hash(self.manifest)))

    def test_missing_reference_and_failed_activity_block_pass_claim(self) -> None:
        broken = copy.deepcopy(self.manifest)
        broken["activities"][0]["exit_code"] = 1
        broken["claims"][0]["entities"].append("entity:missing")
        errors = validate_manifest(broken)
        self.assertTrue(any("unknown reference" in error for error in errors))
        self.assertTrue(any("references failed activity" in error for error in errors))

    def test_quarantined_entity_cannot_support_pass(self) -> None:
        broken = copy.deepcopy(self.manifest)
        broken["entities"][0]["trust"] = "quarantined"
        with self.assertRaisesRegex(EvidenceValidationError, "quarantined"):
            assert_valid_manifest(broken)

    def test_local_hash_mismatch_and_path_escape_are_rejected(self) -> None:
        broken = copy.deepcopy(self.manifest)
        broken["entities"][0]["sha256"] = "0" * 64
        self.assertTrue(any("hash mismatch" in error for error in validate_manifest(broken, FIXTURE_DIR, True)))
        broken["entities"][0]["uri"] = "../manifest.json"
        self.assertTrue(any("escapes manifest base" in error for error in validate_manifest(broken, FIXTURE_DIR, True)))

    def test_screenshot_requires_route_and_theme(self) -> None:
        broken = copy.deepcopy(self.manifest)
        broken["entities"][0]["type"] = "screenshot"
        errors = validate_manifest(broken)
        self.assertTrue(any("requires route and theme" in error for error in errors))

    def test_undeclared_fields_are_rejected(self) -> None:
        broken = copy.deepcopy(self.manifest)
        broken["claims"][0]["magic"] = True
        self.assertTrue(any("additional property" in error for error in validate_manifest(broken)))

    def test_html_report_escapes_content_and_unsafe_links(self) -> None:
        hostile = copy.deepcopy(self.manifest)
        hostile["title"] = "<script>alert(1)</script>"
        hostile["entities"][0]["uri"] = "javascript:alert(1)"
        page = render_report(hostile)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn('href="javascript:', page)
        self.assertIn("Canonical manifest digest", page)


if __name__ == "__main__":
    unittest.main()
