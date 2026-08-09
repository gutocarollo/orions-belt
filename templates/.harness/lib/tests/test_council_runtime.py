import sys
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
ROOT = LIB.parents[1]
sys.path.insert(0, str(LIB))

from council_runtime import (  # noqa: E402
    TransitionError,
    apply_transition,
    evaluate_quality,
    remote_action_allowed,
)


TESTS = {"functional": ["F1"], "quality": ["Q1"], "regression": ["R1"]}
GRAPH = {"objective": "deliver", "start_node": "request", "goal_node": "done", "nodes": ["request", "done", "later"], "edges": [{"edge_id": "E1", "from": "request", "to": "done", "critical": True, "phase": "p1", "item": "i1", "tests": TESTS, "evidence": ["proof.txt"]}]}
ANCHOR = {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "inline", "base_sha": "0" * 40, "worktree_baseline": [], "execution_graph": GRAPH}


def phase(name="p1"):
    return {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": name, "items": ["i1"], "objective": "deliver", "edge_id": "E1", "entry_node": "request", "exit_node": "done", "tests": TESTS}


def item(phase_name="p1", item_name="i1", **extra):
    return {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": phase_name, "item": item_name, "slice": item_name, "validation": ["test"], "objective": "deliver", "edge_id": "E1", "deliverable": "working result", "tests": TESTS, **extra}


def validation(files, command="test"):
    return {"status": "PASS", "commands": [{"command": command, "exit_code": 0, "test_ids": ["F1", "Q1", "R1"]}], "checked_files": files, "executor": "agent_swarm_ledger", "validated_at": "2026-01-01T00:00:00Z", "file_hashes": [{"path": name, "sha256": "0" * 64} for name in files], "tests": TESTS}


def impact(finding_id, disposition="HIGH_FIX_NOW"):
    rating = 4 if disposition == "CRITICAL_BLOCK" else 3
    return {"id": finding_id, "evidence_status": "REAL", "evidence": {"path": ".harness/lib/tests/test_council_runtime.py", "line": 34, "contains": "def impact"}, "objective_impact": rating, "journey_reachability": rating, "acceptance_impact": rating, "irreversibility": rating, "dependency_urgency": rating, "on_critical_path": True, "affects_current_phase": True, "validated_workaround": False, "graph_nodes": ["request", "done"], "score": rating * 25, "disposition": disposition}


def finding(finding_id="R1", disposition="HIGH_FIX_NOW"):
    return {"gap": "required", "evidence": "test", "required_change": "fix", "impact": impact(finding_id, disposition)}


class CouncilRuntimeTest(unittest.TestCase):
    def test_phase_plan_is_rejected_before_slice_when_not_in_anchored_graph(self):
        state = apply_transition(None, "ANCHOR", ANCHOR)
        forged = phase()
        forged.update({"entry_node": "invented-start", "exit_node": "invented-end"})
        with self.assertRaisesRegex(TransitionError, "anchored execution graph"):
            apply_transition(state, "PHASE-PLAN", forged)

    def test_real_finding_locator_is_resolved_before_pending_fix(self):
        state = self.walk_to_commit()
        forged = finding("FORGED", "CRITICAL_BLOCK")
        forged["impact"]["evidence"] = {"path": "missing-proof.txt", "line": 1, "contains": "fabricated"}
        with self.assertRaisesRegex(TransitionError, "impact evidence"):
            apply_transition(state, "QUALITY", {
                "status": "CORRIGIR", "critical": 1, "required": 0,
                "reviewer_id": "33333333-3333-4333-8333-333333333333", "round": 1,
                "findings": [forged],
            }, repository_root=ROOT)

    def walk_to_commit(self):
        state = None
        events = [
            ("ANCHOR", ANCHOR),
            ("PHASE-PLAN", phase()),
            ("ITEM-PLAN", item()),
            ("SLICE", {"skill": "incremental-implementation", "slice": "s1", "changed_files": ["slice.txt"]}),
            ("VALIDATION", validation(["slice.txt"], "python -m unittest")),
            ("LOCAL-COMMIT", {"sha": "a" * 40, "files": ["slice.txt"]}),
        ]
        for kind, payload in events:
            state = apply_transition(state, kind, payload)
        return state

    def test_happy_path_reaches_delivery(self):
        state = self.walk_to_commit()
        for kind, payload in [
            ("QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "11111111-1111-4111-8111-111111111111"}),
            ("SIMPLIFICATION", {"status": "NAO_NECESSARIA", "reason": "already minimal"}),
            ("ADVERSARIAL", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "22222222-2222-4222-8222-222222222222"}),
            ("DELIVERY", {"status": "SATISFEITO", "manifest": "delivery.json"}),
        ]:
            state = apply_transition(state, kind, payload)
        self.assertEqual("DELIVERY", state["stage"])

    def test_edit_without_ready_item_is_rejected(self):
        state = apply_transition(None, "ANCHOR", ANCHOR)
        with self.assertRaisesRegex(TransitionError, "PHASE-PLAN"):
            apply_transition(state, "SLICE", {"skill": "incremental-implementation"})

    def test_next_slice_without_validation_is_rejected(self):
        state = None
        for kind, payload in [
            ("ANCHOR", ANCHOR),
            ("PHASE-PLAN", phase()),
            ("ITEM-PLAN", item()),
            ("SLICE", {"skill": "incremental-implementation", "slice": "s1", "changed_files": ["slice.txt"]}),
        ]:
            state = apply_transition(state, kind, payload)
        with self.assertRaisesRegex(TransitionError, "VALIDATION"):
            apply_transition(state, "SLICE", {"skill": "incremental-implementation"})

    def test_quality_before_local_commit_is_rejected(self):
        state = None
        for kind, payload in [
            ("ANCHOR", ANCHOR),
            ("PHASE-PLAN", phase()),
            ("ITEM-PLAN", item()),
            ("SLICE", {"skill": "incremental-implementation", "slice": "s1", "changed_files": ["slice.txt"]}),
            ("VALIDATION", validation(["slice.txt"])),
        ]:
            state = apply_transition(state, kind, payload)
        with self.assertRaisesRegex(TransitionError, "LOCAL-COMMIT"):
            apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0})

    def test_quality_required_finding_blocks(self):
        self.assertEqual("CORRIGIR", evaluate_quality({"Critical": 0, "Required": 1, "Optional": 3}))
        self.assertEqual("SATISFEITO", evaluate_quality({"Critical": 0, "Required": 0, "Nit": 2}))

    def test_quality_corrigir_cannot_advance_to_simplification(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "QUALITY", {"status": "CORRIGIR", "critical": 0, "required": 1, "reviewer_id": "33333333-3333-4333-8333-333333333333", "round": 1, "findings": [finding()]}, repository_root=ROOT)
        with self.assertRaisesRegex(TransitionError, "ITEM-PLAN"):
            apply_transition(state, "SIMPLIFICATION", {"status": "NAO_NECESSARIA", "reason": "already minimal"})

    def test_adversarial_corrigir_cannot_advance_to_delivery(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "33333333-3333-4333-8333-333333333333", "round": 1})
        state = apply_transition(state, "SIMPLIFICATION", {"status": "NAO_NECESSARIA", "reason": "already minimal"})
        state = apply_transition(state, "ADVERSARIAL", {"status": "CORRIGIR", "critical": 0, "required": 1, "reviewer_id": "44444444-4444-4444-8444-444444444444", "round": 1, "findings": [finding()]}, repository_root=ROOT)
        with self.assertRaisesRegex(TransitionError, "ITEM-PLAN"):
            apply_transition(state, "DELIVERY", {"status": "SATISFEITO", "manifest": "delivery.json"})

    def test_review_round_counts_and_identity_are_enforced(self):
        state = self.walk_to_commit()
        state["implementer_id"] = "builder"
        with self.assertRaisesRegex(TransitionError, "independent"):
            apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "builder", "round": 1})
        with self.assertRaisesRegex(TransitionError, "round"):
            apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "round": 4})
        with self.assertRaisesRegex(TransitionError, "minimum|non-negative"):
            apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": -1, "required": 0, "reviewer_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "round": 1})

    def test_simplification_changes_reenter_plan_validation_and_commit_loop(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "round": 1})
        state = apply_transition(state, "SIMPLIFICATION", {"status": "APLICAR", "reason": "remove duplicate branch"})
        with self.assertRaisesRegex(TransitionError, "ITEM-PLAN"):
            apply_transition(state, "ADVERSARIAL", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "round": 1})
        state = apply_transition(state, "ITEM-PLAN", item("p1", "simplify", fix_kind="simplification", consumes_review_round=1))
        self.assertIsNone(state["pending_fix"])

    def test_local_commit_sha_must_be_new_for_every_slice(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "ITEM-PLAN", item("p1", "second"))
        state = apply_transition(state, "SLICE", {"skill": "incremental-implementation", "slice": "second", "changed_files": ["slice.txt"]})
        state = apply_transition(state, "VALIDATION", validation(["slice.txt"]))
        with self.assertRaisesRegex(TransitionError, "new SHA"):
            apply_transition(state, "LOCAL-COMMIT", {"sha": "a" * 40, "files": ["slice.txt"]})

    def test_quality_and_adversarial_reviewers_must_be_distinct(self):
        state = self.walk_to_commit()
        reviewer = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        state = apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": reviewer, "round": 1})
        state = apply_transition(state, "SIMPLIFICATION", {"status": "NAO_NECESSARIA", "reason": "already minimal"})
        with self.assertRaisesRegex(TransitionError, "distinct"):
            apply_transition(state, "ADVERSARIAL", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": reviewer, "round": 1})

    def test_review_round_cannot_repeat_after_fix(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "QUALITY", {"status": "CORRIGIR", "critical": 0, "required": 1, "reviewer_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "round": 1, "findings": [finding()]}, repository_root=ROOT)
        state = apply_transition(state, "ITEM-PLAN", item("p1", "fix", fix_kind="quality", consumes_review_round=1))
        state = apply_transition(state, "SLICE", {"skill": "incremental-implementation", "slice": "fix", "changed_files": ["fix.txt"]})
        state = apply_transition(state, "VALIDATION", validation(["fix.txt"]))
        state = apply_transition(state, "LOCAL-COMMIT", {"sha": "b" * 40, "files": ["fix.txt"]})
        with self.assertRaisesRegex(TransitionError, "increment"):
            apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "round": 1})

    def test_delivery_before_adversarial_is_rejected(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"})
        state = apply_transition(state, "SIMPLIFICATION", {"status": "NAO_NECESSARIA", "reason": "already minimal"})
        with self.assertRaisesRegex(TransitionError, "ADVERSARIAL"):
            apply_transition(state, "DELIVERY", {"status": "SATISFEITO"})

    def test_read_only_anchor_cannot_enter_execution(self):
        state = apply_transition(None, "ANCHOR", {"mutation_mode": "READ_ONLY", "anchor_source": "inline"})
        with self.assertRaisesRegex(TransitionError, "read-only"):
            apply_transition(state, "PHASE-PLAN", phase())

    def test_read_only_can_deliver_without_workspace_mutation(self):
        state = apply_transition(None, "ANCHOR", {"mutation_mode": "READ_ONLY", "anchor_source": "inline"})
        state = apply_transition(state, "DELIVERY", {"status": "SATISFEITO", "manifest": "inline-read-only-report"})
        self.assertEqual("DELIVERY", state["stage"])

    def test_remote_push_and_merge_require_explicit_authority(self):
        self.assertFalse(remote_action_allowed("push", {}))
        self.assertFalse(remote_action_allowed("merge-main", {"remote_authorized": False}))
        self.assertTrue(remote_action_allowed("push", {"remote_authorized": True, "authorized_by": "user", "authorization_evidence": "prompt-42"}))
        self.assertTrue(remote_action_allowed("local-commit", {}))

    def test_reviews_are_bound_to_impact_and_nonblocking_work_continues(self):
        state = self.walk_to_commit()
        with self.assertRaisesRegex(TransitionError, "counts disagree"):
            apply_transition(state, "QUALITY", {"status": "CORRIGIR", "critical": 1, "required": 0, "reviewer_id": "33333333-3333-4333-8333-333333333333", "round": 1, "findings": [finding()]}, repository_root=ROOT)
        deferred = finding("D1")
        deferred["impact"] = {**impact("D1"), "evidence_status": "UNVERIFIED", "disposition": "DEFER_RUN"}
        deferred["impact"]["graph_nodes"] = ["later"]
        deferred["impact"]["on_critical_path"] = False
        deferred["impact"]["affects_current_phase"] = False
        deferred.update({"reason": "outside the current path", "review_after": "phase two"})
        state = apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "33333333-3333-4333-8333-333333333333", "round": 1, "deferred_findings": [deferred]})
        self.assertEqual("D1", state["deferred_findings"][0]["impact"]["id"])

    def test_blocking_impact_cannot_self_assign_unknown_graph_nodes(self):
        state = self.walk_to_commit()
        forged = finding("GHOST", "CRITICAL_BLOCK")
        forged["impact"]["graph_nodes"] = ["request", "ghost"]
        with self.assertRaisesRegex(TransitionError, "anchored execution graph"):
            apply_transition(state, "QUALITY", {
                "status": "CORRIGIR",
                "critical": 1,
                "required": 0,
                "reviewer_id": "33333333-3333-4333-8333-333333333333",
                "round": 1,
                "findings": [forged],
            }, repository_root=ROOT)

    def test_validation_ids_must_equal_the_planned_graph_edge(self):
        state = apply_transition(None, "ANCHOR", ANCHOR)
        state = apply_transition(state, "PHASE-PLAN", phase())
        state = apply_transition(state, "ITEM-PLAN", item())
        state = apply_transition(state, "SLICE", {"skill": "incremental-implementation", "slice": "i1", "changed_files": ["slice.txt"]})
        evidence = validation(["slice.txt"])
        evidence["commands"][0]["test_ids"][0] = "wrong"
        with self.assertRaisesRegex(TransitionError, "test ID"):
            apply_transition(state, "VALIDATION", evidence)

    def test_workspace_anchor_requires_initial_repository_evidence(self):
        with self.assertRaisesRegex(TransitionError, "base_sha"):
            apply_transition(None, "ANCHOR", {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "inline"})


if __name__ == "__main__":
    unittest.main()
