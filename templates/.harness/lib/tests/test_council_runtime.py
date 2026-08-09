import sys
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

from council_runtime import (  # noqa: E402
    TransitionError,
    apply_transition,
    evaluate_quality,
    remote_action_allowed,
)


def validation(files, command="test"):
    return {"status": "PASS", "commands": [{"command": command, "exit_code": 0}], "checked_files": files, "executor": "agent_swarm_ledger", "validated_at": "2026-01-01T00:00:00Z", "file_hashes": [{"path": name, "sha256": "0" * 64} for name in files]}


class CouncilRuntimeTest(unittest.TestCase):
    def walk_to_commit(self):
        state = None
        events = [
            ("ANCHOR", {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "inline"}),
            ("PHASE-PLAN", {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "items": ["i1"]}),
            ("ITEM-PLAN", {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "item": "i1", "slice": "s1", "validation": ["test"]}),
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
            ("SIMPLIFICATION", {"status": "NAO_NECESSARIA"}),
            ("ADVERSARIAL", {"status": "SATISFEITO", "reviewer_id": "22222222-2222-4222-8222-222222222222"}),
            ("DELIVERY", {"status": "SATISFEITO", "manifest": "delivery.json"}),
        ]:
            state = apply_transition(state, kind, payload)
        self.assertEqual("DELIVERY", state["stage"])

    def test_edit_without_ready_item_is_rejected(self):
        state = apply_transition(None, "ANCHOR", {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "inline"})
        with self.assertRaisesRegex(TransitionError, "PHASE-PLAN"):
            apply_transition(state, "SLICE", {"skill": "incremental-implementation"})

    def test_next_slice_without_validation_is_rejected(self):
        state = None
        for kind, payload in [
            ("ANCHOR", {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "inline"}),
            ("PHASE-PLAN", {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "items": ["i1"]}),
            ("ITEM-PLAN", {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "item": "i1", "slice": "s1", "validation": ["test"]}),
            ("SLICE", {"skill": "incremental-implementation", "slice": "s1", "changed_files": ["slice.txt"]}),
        ]:
            state = apply_transition(state, kind, payload)
        with self.assertRaisesRegex(TransitionError, "VALIDATION"):
            apply_transition(state, "SLICE", {"skill": "incremental-implementation"})

    def test_quality_before_local_commit_is_rejected(self):
        state = None
        for kind, payload in [
            ("ANCHOR", {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "inline"}),
            ("PHASE-PLAN", {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "items": ["i1"]}),
            ("ITEM-PLAN", {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "item": "i1", "slice": "s1", "validation": ["test"]}),
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
        state = apply_transition(state, "QUALITY", {"status": "CORRIGIR", "critical": 0, "required": 1, "reviewer_id": "33333333-3333-4333-8333-333333333333", "round": 1, "findings": [{"gap": "required", "evidence": "test", "required_change": "fix"}]})
        with self.assertRaisesRegex(TransitionError, "ITEM-PLAN"):
            apply_transition(state, "SIMPLIFICATION", {"status": "NAO_NECESSARIA"})

    def test_adversarial_corrigir_cannot_advance_to_delivery(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "33333333-3333-4333-8333-333333333333", "round": 1})
        state = apply_transition(state, "SIMPLIFICATION", {"status": "NAO_NECESSARIA"})
        state = apply_transition(state, "ADVERSARIAL", {"status": "CORRIGIR", "reviewer_id": "44444444-4444-4444-8444-444444444444", "round": 1, "findings": [{"gap": "high", "evidence": "test", "required_change": "fix"}]})
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

    def test_review_round_cannot_repeat_after_fix(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "QUALITY", {"status": "CORRIGIR", "critical": 0, "required": 1, "reviewer_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "round": 1, "findings": [{"gap": "x", "evidence": "test", "required_change": "fix"}]})
        state = apply_transition(state, "ITEM-PLAN", {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "fix", "item": "fix", "slice": "fix", "validation": ["test"], "fix_kind": "quality", "consumes_review_round": 1})
        state = apply_transition(state, "SLICE", {"skill": "incremental-implementation", "slice": "fix", "changed_files": ["fix.txt"]})
        state = apply_transition(state, "VALIDATION", validation(["fix.txt"]))
        state = apply_transition(state, "LOCAL-COMMIT", {"sha": "b" * 40, "files": ["fix.txt"]})
        with self.assertRaisesRegex(TransitionError, "increment"):
            apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "round": 1})

    def test_delivery_before_adversarial_is_rejected(self):
        state = self.walk_to_commit()
        state = apply_transition(state, "QUALITY", {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"})
        state = apply_transition(state, "SIMPLIFICATION", {"status": "NAO_NECESSARIA"})
        with self.assertRaisesRegex(TransitionError, "ADVERSARIAL"):
            apply_transition(state, "DELIVERY", {"status": "SATISFEITO"})

    def test_read_only_anchor_cannot_enter_execution(self):
        state = apply_transition(None, "ANCHOR", {"mutation_mode": "READ_ONLY", "anchor_source": "inline"})
        with self.assertRaisesRegex(TransitionError, "read-only"):
            apply_transition(state, "PHASE-PLAN", {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "items": ["i1"]})

    def test_read_only_can_deliver_without_workspace_mutation(self):
        state = apply_transition(None, "ANCHOR", {"mutation_mode": "READ_ONLY", "anchor_source": "inline"})
        state = apply_transition(state, "DELIVERY", {"status": "SATISFEITO", "manifest": "inline-read-only-report"})
        self.assertEqual("DELIVERY", state["stage"])

    def test_remote_push_and_merge_require_explicit_authority(self):
        self.assertFalse(remote_action_allowed("push", {}))
        self.assertFalse(remote_action_allowed("merge-main", {"remote_authorized": False}))
        self.assertTrue(remote_action_allowed("push", {"remote_authorized": True, "authorized_by": "user", "authorization_evidence": "prompt-42"}))
        self.assertTrue(remote_action_allowed("local-commit", {}))


if __name__ == "__main__":
    unittest.main()
