import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
ROOT = LIB.parents[1]
sys.path.insert(0, str(LIB))

from context_evidence import ContextEvidenceError, verify_context_delivery  # noqa: E402
from context_routing import RoutingError, route_context, validate_route  # noqa: E402
from council_runtime import TransitionError, apply_transition  # noqa: E402

TESTS = {"functional": ["F1"], "quality": ["Q1"], "regression": ["R1"]}
GRAPH = {
    "objective": "deliver",
    "start_node": "request",
    "goal_node": "done",
    "nodes": ["request", "done"],
    "edges": [{
        "edge_id": "E1", "from": "request", "to": "done", "critical": True,
        "phase": "p1", "item": "i1", "tests": TESTS, "evidence": ["proof.txt"],
    }],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase():
    return {
        "skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1",
        "items": ["i1"], "objective": "deliver", "edge_id": "E1",
        "entry_node": "request", "exit_node": "done", "tests": TESTS,
    }


def evidence_fixture(root: Path, plan: dict, *, fresh=True, complete=True):
    lifecycle = root / ".harness/runs/subagents/session/agent-1.jsonl"
    lifecycle.parent.mkdir(parents=True)
    records = [
        {"event": "SubagentStart", "runtime": "claude", "agent_id": "agent-1", "agent_type": "sample-context-scout", "configured_model": "sonnet"},
        {"event": "AgentToolResult", "runtime": "claude", "agent_id": "agent-1", "agent_type": "sample-context-scout", "configured_model": "sonnet", "model": "sonnet"},
        {"event": "SubagentStop", "runtime": "claude", "agent_id": "agent-1", "agent_type": "sample-context-scout", "configured_model": "sonnet"},
    ]
    lifecycle.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
    artifacts = []
    for item in plan["method_stages"]:
        path = root / ".harness/runs/context" / f"{item['method']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"method": item["method"], "evidence": ["source.tsx:1"]}), encoding="utf-8")
        artifacts.append({
            "method": item["method"],
            "path": path.relative_to(root).as_posix(),
            "sha256": sha(path),
            "stage": item["stage"],
        })
    analyzed = 3 if complete else 2
    return {
        "status": "SATISFEITO",
        "skill": "context-delivery",
        "plan_id": plan["plan_id"],
        "runtime": "claude",
        "agent_id": "agent-1",
        "agent_type": "sample-context-scout",
        "model": "sonnet",
        "lifecycle_receipt": {"path": lifecycle.relative_to(root).as_posix(), "sha256": sha(lifecycle)},
        "artifacts": artifacts,
        "provider_state": {
            "provider": "codegraph",
            "status": "AVAILABLE",
            "index_fresh": fresh,
            "pending_changes": 0 if fresh else 1,
        },
        "coverage": {
            "eligible_files": 3,
            "analyzed_files": analyzed,
            "candidates": 2,
            "confirmed": 1,
            "false_positives": 1,
            "unresolved": 0 if complete else 1,
        },
        "claims": [{"claim": "All candidate components are mapped to entrypoints", "evidence": ["source.tsx:1"]}],
        "unresolved_items": [],
    }


class ContextRoutingTest(unittest.TestCase):
    def test_lexical_enumeration_is_sequential_before_graph(self):
        plan = route_context(task_shape="LEXICAL_ENUMERATION", codegraph_available=True)
        stages = {item["method"]: item["stage"] for item in plan["method_stages"]}
        self.assertLess(stages["rg"], stages["targeted-read"])
        self.assertLess(stages["targeted-read"], stages["codegraph"])
        self.assertNotIn(["codegraph", "rg"], plan["parallel_groups"])

    def test_known_high_radius_symbol_uses_graph_and_text_in_parallel(self):
        plan = route_context(
            task_shape="KNOWN_SYMBOL_IMPACT",
            risk_tier="HIGH",
            codegraph_available=True,
            lsp_available=True,
            symbol_ambiguous=True,
        )
        self.assertIn(["codegraph", "rg"], plan["parallel_groups"])
        stages = {item["method"]: item["stage"] for item in plan["method_stages"]}
        self.assertEqual(stages["codegraph"], stages["rg"])
        self.assertGreater(stages["lsp"], stages["rg"])

    def test_live_state_requires_a_real_tool(self):
        with self.assertRaisesRegex(RoutingError, "read-only live-state"):
            route_context(task_shape="LIVE_STATE", live_state_available=False)

    def test_dependent_methods_cannot_be_forged_as_parallel(self):
        plan = route_context(task_shape="LEXICAL_ENUMERATION", codegraph_available=True)
        plan["parallel_groups"].append(["rg", "targeted-read"])
        with self.assertRaisesRegex(RoutingError, "parallel group|dependent methods"):
            validate_route(plan)


class ContextEvidenceTest(unittest.TestCase):
    def plan(self):
        return route_context(
            task_shape="LEXICAL_ENUMERATION",
            risk_tier="HIGH",
            codegraph_available=True,
            claims_completeness=True,
            allowed_agent_types=["sample-context-scout"],
            allowed_models=["sonnet"],
            plan_id="plan-1",
        )

    def test_context_delivery_is_verified_before_phase_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan()
            delivery = evidence_fixture(root, plan)
            anchor = {
                "mutation_mode": "WORKSPACE_WRITE", "anchor_source": "prompt",
                "context_required": True, "base_sha": "0" * 40,
                "worktree_baseline": [], "execution_graph": GRAPH,
            }
            state = apply_transition(None, "ANCHOR", anchor, repository_root=root)
            with self.assertRaisesRegex(TransitionError, "CONTEXT-PLAN"):
                apply_transition(state, "PHASE-PLAN", phase(), repository_root=root)
            state = apply_transition(state, "CONTEXT-PLAN", plan, repository_root=root)
            state = apply_transition(state, "CONTEXT-DELIVERY", delivery, repository_root=root)
            state = apply_transition(state, "PHASE-PLAN", phase(), repository_root=root)
            self.assertEqual("PHASE-PLAN", state["stage"])
            self.assertEqual("agent-1", state["context_delivery"]["agent_id"])

    def test_stale_graph_cannot_authorize_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan()
            with self.assertRaisesRegex(ContextEvidenceError, "stale"):
                verify_context_delivery(evidence_fixture(root, plan, fresh=False), plan, root)

    def test_exhaustive_claim_requires_closed_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan()
            with self.assertRaisesRegex(ContextEvidenceError, "analyzed_files"):
                verify_context_delivery(evidence_fixture(root, plan, complete=False), plan, root)

    def test_artifact_hash_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan()
            delivery = evidence_fixture(root, plan)
            delivery["artifacts"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ContextEvidenceError, "hash mismatch"):
                verify_context_delivery(delivery, plan, root)


class RuntimeEvidenceHookTest(unittest.TestCase):
    def test_lifecycle_receipt_is_per_agent_and_contains_resolved_model(self):
        hook = ROOT / ".harness/hooks/subagent-lifecycle-ledger.py"
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            definition = project / ".claude/agents/sample-context-scout.md"
            definition.parent.mkdir(parents=True)
            definition.write_text("---\nname: sample-context-scout\nmodel: sonnet\n---\n", encoding="utf-8")
            env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
            common = {
                "session_id": "session-1",
                "agent_id": "agent-1",
                "agent_type": "sample-context-scout",
                "cwd": str(project),
            }
            start = {**common, "hook_event_name": "SubagentStart"}
            result = subprocess.run(
                [sys.executable, str(hook), "--runtime", "claude"],
                input=json.dumps(start), text=True, capture_output=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("lifecycle_receipt_path", result.stdout)
            tool = {
                "hook_event_name": "PostToolUse",
                "session_id": "session-1",
                "cwd": str(project),
                "tool_name": "Agent",
                "tool_input": {"subagent_type": "sample-context-scout"},
                "tool_response": {"agentId": "agent-1", "resolvedModel": "sonnet"},
            }
            result = subprocess.run(
                [sys.executable, str(hook), "--runtime", "claude", "--observe-agent-tool"],
                input=json.dumps(tool), text=True, capture_output=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            stop = {**common, "hook_event_name": "SubagentStop"}
            result = subprocess.run(
                [sys.executable, str(hook), "--runtime", "claude"],
                input=json.dumps(stop), text=True, capture_output=True, env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            receipt = project / ".harness/runs/subagents/session-1/agent-1.jsonl"
            records = [json.loads(line) for line in receipt.read_text().splitlines()]
            self.assertEqual(["SubagentStart", "AgentToolResult", "SubagentStop"], [item["event"] for item in records])
            self.assertEqual("sonnet", records[1]["model"])
            self.assertFalse((project / ".harness/runs/subagents/session-1.jsonl").exists())

    def test_serena_health_policy_blocks_process_fanout_and_rss(self):
        path = ROOT / ".harness/hooks/serena-health-gate.py"
        spec = importlib.util.spec_from_file_location("serena_health_gate", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        processes = module.parse_process_table(
            "101 1048576 python -m serena.server\n102 1048576 python -m serena.server\n103 1048576 python -m serena.server\n"
        )
        ok, reason = module.evaluate(processes, max_processes=2, max_rss_mb=4096)
        self.assertFalse(ok)
        self.assertIn("process count", reason)
        ok, reason = module.evaluate(processes[:2], max_processes=2, max_rss_mb=1024)
        self.assertFalse(ok)
        self.assertIn("RSS", reason)


class RenderedSurfaceTest(unittest.TestCase):
    def test_runtime_native_agents_and_models_exist(self):
        claude_scout = next((ROOT / ".claude/agents").glob("*-context-scout.md"))
        claude_shard = next((ROOT / ".claude/agents").glob("*-context-shard.md"))
        codex_scout = next((ROOT / ".codex/agents").glob("*-context-scout.toml"))
        codex_shard = next((ROOT / ".codex/agents").glob("*-context-shard.toml"))
        self.assertIn("model: sonnet", claude_scout.read_text())
        self.assertIn("model: haiku", claude_shard.read_text())
        self.assertIn('model = "gpt-5.6-terra"', codex_scout.read_text())
        self.assertIn('model = "gpt-5.6-luna"', codex_shard.read_text())
        self.assertNotIn(".codex/agents", claude_scout.read_text())

    def test_lifecycle_and_serena_hooks_are_wired(self):
        claude = json.loads((ROOT / ".claude/settings.json").read_text())["hooks"]
        codex = json.loads((ROOT / ".codex/hooks.json").read_text())["hooks"]
        self.assertIn("SubagentStart", claude)
        self.assertIn("SubagentStop", claude)
        self.assertIn("SubagentStart", codex)
        self.assertIn("SubagentStop", codex)
        self.assertIn("serena-health-gate", json.dumps(claude["PreToolUse"]))
        self.assertIn("serena-health-gate", json.dumps(codex["PreToolUse"]))

    def test_context_skill_and_provider_contracts_exist(self):
        self.assertTrue((ROOT / ".claude/skills/context-delivery/SKILL.md").is_file())
        self.assertTrue((ROOT / ".agents/skills/context-delivery/SKILL.md").is_file())
        self.assertTrue((ROOT / ".harness/context-providers/code-graph.json").is_file())
        self.assertTrue((ROOT / ".harness/context-providers/serena.json").is_file())
        self.assertIn("CONTEXT-DELIVERY", (ROOT / "AGENTS.md").read_text())


if __name__ == "__main__":
    unittest.main()
