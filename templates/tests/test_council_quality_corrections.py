from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "templates/.harness/lib"
RUNTIME_TESTS = LIB / "tests"
for path in (LIB, RUNTIME_TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from council_findings import partition_findings  # noqa: E402
from council_review_batch import consolidate_findings, normalize_review_batch  # noqa: E402
from council_runtime import apply_transition  # noqa: E402
from mini_schema_validate import validate_instance  # noqa: E402
from test_council_runtime import CouncilRuntimeTest  # noqa: E402


def canonical_impact(finding_id: str) -> dict:
    return {
        "id": finding_id,
        "evidence_status": "REAL",
        "evidence": {"path": "templates/tests/test_council_quality_corrections.py", "line": 20, "contains": "def canonical_impact"},
        "objective_impact": 3,
        "journey_reachability": 3,
        "acceptance_impact": 3,
        "irreversibility": 3,
        "dependency_urgency": 3,
        "on_critical_path": True,
        "affects_current_phase": True,
        "validated_workaround": False,
        "graph_nodes": ["request", "done"],
        "score": 75,
        "disposition": "HIGH_FIX_NOW",
    }


class CouncilQualityCorrectionsTest(unittest.TestCase):
    def test_canonical_high_fix_now_cannot_be_demoted_by_missing_lightweight_severity(self):
        fix_now, backlog = partition_findings([{"id": "H1", "impact": canonical_impact("H1")}])
        self.assertEqual(["H1"], [item["id"] for item in fix_now])
        self.assertEqual([], backlog)
        self.assertEqual("canonical-impact", fix_now[0]["classification_source"])
        self.assertEqual("HIGH_FIX_NOW", fix_now[0]["disposition"])

    def test_parallel_prisms_may_reuse_local_ids_without_losing_findings(self):
        result = consolidate_findings([
            {"id": "H1", "severity": "MEDIUM", "reachable_in_current_task": True, "prism": "simplicity-maintainability"},
            {"id": "H1", "severity": "CRITICAL", "reachable_in_current_task": True, "prism": "correctness-security-data"},
        ])
        self.assertEqual(2, len(result["fix_now"] + result["backlog"]))
        self.assertEqual("CRITICAL", result["fix_now"][0]["severity"])

    def test_review_batch_receipts_require_unique_prisms_and_reviewers(self):
        receipts = normalize_review_batch([
            {"prism": "correctness-security-data", "reviewer_id": "11111111-1111-4111-8111-111111111111", "status": "SATISFEITO", "evidence": "correctness.json"},
            {"prism": "tests-acceptance-regression", "reviewer_id": "22222222-2222-4222-8222-222222222222", "status": "SATISFEITO", "evidence": "tests.json"},
        ])
        self.assertEqual(2, len(receipts))

    def test_adversarial_schema_persists_batch_provenance(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        payload = {
            "status": "SATISFEITO",
            "reviewer_id": "33333333-3333-4333-8333-333333333333",
            "critical": 0,
            "required": 0,
            "review_batch": [
                {"prism": "correctness-security-data", "reviewer_id": "11111111-1111-4111-8111-111111111111", "status": "SATISFEITO", "evidence": "correctness.json"},
                {"prism": "tests-acceptance-regression", "reviewer_id": "22222222-2222-4222-8222-222222222222", "status": "SATISFEITO", "evidence": "tests.json"},
            ],
        }
        self.assertEqual([], validate_instance(payload, schema))

    def test_existing_adversarial_state_keeps_review_batch_without_new_state(self):
        state = CouncilRuntimeTest().walk_to_commit()
        payload = {
            "status": "SATISFEITO",
            "critical": 0,
            "required": 0,
            "reviewer_id": "33333333-3333-4333-8333-333333333333",
            "round": 1,
            "review_batch": [
                {"prism": "correctness-security-data", "reviewer_id": "11111111-1111-4111-8111-111111111111", "status": "SATISFEITO", "evidence": "correctness.json"},
                {"prism": "tests-acceptance-regression", "reviewer_id": "22222222-2222-4222-8222-222222222222", "status": "SATISFEITO", "evidence": "tests.json"},
            ],
        }
        state = apply_transition(state, "ADVERSARIAL", payload)
        self.assertEqual("ADVERSARIAL", state["stage"])
        self.assertEqual(payload["review_batch"], state["history"][-1]["payload"]["review_batch"])


if __name__ == "__main__":
    unittest.main()
