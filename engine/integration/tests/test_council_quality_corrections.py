from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
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

RUN_ID = "run-1"
IMPLEMENTER = "99999999-9999-4999-8999-999999999999"
SNAPSHOT = "a" * 40
REVIEWER_A = "11111111-1111-4111-8111-111111111111"
REVIEWER_B = "22222222-2222-4222-8222-222222222222"
CONSOLIDATOR = "33333333-3333-4333-8333-333333333333"


def canonical_impact(finding_id: str) -> dict:
    return {
        "id": finding_id,
        "evidence_status": "REAL",
        "evidence": {
            "path": "engine/integration/tests/test_council_quality_corrections.py",
            "line": 35,
            "contains": "def canonical_impact",
        },
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


def schema_payload(*, status: str = "SATISFEITO", findings: list[dict] | None = None, batch: list[dict] | None = None) -> dict:
    findings = list(findings or [])
    critical = sum(item.get("impact", {}).get("disposition") == "CRITICAL_BLOCK" for item in findings)
    required = sum(item.get("impact", {}).get("disposition") == "HIGH_FIX_NOW" for item in findings)
    return {
        "status": status,
        "reviewer_id": CONSOLIDATOR,
        "critical": critical,
        "required": required,
        "run_id": RUN_ID,
        "implementer_id": IMPLEMENTER,
        "snapshot_sha": SNAPSHOT,
        "findings": findings,
        "review_batch": list(batch or []),
    }


@contextmanager
def runtime_receipts(*, implementer_id: str = IMPLEMENTER, include_a: bool = True, include_b: bool = True, session_b: str = "session-1"):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / ".harness/runs/agent-swarm" / RUN_ID / "council-state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"run_id": RUN_ID, "implementer_id": implementer_id}), encoding="utf-8")
        (root / ".harness/council-active").write_text(str(state), encoding="utf-8")
        ledger = root / ".harness/runs/subagent-cost/session-1/events.jsonl"
        ledger.parent.mkdir(parents=True)
        rows = []
        if include_a:
            rows.append({
                "event": "SubagentStop",
                "run_id": RUN_ID,
                "session_id": "session-1",
                "agent_id": REVIEWER_A,
                "agent_id_source": "runtime",
                "snapshot_sha": SNAPSHOT,
            })
        if include_b:
            rows.append({
                "event": "SubagentStop",
                "run_id": RUN_ID,
                "session_id": session_b,
                "agent_id": REVIEWER_B,
                "agent_id_source": "runtime",
                "snapshot_sha": SNAPSHOT,
            })
        ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        previous = os.environ.get("HARNESS_PROJECT_ROOT")
        os.environ["HARNESS_PROJECT_ROOT"] = str(root)
        try:
            yield root
        finally:
            if previous is None:
                os.environ.pop("HARNESS_PROJECT_ROOT", None)
            else:
                os.environ["HARNESS_PROJECT_ROOT"] = previous


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

    def test_review_batch_receipts_require_unique_prisms_reviewers_and_finding_uids(self):
        receipts = normalize_review_batch([
            receipt("correctness-security-data", REVIEWER_A, finding_uids=["uid-H1"]),
            receipt("tests-acceptance-regression", REVIEWER_B),
        ])
        self.assertEqual(2, len(receipts))
        self.assertEqual(["uid-H1"], receipts[0]["finding_uids"])

    def test_adversarial_schema_persists_batch_provenance_and_real_lifecycle(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        payload = schema_payload(batch=[
            receipt("correctness-security-data", REVIEWER_A),
            receipt("tests-acceptance-regression", REVIEWER_B),
        ])
        with runtime_receipts():
            self.assertEqual([], validate_instance(payload, schema))

    def test_schema_rejects_satisfied_root_when_a_prism_requests_correction(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        high = {
            "finding_uid": "uid-H1",
            "gap": "required",
            "evidence": "test",
            "required_change": "fix",
            "impact": canonical_impact("H1"),
        }
        payload = schema_payload(status="SATISFEITO", findings=[high], batch=[
            receipt("correctness-security-data", REVIEWER_A, status="CORRIGIR", finding_uids=["uid-H1"]),
            receipt("tests-acceptance-regression", REVIEWER_B),
        ])
        with runtime_receipts():
            errors = validate_instance(payload, schema)
        self.assertTrue(any("cannot be SATISFEITO" in error for error in errors), errors)

    def test_schema_rejects_reviewer_that_is_the_council_implementer(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        payload = schema_payload(batch=[
            receipt("correctness-security-data", REVIEWER_A),
            receipt("tests-acceptance-regression", REVIEWER_B),
        ])
        payload["implementer_id"] = REVIEWER_A
        with runtime_receipts(implementer_id=REVIEWER_A):
            errors = validate_instance(payload, schema)
        self.assertTrue(any("cannot use the Council implementer" in error for error in errors), errors)

    def test_schema_rejects_fabricated_reviewer_without_runtime_receipt(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        payload = schema_payload(batch=[
            receipt("correctness-security-data", REVIEWER_A),
            receipt("tests-acceptance-regression", REVIEWER_B),
        ])
        with runtime_receipts(include_b=False):
            errors = validate_instance(payload, schema)
        self.assertTrue(any("no successful runtime lifecycle receipt" in error for error in errors), errors)

    def test_schema_rejects_reviewers_from_different_runtime_sessions(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        payload = schema_payload(batch=[
            receipt("correctness-security-data", REVIEWER_A),
            receipt("tests-acceptance-regression", REVIEWER_B),
        ])
        with runtime_receipts(session_b="session-2"):
            errors = validate_instance(payload, schema)
        self.assertTrue(any("same runtime session" in error for error in errors), errors)

    def test_duplicate_local_ids_remain_distinct_via_finding_uid(self):
        findings = [
            {"finding_uid": "uid-correctness", "id": "H1", "severity": "HIGH", "reachable_in_current_task": True},
            {"finding_uid": "uid-tests", "id": "H1", "severity": "HIGH", "reachable_in_current_task": True},
        ]
        result = consolidate_findings(
            findings,
            [
                receipt("correctness-security-data", REVIEWER_A, status="CORRIGIR", finding_uids=["uid-correctness"]),
                receipt("tests-acceptance-regression", REVIEWER_B, status="CORRIGIR", finding_uids=["uid-tests"]),
            ],
        )
        self.assertEqual(
            ["correctness-security-data", "tests-acceptance-regression"],
            result["targeted_recheck_prisms"],
        )

    def test_schema_rejects_duplicate_global_finding_uid(self):
        schema = json.loads((ROOT / "templates/.harness/schemas/adversarial-review-result.schema.json").read_text())
        findings = [
            {"finding_uid": "same", "gap": "one", "evidence": "e1", "required_change": "f1", "impact": canonical_impact("H1")},
            {"finding_uid": "same", "gap": "two", "evidence": "e2", "required_change": "f2", "impact": canonical_impact("H1")},
        ]
        payload = schema_payload(status="CORRIGIR", findings=findings, batch=[
            receipt("correctness-security-data", REVIEWER_A, status="CORRIGIR", finding_uids=["same"]),
            receipt("tests-acceptance-regression", REVIEWER_B),
        ])
        with runtime_receipts():
            errors = validate_instance(payload, schema)
        self.assertTrue(any("globally unique" in error for error in errors), errors)

    def test_cost_ledger_persists_snapshot_for_runtime_identity_binding(self):
        spec = importlib.util.spec_from_file_location(
            "subagent_cost_ledger_test",
            ROOT / "templates/.harness/hooks/subagent-cost-ledger.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = module.record_event(
                {
                    "hook_event_name": "SubagentStop",
                    "run_id": RUN_ID,
                    "session_id": "session-1",
                    "agent_id": REVIEWER_A,
                    "agent_type": "reviewer",
                    "model": "test-model",
                    "snapshot_sha": SNAPSHOT,
                },
                "codex",
                root,
            )
            self.assertIsNotNone(path)
            row = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(SNAPSHOT, row["snapshot_sha"])
            self.assertEqual("runtime", row["agent_id_source"])

    def test_runtime_authoritative_path_consumes_cross_field_schema_validation(self):
        state = CouncilRuntimeTest().walk_to_commit()
        payload = {
            "status": "SATISFEITO",
            "critical": 0,
            "required": 0,
            "reviewer_id": CONSOLIDATOR,
            "round": 1,
            "run_id": RUN_ID,
            "implementer_id": IMPLEMENTER,
            "snapshot_sha": SNAPSHOT,
            "review_batch": [
                receipt("correctness-security-data", REVIEWER_A, status="CORRIGIR", finding_uids=["missing"]),
                receipt("tests-acceptance-regression", REVIEWER_B),
            ],
        }
        with runtime_receipts():
            with self.assertRaisesRegex(TransitionError, "review prism|unknown findings|SATISFEITO"):
                apply_transition(state, "ADVERSARIAL", payload)


if __name__ == "__main__":
    unittest.main()
