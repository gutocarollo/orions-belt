from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "templates/.harness/lib"
RUNTIME_TESTS = LIB / "tests"
for path in (LIB, RUNTIME_TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from council_findings import partition_findings  # noqa: E402
from council_review_batch import consolidate_findings, normalize_review_batch  # noqa: E402
from council_runtime import TransitionError, apply_transition  # noqa: E402
from mini_schema_validate import validate_instance  # noqa: E402
from test_council_runtime import CouncilRuntimeTest  # noqa: E402


def canonical_impact(finding_id: str) -> dict:
    return {
        "id": finding_id,
        "evidence_status": "REAL",
        "evidence": {"path": "engine/integration/tests/test_council_quality_corrections.py", "line": 22, "contains": "def canonical_impact"},
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


def receipt(prism: str, reviewer_id: str, *, status: str = "SATISFEITO", finding_ids: list[str] | None = None) -> dict:
    return {
        "prism": prism,
        "reviewer_id": reviewer_id,
        "status": status,
        "evidence": f"{prism}.json",
        "finding_ids": list(finding_ids or []),
    }


def schema_payload(*, status: str = "SATISFEITO", findings: list[dict] | None = None, batch: list[dict] | None = None) -> dict:
    findings = list(findings or [])
    critical = sum(item.get("impact", {}).get("disposition") == "CRITICAL_BLOCK" for item in findings)
    required = sum(item.get("impact", {}).get("disposition") == "HIGH_FIX_NOW" for item in findings)
    return {
        "status": status,
        "reviewer_id": "33333333-3333-4333-8333-333333333333",
        "critical": critical,
        "required": required,
        "findings": findings,
        "review_batch": list(batch or []),
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

    def test_review_batch_receipts_require_unique_prisms_reviewers_and_finding_ids(self):
        receipts = normalize_review_batch([
            receipt("correctness-security-data", "11111111-1111-4111-8111-111111111111", finding_ids=["H1"]),
            receipt("tests-acceptance-regression", "22222222-2222-4222-8222-222222222222"),
        ])
        self.assertEqual(2, len(receipts))
        self.assertEqual(["H1"], receipts[0]["finding_ids"])

    def test_adversarial_schema_persists_batch_provenance(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        payload = schema_payload(batch=[
            receipt("correctness-security-data", "11111111-1111-4111-8111-111111111111"),
            receipt("tests-acceptance-regression", "22222222-2222-4222-8222-222222222222"),
        ])
        self.assertEqual([], validate_instance(payload, schema))

    def test_schema_rejects_satisfied_root_when_a_prism_requests_correction(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        high = {"gap": "required", "evidence": "test", "required_change": "fix", "impact": canonical_impact("H1")}
        payload = schema_payload(status="SATISFEITO", findings=[high], batch=[
            receipt("correctness-security-data", "11111111-1111-4111-8111-111111111111", status="CORRIGIR", finding_ids=["H1"]),
            receipt("tests-acceptance-regression", "22222222-2222-4222-8222-222222222222"),
        ])
        errors = validate_instance(payload, schema)
        self.assertTrue(any("cannot be SATISFEITO" in error for error in errors), errors)

    def test_schema_rejects_duplicate_prism_or_reviewer_even_if_json_shape_is_valid(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        duplicate = receipt("correctness-security-data", "11111111-1111-4111-8111-111111111111")
        payload = schema_payload(batch=[duplicate, dict(duplicate)])
        errors = validate_instance(payload, schema)
        self.assertTrue(any("unique prisms" in error for error in errors), errors)

    def test_schema_requires_every_blocking_finding_to_be_attributed_to_a_prism(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        high = {"gap": "required", "evidence": "test", "required_change": "fix", "impact": canonical_impact("H1")}
        payload = schema_payload(status="CORRIGIR", findings=[high], batch=[
            receipt("correctness-security-data", "11111111-1111-4111-8111-111111111111"),
            receipt("tests-acceptance-regression", "22222222-2222-4222-8222-222222222222"),
        ])
        errors = validate_instance(payload, schema)
        self.assertTrue(any("every blocking finding" in error for error in errors), errors)

    def test_runtime_authoritative_path_consumes_cross_field_schema_validation(self):
        state = CouncilRuntimeTest().walk_to_commit()
        payload = {
            "status": "SATISFEITO",
            "critical": 0,
            "required": 0,
            "reviewer_id": "33333333-3333-4333-8333-333333333333",
            "round": 1,
            "review_batch": [
                receipt("correctness-security-data", "11111111-1111-4111-8111-111111111111", status="CORRIGIR", finding_ids=["H1"]),
                receipt("tests-acceptance-regression", "22222222-2222-4222-8222-222222222222"),
            ],
        }
        with self.assertRaisesRegex(TransitionError, "review prism|unknown findings|SATISFEITO"):
            apply_transition(state, "ADVERSARIAL", payload)


if __name__ == "__main__":
    unittest.main()
