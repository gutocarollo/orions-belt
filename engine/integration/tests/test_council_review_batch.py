from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "templates/.harness/lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from council_review_batch import (  # noqa: E402
    ReviewBatchError,
    consolidate_findings,
    normalize_review_batch,
    plan_review_batch,
)


def receipt(
    prism: str,
    reviewer_id: str,
    *,
    status: str = "SATISFEITO",
    finding_uids: list[str] | None = None,
) -> dict:
    return {
        "prism": prism,
        "reviewer_id": reviewer_id,
        "status": status,
        "evidence": f"{prism}.json",
        "finding_uids": list(finding_uids or []),
    }


class CouncilReviewBatchTest(unittest.TestCase):
    def test_direct_auto_skips_execution_review(self):
        result = plan_review_batch(execution_profile="DIRECT")
        self.assertEqual("NONE", result["effective_mode"])
        self.assertEqual(0, result["max_reviewers"])

    def test_direct_explicit_single_is_respected(self):
        result = plan_review_batch(execution_profile="DIRECT", review_mode="SINGLE")
        self.assertEqual("SINGLE", result["effective_mode"])
        self.assertEqual(1, result["max_reviewers"])

    def test_light_auto_keeps_one_consolidated_review(self):
        result = plan_review_batch(execution_profile="LIGHT")
        self.assertEqual("SINGLE", result["effective_mode"])
        self.assertFalse(result["parallel"])

    def test_full_auto_prefers_parallel_prisms_over_legacy_serial_chain(self):
        result = plan_review_batch(execution_profile="FULL")
        self.assertEqual("BATCH", result["effective_mode"])
        self.assertTrue(result["parallel"])
        self.assertEqual(3, len(result["prisms"]))

    def test_light_batch_is_bounded_to_two_reviewers(self):
        result = plan_review_batch(execution_profile="LIGHT", review_mode="BATCH")
        self.assertEqual("BATCH", result["effective_mode"])
        self.assertLessEqual(result["max_reviewers"], 2)

    def test_explicit_full_preserves_legacy_two_reviewer_contract(self):
        result = plan_review_batch(execution_profile="FULL", review_mode="FULL")
        self.assertEqual("FULL", result["effective_mode"])
        self.assertFalse(result["parallel"])
        self.assertEqual(2, result["max_reviewers"])
        self.assertIsNone(result["requires_profile_escalation"])

    def test_full_review_requested_from_direct_requires_profile_escalation(self):
        result = plan_review_batch(execution_profile="DIRECT", review_mode="FULL")
        self.assertEqual("FULL", result["effective_mode"])
        self.assertEqual("FULL", result["requires_profile_escalation"])
        self.assertEqual(2, result["max_reviewers"])

    def test_only_reachable_high_or_critical_blocks(self):
        result = consolidate_findings([
            {"id": "H1", "severity": "HIGH", "reachable_in_current_task": True, "prism": "tests-acceptance-regression"},
            {"id": "M1", "severity": "MEDIUM", "reachable_in_current_task": True, "prism": "simplicity-maintainability"},
            {"id": "H2", "severity": "HIGH", "reachable_in_current_task": False, "prism": "correctness-security-data"},
        ])
        self.assertEqual(["H1"], [item["id"] for item in result["fix_now"]])
        self.assertEqual(["M1", "H2"], [item["id"] for item in result["backlog"]])

    def test_same_local_id_can_have_distinct_global_finding_uids(self):
        result = consolidate_findings(
            [
                {"finding_uid": "uid-a", "id": "H1", "severity": "HIGH", "reachable_in_current_task": True},
                {"finding_uid": "uid-b", "id": "H1", "severity": "HIGH", "reachable_in_current_task": True},
            ],
            [
                receipt("correctness-security-data", "11111111-1111-4111-8111-111111111111", status="CORRIGIR", finding_uids=["uid-a"]),
                receipt("tests-acceptance-regression", "22222222-2222-4222-8222-222222222222", status="CORRIGIR", finding_uids=["uid-b"]),
            ],
        )
        self.assertEqual(
            ["correctness-security-data", "tests-acceptance-regression"],
            result["targeted_recheck_prisms"],
        )

    def test_batch_receipts_require_finding_uids_even_when_empty(self):
        with self.assertRaisesRegex(ReviewBatchError, "finding_uids array"):
            normalize_review_batch([
                {
                    "prism": "correctness-security-data",
                    "reviewer_id": "11111111-1111-4111-8111-111111111111",
                    "status": "SATISFEITO",
                    "evidence": "one.json",
                },
                receipt("tests-acceptance-regression", "22222222-2222-4222-8222-222222222222"),
            ])


if __name__ == "__main__":
    unittest.main()
