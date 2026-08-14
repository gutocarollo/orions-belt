from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
ROOT = LIB.parents[1]
sys.path.insert(0, str(LIB))

from context_evidence import ContextEvidenceError, _verify_lifecycle, _verify_predicates, repository_fingerprint, verify_context_delivery  # noqa: E402
from context_predicates import PredicateError, evaluate_repository_predicates  # noqa: E402
from context_provider_probe import ProviderProbeError, parse_codegraph_status  # noqa: E402
from context_routing import RoutingError, route_context, route_from_repository, validate_route  # noqa: E402
from codex_context_receipts import (  # noqa: E402
    TranscriptReceiptError,
    _read_only_shell,
    capture as capture_codex_receipts,
)
from council_runtime import TransitionError, apply_transition  # noqa: E402

_tool_spec = importlib.util.spec_from_file_location("context_tool_ledger", ROOT / ".harness/hooks/context-tool-ledger.py")
TOOL_LEDGER = importlib.util.module_from_spec(_tool_spec)
assert _tool_spec.loader is not None
sys.modules[_tool_spec.name] = TOOL_LEDGER
_tool_spec.loader.exec_module(TOOL_LEDGER)

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


def run(command: list[str], cwd: Path, *, env: dict[str, str] | None = None, stdin: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, env=env, text=True, capture_output=True,
        input=json.dumps(stdin) if stdin is not None else None,
    )


def git(root: Path, *args: str) -> str:
    result = run(["git", *args], root)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def init_repo(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "context@example.invalid")
    git(root, "config", "user.name", "Context Test")


def phase() -> dict:
    return {
        "skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1",
        "items": ["i1"], "objective": "deliver", "edge_id": "E1",
        "entry_node": "request", "exit_node": "done", "tests": TESTS,
    }


def definition(root: Path, runtime: str, agent_type: str, model: str) -> None:
    if runtime == "claude":
        path = root / ".claude/agents" / f"{agent_type}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {agent_type}\nmodel: {model}\n---\n", encoding="utf-8")
    else:
        path = root / ".codex/agents" / f"{agent_type}.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'name = "{agent_type}"\ndescription = "test"\nmodel = "{model}"\n'
            'sandbox_mode = "read-only"\ndeveloper_instructions = """test"""\n',
            encoding="utf-8",
        )


def lifecycle(root: Path, runtime: str, model: str, agent_type: str = "sample-context-scout") -> Path:
    definition(root, runtime, agent_type, model)
    fingerprint = repository_fingerprint(root)
    path = root / ".harness/runs/subagents/session-1/agent-1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"event": "SubagentStart", "run_id": "run-1", "repository_fingerprint": fingerprint, "session_id": "session-1", "runtime": runtime, "agent_id": "agent-1", "agent_type": agent_type, "configured_model": model, "model": model, "agent_transcript_path": "/tmp/agent-1.jsonl"},
        {"event": "AgentToolResult", "run_id": "run-1", "repository_fingerprint": fingerprint, "session_id": "session-1", "runtime": runtime, "agent_id": "agent-1", "agent_type": agent_type, "configured_model": model, "model": model, "agent_transcript_path": "/tmp/agent-1.jsonl", "usage": {"input_tokens": 10, "output_tokens": 5}, "duration_ms": 20},
        {"event": "SubagentStop", "run_id": "run-1", "repository_fingerprint": fingerprint, "session_id": "session-1", "runtime": runtime, "agent_id": "agent-1", "agent_type": agent_type, "configured_model": model, "model": model, "agent_transcript_path": "/tmp/agent-1.jsonl"},
    ]
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
    return path


def emit_tool(root: Path, runtime: str, call_id: str, tool_name: str, tool_input: dict, response: object) -> None:
    common = {
        "run_id": "run-1", "repository_fingerprint": repository_fingerprint(root),
        "session_id": "session-1", "agent_id": "agent-1", "agent_type": "sample-context-scout",
        "agent_transcript_path": "/tmp/agent-1.jsonl", "cwd": str(root), "model": "sonnet" if runtime == "claude" else "gpt-5.6-terra",
        "tool_use_id": call_id, "tool_name": tool_name, "tool_input": tool_input,
    }
    for event, extra in (("PreToolUse", {}), ("PostToolUse", {"tool_response": response})):
        TOOL_LEDGER.record_event({**common, "hook_event_name": event, **extra}, runtime, root)


def tool_records(root: Path) -> tuple[Path, dict[str, dict]]:
    path = root / ".harness/runs/context-tools/session-1/tools.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    post = {item["tool_use_id"]: item for item in records if item["event"] == "PostToolUse"}
    return path, post


def artifact(root: Path, method: str, post: dict[str, dict], *call_ids: str) -> dict:
    receipts = [
        {
            "tool_use_id": call_id,
            "input_sha256": post[call_id]["input_sha256"],
            "output_sha256": post[call_id]["output_sha256"],
        }
        for call_id in call_ids
    ]
    path = root / ".harness/runs/context" / f"{method}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"method": method, "tool_receipts": receipts, "findings": [f"{method}:ok"]}, sort_keys=True), encoding="utf-8")
    return {"method": method, "path": path.relative_to(root).as_posix(), "sha256": sha(path), "tool_receipts": receipts}


def lexical_evidence(root: Path, plan: dict, *, runtime="claude", model="sonnet", fresh=True, order_ok=True, complete=True) -> dict:
    for relative, content in (
        ("docs/index.md", "router\n"),
        ("src/a.tsx", "hover:scale-105\n"),
        ("src/b.tsx", "hover:scale-105\n"),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    lifecycle_path = lifecycle(root, runtime, model)
    order = [
        ("docs", "Read", {"file_path": "docs/index.md"}, {"content": "router"}),
        ("rg", "Grep", {"pattern": "hover:"}, {"matches": ["src/a.tsx:1", "src/b.tsx:1"]}),
        ("read", "Read", {"file_path": "src/a.tsx"}, {"content": "hover:scale-105"}),
        ("graph-status", "mcp__codegraph__codegraph_status", {"root": "."}, {"version": "1.2.3", "pending_changes": 0 if fresh else 1, "index_fresh": fresh}),
        ("graph-query", "mcp__codegraph__codegraph_explore", {"symbol": "HoverCard"}, {"paths": ["HoverCard", "DashboardPage"]}),
    ]
    if not order_ok:
        order[3], order[4] = order[4], order[3]
    for args in order:
        emit_tool(root, runtime, *args)
    receipt_path, post = tool_records(root)
    artifacts = [
        artifact(root, "canonical-docs", post, "docs"),
        artifact(root, "rg", post, "rg"),
        artifact(root, "targeted-read", post, "read"),
        artifact(root, "codegraph-status", post, "graph-status"),
        artifact(root, "codegraph", post, "graph-query"),
    ]
    provider = parse_codegraph_status(post["graph-status"]["response_excerpt"])
    provider["source_tool_call_id"] = "graph-status"
    analyzed = 3 if complete else 2
    fingerprint = repository_fingerprint(root)
    plan["council_binding"] = {
        "run_id": "run-1", "base_sha": "0" * 40,
        "repository_fingerprint": fingerprint,
    }
    return {
        "status": "SATISFEITO", "skill": "context-delivery", "plan_id": plan["plan_id"],
        "run_id": "run-1", "session_id": "session-1", "base_sha": "0" * 40,
        "repository_fingerprint": fingerprint,
        "runtime": runtime, "agent_id": "agent-1", "agent_type": "sample-context-scout", "model": model,
        "lifecycle_receipt": {"path": lifecycle_path.relative_to(root).as_posix(), "sha256": sha(lifecycle_path)},
        "tool_receipt": {"path": receipt_path.relative_to(root).as_posix(), "sha256": sha(receipt_path)},
        "predicate_resolutions": [{"predicate": "P5", "status": fresh, "source_tool_call_ids": ["graph-status"], "evidence": ["CodeGraph status receipt"], "definition_count": 0, "definition_ids": []}], "artifacts": artifacts, "provider_state": provider,
        "coverage": {
            "eligible_files": 3,
            "analyzed_files": analyzed,
            "candidates": 2,
            "confirmed": 1,
            "false_positives": 1 if complete else 0,
            "unresolved": 0 if complete else 1,
            "eligible_paths": ["docs/index.md", "src/a.tsx", "src/b.tsx"],
            "analyzed_paths": ["docs/index.md", "src/a.tsx", "src/b.tsx"] if complete else ["docs/index.md", "src/a.tsx"],
            "candidate_ids": ["src/a.tsx:1", "src/b.tsx:1"],
            "confirmed_candidate_ids": ["src/a.tsx:1"],
            "false_positive_candidate_ids": ["src/b.tsx:1"] if complete else [],
            "unresolved_candidate_ids": [] if complete else ["src/b.tsx:1"],
            "source_tool_call_ids": ["docs", "rg", "read"],
        },
        "claims": [{"claim": "All candidates are classified", "evidence": [artifacts[-1]["path"]]}],
        "unresolved_items": [],
        "execution_metrics": {"source": "OBSERVED", "duration_ms": 20, "input_tokens": 10, "output_tokens": 5, "tool_calls": 5, "reason": ""},
    }


class CodexTranscriptReceiptTest(unittest.TestCase):
    def _transcript(self, root: Path, command: str) -> tuple[Path, Path, str]:
        session_id = "session-codex"
        active = root / ".harness/runs/ACTIVE"
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text("run-1\n", encoding="utf-8")
        definition(root, "codex", "sample-context-scout", "gpt-5.6-terra")
        sessions = root / "codex-home/sessions/2026/08/10"
        sessions.mkdir(parents=True)
        parent = sessions / "parent.jsonl"
        parent.write_text(json.dumps({"type": "session_meta", "payload": {"id": session_id}}) + "\n")
        child = sessions / "child.jsonl"
        events = [
            {"timestamp": "2026-08-10T12:00:00Z", "type": "session_meta", "payload": {
                "id": "agent-codex", "session_id": session_id, "cwd": str(root),
                "thread_source": "subagent", "agent_role": "sample-context-scout",
            }},
            {"timestamp": "2026-08-10T12:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.6-terra"}},
            {"timestamp": "2026-08-10T12:00:02Z", "type": "response_item", "payload": {
                "type": "custom_tool_call", "name": "exec", "call_id": "call-read",
                "input": f'const r = await tools.exec_command({json.dumps({"cmd": command})}); text(r);',
            }},
            {"timestamp": "2026-08-10T12:00:03Z", "type": "response_item", "payload": {
                "type": "custom_tool_call_output", "call_id": "call-read",
                "output": [{"type": "input_text", "text": "runtime-marker"}],
            }},
            {"timestamp": "2026-08-10T12:00:04Z", "type": "event_msg", "payload": {
                "type": "mcp_tool_call_end", "call_id": "call-graph", "read_only_hint": True,
                "invocation": {"server": "codegraph", "tool": "codegraph_explore", "arguments": {"query": "runtime-marker"}},
                "result": {"Ok": {"content": [{"type": "text", "text": "marker.txt:1"}]}},
            }},
            {"timestamp": "2026-08-10T12:00:05Z", "type": "event_msg", "payload": {
                "type": "token_count", "info": {"total_token_usage": {"input_tokens": 12, "output_tokens": 3}},
            }},
            {"timestamp": "2026-08-10T12:00:06Z", "type": "event_msg", "payload": {
                "type": "task_complete", "last_agent_message": "done", "duration_ms": 25,
            }},
        ]
        child.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
        return parent, child, session_id

    def test_completed_read_only_child_is_bound_to_transcript_and_real_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent, child, session_id = self._transcript(root, "sed -n '1,10p' marker.txt")
            previous = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = str(root / "codex-home")
            try:
                result = capture_codex_receipts(root, session_id, parent)
            finally:
                if previous is None:
                    os.environ.pop("CODEX_HOME", None)
                else:
                    os.environ["CODEX_HOME"] = previous
            self.assertEqual("agent-codex", result["agents"][0]["agent_id"])
            lifecycle_path = root / result["agents"][0]["lifecycle_receipt"]
            lifecycle_records = [json.loads(line) for line in lifecycle_path.read_text().splitlines()]
            self.assertEqual(["SubagentStart", "AgentToolResult", "SubagentStop"], [item["event"] for item in lifecycle_records])
            self.assertTrue(all(item["transcript_sha256"] == sha(child) for item in lifecycle_records))
            tools_path = root / result["agents"][0]["tool_receipt"]
            posts = [json.loads(line) for line in tools_path.read_text().splitlines() if '"PostToolUse"' in line]
            self.assertEqual({"targeted-read", "codegraph"}, {method for item in posts for method in item["methods"]})
            delivery = {
                "agent_id": "agent-codex", "agent_type": "sample-context-scout",
                "runtime": "codex", "model": "gpt-5.6-terra",
                "run_id": "run-1", "session_id": session_id,
                "repository_fingerprint": repository_fingerprint(root),
                "lifecycle_receipt": {"path": lifecycle_path.relative_to(root).as_posix(), "sha256": sha(lifecycle_path)},
            }
            plan = {"allowed_models": ["gpt-5.6-terra"], "allowed_agent_types": ["sample-context-scout"]}
            _verify_lifecycle(root, delivery, plan)
            child.write_text(child.read_text() + "{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ContextEvidenceError, "transcript hash mismatch"):
                _verify_lifecycle(root, delivery, plan)

    def test_child_write_command_is_rejected_instead_of_omitted_from_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent, _, session_id = self._transcript(root, "echo corrupted > marker.txt")
            previous = os.environ.get("CODEX_HOME")
            os.environ["CODEX_HOME"] = str(root / "codex-home")
            try:
                with self.assertRaisesRegex(TranscriptReceiptError, "non-read-only"):
                    capture_codex_receipts(root, session_id, parent)
            finally:
                if previous is None:
                    os.environ.pop("CODEX_HOME", None)
                else:
                    os.environ["CODEX_HOME"] = previous

    def test_shell_validator_rejects_operator_and_executable_option_bypasses(self):
        attacks = (
            "ls ; touch /tmp/orions-write",
            "ls & touch /tmp/orions-write",
            "find . -name '*.tmp' -delete",
            "find . -exec sh -c 'touch /tmp/orions-write' \\;",
            "rg --pre 'touch /tmp/orions-write' pattern .",
        )
        for command in attacks:
            with self.subTest(command=command):
                self.assertFalse(_read_only_shell(command))

    def test_shell_validator_preserves_required_read_only_commands(self):
        commands = (
            "sed -n '1,80p' src/a.tsx",
            "rg -n hover src",
            "git diff -- src/a.tsx",
            "codegraph status",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(_read_only_shell(command))


class PredicateAndRoutingTest(unittest.TestCase):
    def test_p1_p2_p3_are_computed_from_git_and_risk_cannot_be_understated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_repo(root)
            (root / "src/core").mkdir(parents=True)
            (root / "src/core/a.py").write_text("value = 1\n")
            git(root, "add", "-A"); git(root, "commit", "-qm", "base")
            base = git(root, "rev-parse", "HEAD")
            (root / "src/core/a.py").write_text("INSERT INTO x VALUES (1)\n")
            (root / "b.py").write_text("b=1\n"); (root / "c.ts").write_text("export const c=1\n")
            git(root, "add", "-A"); git(root, "commit", "-qm", "change")
            predicates = evaluate_repository_predicates(root, base_ref=base, head_ref="HEAD", core_paths="src/core/", data_write_patterns="INSERT INTO", task_shape="KNOWN_SYMBOL_IMPACT")
            self.assertTrue(predicates["P1"]["status"])
            self.assertTrue(predicates["P2"]["status"])
            self.assertTrue(predicates["P3"]["status"])
            plan = route_from_repository(root, base_ref=base, head_ref="HEAD", task_shape="KNOWN_SYMBOL_IMPACT", core_paths="src/core/", data_write_patterns="INSERT INTO", codegraph_available=True)
            self.assertEqual("CRITICAL", plan["risk_tier"])
            with self.assertRaisesRegex(RoutingError, "understates"):
                route_context(task_shape="KNOWN_SYMBOL_IMPACT", predicates=predicates, risk_tier="LOW", codegraph_available=True)

    def test_git_revision_endpoints_are_resolved_and_option_like_refs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init_repo(root)
            (root / "a.py").write_text("value = 1\n", encoding="utf-8")
            git(root, "add", "-A"); git(root, "commit", "-qm", "base")
            base = git(root, "rev-parse", "HEAD")
            (root / "a.py").write_text("value = 2\n", encoding="utf-8")
            git(root, "add", "-A"); git(root, "commit", "-qm", "head")
            predicates = evaluate_repository_predicates(
                root, base_ref=base, head_ref="HEAD", task_shape="DIRECT_TARGETED"
            )
            self.assertRegex(predicates["P1"]["resolved_refs"]["head"], r"^[0-9a-f]{40}$")
            self.assertNotIn("HEAD", predicates["P1"]["command"]
            )
            with self.assertRaisesRegex(PredicateError, "unsafe base_ref"):
                evaluate_repository_predicates(
                    root, base_ref="--output=/tmp/not-allowed", head_ref="HEAD", task_shape="DIRECT_TARGETED"
                )
            with self.assertRaisesRegex(PredicateError, "unsafe head_ref"):
                evaluate_repository_predicates(
                    root, base_ref=base, head_ref="HEAD...main", task_shape="DIRECT_TARGETED"
                )

    def test_pre_change_diff_predicates_are_deferred_not_false(self):
        plan = route_context(task_shape="DIRECT_TARGETED")
        self.assertEqual("DEFERRED", plan["predicates"]["P1"]["status"])
        self.assertEqual("DEFERRED", plan["predicates"]["P2"]["status"])
        self.assertEqual("DEFERRED", plan["predicates"]["P3"]["status"])
        self.assertEqual("MEDIUM", plan["risk_tier"])

    def test_lexical_enumeration_is_sequential_before_graph(self):
        plan = route_context(task_shape="LEXICAL_ENUMERATION", codegraph_available=True, canonical_docs=["docs/index.md"])
        stages = {item["method"]: item["stage"] for item in plan["method_stages"]}
        self.assertLess(stages["rg"], stages["targeted-read"])
        self.assertLessEqual(stages["codegraph-status"], stages["rg"])
        self.assertLess(stages["codegraph-status"], stages["codegraph"])
        self.assertLess(stages["targeted-read"], stages["codegraph"])
        self.assertNotIn(["codegraph", "rg"], plan["parallel_groups"])

    def test_known_high_radius_symbol_uses_graph_and_text_in_parallel_then_conditional_lsp(self):
        plan = route_context(task_shape="KNOWN_SYMBOL_IMPACT", risk_tier="HIGH", codegraph_available=True, lsp_available=True)
        self.assertIn(["codegraph-status", "rg"], plan["parallel_groups"])
        stages = {item["method"]: item["stage"] for item in plan["method_stages"]}
        self.assertLess(stages["codegraph-status"], stages["codegraph"])
        self.assertEqual([{"method": "lsp", "when_predicate": "P4", "equals": True}], plan["conditional_methods"])

    def test_graph_query_requires_freshness_preflight(self):
        plan = route_context(task_shape="KNOWN_SYMBOL_IMPACT", risk_tier="HIGH", codegraph_available=True)
        edges = {(item["before"], item["after"]) for item in plan["dependency_edges"]}
        self.assertIn(("codegraph-status", "codegraph"), edges)

    def test_dependent_methods_cannot_be_forged_as_parallel(self):
        plan = route_context(task_shape="LEXICAL_ENUMERATION", codegraph_available=True)
        plan["parallel_groups"].append(["rg", "targeted-read"])
        with self.assertRaisesRegex(RoutingError, "parallel|dependent"):
            validate_route(plan)

    def test_parallel_shards_fail_closed_until_shard_receipts_are_enforced(self):
        with self.assertRaisesRegex(RoutingError, "parallel_shards.*not supported"):
            route_context(task_shape="LEXICAL_ENUMERATION", parallel_shards=["src/a", "src/b"])

    def test_live_state_fails_closed_without_a_real_tool(self):
        with self.assertRaisesRegex(RoutingError, "read-only live-state"):
            route_context(task_shape="LIVE_STATE", live_state_available=False)


class ProviderProbeTest(unittest.TestCase):
    def test_unrelated_current_text_is_not_accepted_as_graph_freshness(self):
        with self.assertRaisesRegex(ProviderProbeError, "explicitly prove freshness"):
            parse_codegraph_status("Current branch: main\nGraph root: .codegraph")
        value = parse_codegraph_status("[OK] Index is up to date\nPending changes: 0")
        self.assertTrue(value["index_fresh"])
        self.assertEqual(0, value["pending_changes"])

    def test_nested_mcp_status_is_parsed_and_requires_explicit_freshness(self):
        value = {"content": [{"text": json.dumps({"version": "1.2.3", "pending_changes": 0, "index_fresh": True})}]}
        result = parse_codegraph_status(value)
        self.assertEqual("1.2.3", result["provider_version"])
        self.assertTrue(result["index_fresh"])
        text_result = parse_codegraph_status("Index Statistics:\nFiles: 28\n[OK] Index is up to date")
        self.assertTrue(text_result["index_fresh"])
        self.assertEqual(0, text_result["pending_changes"])
        with self.assertRaises(ProviderProbeError):
            parse_codegraph_status("CodeGraph is probably fine")

    def test_current_codegraph_json_status_is_supported(self):
        current = {
            "version": "1.5.0",
            "pendingChanges": {"added": 0, "modified": 0, "removed": 0},
            "worktreeMismatch": None,
            "index": {
                "state": "complete",
                "pendingRefs": 0,
                "reindexRecommended": False,
            },
        }
        result = parse_codegraph_status({"output": json.dumps(current), "exit_code": 0})
        self.assertTrue(result["index_fresh"])
        self.assertEqual(0, result["pending_changes"])
        self.assertEqual("1.5.0", result["provider_version"])


class EvidenceTest(unittest.TestCase):
    def plan(self, runtime="claude", model="sonnet") -> dict:
        return route_context(task_shape="LEXICAL_ENUMERATION", codegraph_available=True, claims_completeness=True, canonical_docs=["docs/index.md"], allowed_agent_types=["sample-context-scout"], allowed_models=[model], plan_id="plan-1")

    def test_real_tool_receipts_artifact_hashes_model_freshness_and_order_authorize_context(self):
        for runtime, model in (("claude", "sonnet"), ("codex", "gpt-5.6-terra")):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = self.plan(runtime, model)
                result = verify_context_delivery(lexical_evidence(root, plan, runtime=runtime, model=model), plan, root)
                self.assertEqual(model, result["model"])
                self.assertEqual(5, result["tool_calls"])

    def test_resolved_claude_model_family_must_match_configured_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(model="sonnet")
            delivery = lexical_evidence(root, plan, model="sonnet")
            lifecycle_path = root / delivery["lifecycle_receipt"]["path"]
            records = [json.loads(line) for line in lifecycle_path.read_text().splitlines() if line.strip()]
            for record in records:
                if record["event"] == "AgentToolResult":
                    record["model"] = "claude-sonnet-4-6-20260801"
            lifecycle_path.write_text("".join(json.dumps(item) + "\n" for item in records))
            delivery["lifecycle_receipt"]["sha256"] = sha(lifecycle_path)
            delivery["model"] = "claude-sonnet-4-6-20260801"
            result = verify_context_delivery(delivery, plan, root)
            self.assertIn("sonnet", result["model"])

    def test_different_resolved_model_family_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(model="sonnet")
            delivery = lexical_evidence(root, plan, model="sonnet")
            lifecycle_path = root / delivery["lifecycle_receipt"]["path"]
            records = [json.loads(line) for line in lifecycle_path.read_text().splitlines() if line.strip()]
            for record in records:
                if record["event"] == "AgentToolResult":
                    record["model"] = "claude-opus-4-6-20260801"
            lifecycle_path.write_text("".join(json.dumps(item) + "\n" for item in records))
            delivery["lifecycle_receipt"]["sha256"] = sha(lifecycle_path)
            delivery["model"] = "claude-opus-4-6-20260801"
            with self.assertRaisesRegex(ContextEvidenceError, "delivery model is not allowed|observed runtime model"):
                verify_context_delivery(delivery, plan, root)

    def test_empty_model_and_agent_allowlists_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = route_context(
                task_shape="LEXICAL_ENUMERATION",
                codegraph_available=True,
                claims_completeness=True,
                canonical_docs=["docs/index.md"],
                allowed_agent_types=[],
                allowed_models=[],
                plan_id="empty-authorization",
            )
            delivery = lexical_evidence(root, plan)
            with self.assertRaisesRegex(ContextEvidenceError, "allowed_(models|agent_types)"):
                verify_context_delivery(delivery, plan, root)

    def test_pre_post_tool_identity_cannot_be_spliced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            receipt = root / delivery["tool_receipt"]["path"]
            records = [json.loads(line) for line in receipt.read_text().splitlines() if line.strip()]
            for record in records:
                if record["event"] == "PostToolUse" and record["tool_use_id"] == "rg":
                    record["tool_name"] = "mcp__codegraph__codegraph_status"
                    record["methods"] = ["codegraph"]
            receipt.write_text("".join(json.dumps(item) + "\n" for item in records))
            delivery["tool_receipt"]["sha256"] = sha(receipt)
            with self.assertRaisesRegex(ContextEvidenceError, "tool_name changed|method classification changed"):
                verify_context_delivery(delivery, plan, root)

    def test_status_call_cannot_substitute_for_operational_graph_query(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            graph_artifact = next(item for item in delivery["artifacts"] if item["method"] == "codegraph")
            receipt_path = root / delivery["tool_receipt"]["path"]
            posts = {item["tool_use_id"]: item for item in (json.loads(line) for line in receipt_path.read_text().splitlines()) if item["event"] == "PostToolUse"}
            status = posts["graph-status"]
            graph_artifact["tool_receipts"] = [{
                "tool_use_id": "graph-status",
                "input_sha256": status["input_sha256"],
                "output_sha256": status["output_sha256"],
            }]
            artifact_path = root / graph_artifact["path"]
            payload = json.loads(artifact_path.read_text())
            payload["tool_receipts"] = graph_artifact["tool_receipts"]
            artifact_path.write_text(json.dumps(payload, sort_keys=True))
            graph_artifact["sha256"] = sha(artifact_path)
            with self.assertRaisesRegex(ContextEvidenceError, "does not prove method codegraph"):
                verify_context_delivery(delivery, plan, root)

    def test_coordinator_cli_status_in_same_session_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            receipt = root / delivery["tool_receipt"]["path"]
            records = [json.loads(line) for line in receipt.read_text().splitlines() if line.strip()]
            for record in records:
                if record["tool_use_id"] == "graph-status":
                    record["agent_id"] = ""
                    record["agent_type"] = ""
                    record["transcript_path"] = "/tmp/root-session.jsonl"
                    record["model"] = "gpt-5.6-sol"
                    record["tool_name"] = "Bash"
                    record["input_excerpt"] = '{"command":"codegraph status --json"}'
                    record["methods"] = ["codegraph-status"]
            receipt.write_text("".join(json.dumps(item) + "\n" for item in records))
            delivery["tool_receipt"]["sha256"] = sha(receipt)
            result = verify_context_delivery(delivery, plan, root)
            self.assertEqual(5, result["tool_calls"])

    def test_coordinator_cannot_supply_operational_context_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            receipt = root / delivery["tool_receipt"]["path"]
            records = [json.loads(line) for line in receipt.read_text().splitlines() if line.strip()]
            for record in records:
                if record["tool_use_id"] == "graph-query":
                    record["agent_id"] = ""
                    record["agent_type"] = ""
                    record["transcript_path"] = ""
            receipt.write_text("".join(json.dumps(item) + "\n" for item in records))
            delivery["tool_receipt"]["sha256"] = sha(receipt)
            with self.assertRaisesRegex(ContextEvidenceError, "unknown tool call"):
                verify_context_delivery(delivery, plan, root)

    def test_arbitrary_file_labeled_codegraph_without_exact_receipts_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            delivery["artifacts"][-1]["tool_receipts"][0]["output_sha256"] = "0" * 64
            with self.assertRaisesRegex(ContextEvidenceError, "output hash"):
                verify_context_delivery(delivery, plan, root)

    def test_actual_tool_order_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan, order_ok=False)
            with self.assertRaisesRegex(ContextEvidenceError, "actual tool order"):
                verify_context_delivery(delivery, plan, root)

    def test_tool_receipt_runtime_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            receipt = root / delivery["tool_receipt"]["path"]
            records = [json.loads(line) for line in receipt.read_text(encoding="utf-8").splitlines() if line.strip()]
            for record in records:
                record["runtime"] = "codex"
            receipt.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
            delivery["tool_receipt"]["sha256"] = sha(receipt)
            with self.assertRaisesRegex(ContextEvidenceError, "attributable to the context agent"):
                verify_context_delivery(delivery, plan, root)

    def test_claim_requires_existing_artifact_or_valid_path_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            delivery["claims"] = [{"claim": "All candidates are classified", "evidence": ["missing.tsx:999"]}]
            with self.assertRaisesRegex(ContextEvidenceError, "valid path:line"):
                verify_context_delivery(delivery, plan, root)

    def test_p5_status_cannot_disagree_with_runtime_provider_output(self):
        plan = route_context(task_shape="LEXICAL_ENUMERATION", codegraph_available=True)
        tools = {
            "status": {
                "methods": ["codegraph-status"],
                "tool_name": "mcp__codegraph__codegraph_status",
                "response_excerpt": "[OK] Index is up to date",
            }
        }
        delivery = {"predicate_resolutions": [{
            "predicate": "P5", "status": False, "source_tool_call_ids": ["status"],
            "evidence": ["provider status"], "definition_count": 0, "definition_ids": [],
        }]}
        with self.assertRaisesRegex(ContextEvidenceError, "P5 status"):
            _verify_predicates(delivery, plan, tools)

    def test_execution_metrics_are_bound_to_lifecycle_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            delivery["execution_metrics"]["input_tokens"] = 999
            with self.assertRaisesRegex(ContextEvidenceError, "input_tokens"):
                verify_context_delivery(delivery, plan, root)

    def test_unavailable_metrics_cannot_smuggle_unverified_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            delivery["execution_metrics"] = {"source": "UNAVAILABLE", "duration_ms": 1, "input_tokens": 0, "output_tokens": 0, "tool_calls": 5, "reason": "runtime did not expose metrics"}
            with self.assertRaisesRegex(ContextEvidenceError, "UNAVAILABLE metrics"):
                verify_context_delivery(delivery, plan, root)

    def test_stale_provider_and_open_coverage_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan, fresh=False)
            with self.assertRaisesRegex(ContextEvidenceError, "stale|fresh"):
                verify_context_delivery(delivery, plan, root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan, complete=False)
            with self.assertRaisesRegex(ContextEvidenceError, "analyzed_files"):
                verify_context_delivery(delivery, plan, root)

    def test_delivery_is_rejected_after_repository_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan()
            delivery = lexical_evidence(root, plan)
            (root / "src/a.tsx").write_text("changed after context\n", encoding="utf-8")
            with self.assertRaisesRegex(ContextEvidenceError, "fingerprint|drift"):
                verify_context_delivery(delivery, plan, root)

    def test_coverage_counts_must_be_derived_from_existing_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = self.plan(); delivery = lexical_evidence(root, plan)
            delivery["coverage"]["eligible_files"] = 999
            delivery["coverage"]["analyzed_files"] = 999
            with self.assertRaisesRegex(ContextEvidenceError, "eligible_files.*eligible_paths|analyzed_files.*analyzed_paths"):
                verify_context_delivery(delivery, plan, root)

    def test_coverage_identities_must_appear_in_source_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "src/fabricated.tsx"
            fake.parent.mkdir(parents=True)
            fake.write_text("hover:scale-105\n")
            plan = self.plan(); delivery = lexical_evidence(root, plan)
            delivery["coverage"]["eligible_paths"][2] = "src/fabricated.tsx"
            delivery["coverage"]["analyzed_paths"][2] = "src/fabricated.tsx"
            delivery["coverage"]["candidate_ids"][1] = "src/fabricated.tsx:1"
            delivery["coverage"]["false_positive_candidate_ids"][0] = "src/fabricated.tsx:1"
            with self.assertRaisesRegex(ContextEvidenceError, "absent from source tool receipts"):
                verify_context_delivery(delivery, plan, root)

    def test_p4_definition_ids_must_exist_in_runtime_output(self):
        plan = route_context(task_shape="KNOWN_SYMBOL_IMPACT", risk_tier="HIGH", codegraph_available=True, lsp_available=True, allowed_agent_types=["sample-context-scout"], allowed_models=["sonnet"], plan_id="p4")
        resolution = {"predicate": "P4", "status": False, "source_tool_call_ids": ["graph-query"], "evidence": ["two defs"], "definition_count": 2, "definition_ids": ["A", "B"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivery = lexical_evidence(root, self.plan())
            delivery["plan_id"] = plan["plan_id"]
            plan["council_binding"] = {
                "run_id": delivery["run_id"],
                "base_sha": delivery["base_sha"],
                "repository_fingerprint": delivery["repository_fingerprint"],
            }
            delivery["predicate_resolutions"] = [resolution, {"predicate": "P5", "status": True, "source_tool_call_ids": ["graph-status"], "evidence": ["fresh"], "definition_count": 0, "definition_ids": []}]
            with self.assertRaisesRegex(ContextEvidenceError, "definition id"):
                verify_context_delivery(delivery, plan, root)

    def test_p4_status_is_derived_from_proven_definition_count(self):
        plan = route_context(task_shape="KNOWN_SYMBOL_IMPACT", risk_tier="HIGH", codegraph_available=True, lsp_available=True)
        tools = {
            "graph": {"methods": ["codegraph"], "tool_name": "mcp__codegraph__codegraph_search", "response_excerpt": "definitions: src/a.py:10 src/b.py:20", "definition_ids": ["src/a.py:10", "src/b.py:20"]},
            "status": {"methods": ["codegraph-status"], "tool_name": "mcp__codegraph__codegraph_status", "response_excerpt": "[OK] Index is up to date", "definition_ids": []},
        }
        delivery = {"predicate_resolutions": [
            {"predicate": "P4", "status": False, "source_tool_call_ids": ["graph"], "evidence": ["definitions"], "definition_count": 2, "definition_ids": ["src/a.py:10", "src/b.py:20"]},
            {"predicate": "P5", "status": True, "source_tool_call_ids": ["status"], "evidence": ["fresh"], "definition_count": 0, "definition_ids": []},
        ]}
        with self.assertRaisesRegex(ContextEvidenceError, "P4 status"):
            _verify_predicates(delivery, plan, tools)

    def test_p4_cannot_omit_an_observed_definition(self):
        plan = route_context(task_shape="KNOWN_SYMBOL_IMPACT", risk_tier="HIGH", codegraph_available=True, lsp_available=True)
        tools = {
            "graph": {"methods": ["codegraph"], "tool_name": "mcp__codegraph__codegraph_explore", "response_excerpt": "definitions: src/a.py:10 src/b.py:20", "definition_ids": ["src/a.py:10", "src/b.py:20"]},
            "status": {"methods": ["codegraph-status"], "tool_name": "mcp__codegraph__codegraph_status", "response_excerpt": "[OK] Index is up to date", "definition_ids": []},
        }
        delivery = {"predicate_resolutions": [
            {"predicate": "P4", "status": False, "source_tool_call_ids": ["graph"], "evidence": ["definitions"], "definition_count": 1, "definition_ids": ["src/a.py:10"]},
            {"predicate": "P5", "status": True, "source_tool_call_ids": ["status"], "evidence": ["fresh"], "definition_count": 0, "definition_ids": []},
        ]}
        with self.assertRaisesRegex(ContextEvidenceError, "complete observed definition set"):
            _verify_predicates(delivery, plan, tools)

    def test_p4_uses_full_structured_definitions_beyond_excerpt_limit(self):
        plan = route_context(task_shape="KNOWN_SYMBOL_IMPACT", risk_tier="HIGH", codegraph_available=True, lsp_available=True)
        tools = {
            "graph": {
                "methods": ["codegraph"],
                "tool_name": "mcp__codegraph__codegraph_explore",
                "response_excerpt": "definitions: src/a.py:10 " + ("note " * 4000),
                "definition_ids": ["src/a.py:10", "src/b.py:20"],
            },
            "status": {"methods": ["codegraph-status"], "tool_name": "mcp__codegraph__codegraph_status", "response_excerpt": "[OK] Index is up to date", "definition_ids": []},
        }
        delivery = {"predicate_resolutions": [
            {"predicate": "P4", "status": False, "source_tool_call_ids": ["graph"], "evidence": ["definitions"], "definition_count": 1, "definition_ids": ["src/a.py:10"]},
            {"predicate": "P5", "status": True, "source_tool_call_ids": ["status"], "evidence": ["fresh"], "definition_count": 0, "definition_ids": []},
        ]}
        with self.assertRaisesRegex(ContextEvidenceError, "complete observed definition set"):
            _verify_predicates(delivery, plan, tools)


class StateMachineTest(unittest.TestCase):
    def test_phase_plan_is_blocked_until_verified_context_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan = route_context(task_shape="DIRECT_TARGETED", allowed_agent_types=["sample-context-scout"], allowed_models=["sonnet"], plan_id="state")
            state = apply_transition(None, "ANCHOR", {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "prompt", "context_required": True, "run_id": "state-run", "base_sha": "0" * 40, "worktree_baseline": [], "execution_graph": GRAPH}, repository_root=root, run_id="state-run")
            with self.assertRaisesRegex(TransitionError, "CONTEXT-PLAN"):
                apply_transition(state, "PHASE-PLAN", phase(), repository_root=root)
            state = apply_transition(state, "CONTEXT-PLAN", plan, repository_root=root, run_id="state-run")
            with self.assertRaisesRegex(TransitionError, "CONTEXT-DELIVERY"):
                apply_transition(state, "PHASE-PLAN", phase(), repository_root=root)

    def test_context_delivery_cannot_be_replayed_into_a_different_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = route_context(
                task_shape="LEXICAL_ENUMERATION",
                codegraph_available=True,
                claims_completeness=True,
                canonical_docs=["docs/index.md"],
                allowed_agent_types=["sample-context-scout"],
                allowed_models=["sonnet"],
                plan_id="replay-plan",
            )
            delivery = lexical_evidence(root, plan)
            anchor = {
                "mutation_mode": "WORKSPACE_WRITE", "anchor_source": "prompt",
                "context_required": True, "base_sha": "0" * 40,
                "worktree_baseline": [], "execution_graph": GRAPH,
            }
            state_a = apply_transition(
                None, "ANCHOR", {**anchor, "run_id": "run-1"},
                repository_root=root, run_id="run-1",
            )
            state_a = apply_transition(
                state_a, "CONTEXT-PLAN", plan, repository_root=root, run_id="run-1"
            )
            apply_transition(
                state_a, "CONTEXT-DELIVERY", delivery,
                repository_root=root, run_id="run-1",
            )

            plan_b = dict(plan)
            plan_b.pop("council_binding")
            state_b = apply_transition(
                None, "ANCHOR", {**anchor, "run_id": "run-2"},
                repository_root=root, run_id="run-2",
            )
            state_b = apply_transition(
                state_b, "CONTEXT-PLAN", plan_b, repository_root=root, run_id="run-2"
            )
            with self.assertRaisesRegex(TransitionError, "run_id"):
                apply_transition(
                    state_b, "CONTEXT-DELIVERY", delivery,
                    repository_root=root, run_id="run-2",
                )


class ToolLedgerHookCliTest(unittest.TestCase):
    def test_cli_requires_runtime_tool_use_id_and_records_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hook = ROOT / ".harness/hooks/context-tool-ledger.py"
            payload = {
                "hook_event_name": "PreToolUse", "session_id": "s", "agent_id": "a",
                "agent_type": "sample-context-scout", "cwd": str(root), "model": "sonnet",
                "run_id": "run-1",
                "tool_use_id": "call-1", "tool_name": "Grep", "tool_input": {"pattern": "x"},
            }
            result = run([sys.executable, str(hook), "--runtime", "claude"], root, env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)}, stdin=payload)
            self.assertEqual(0, result.returncode, result.stderr)
            receipt = root / ".harness/runs/context-tools/s/tools.jsonl"
            record = json.loads(receipt.read_text().strip())
            self.assertEqual("call-1", record["tool_use_id"])
            bad = dict(payload); bad.pop("tool_use_id")
            result = run([sys.executable, str(hook), "--runtime", "claude"], root, env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)}, stdin=bad)
            self.assertEqual(2, result.returncode)

    def test_context_tool_ledger_rejects_symlinked_session_directory(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_directory:
            root = Path(directory); outside = Path(outside_directory)
            session_parent = root / ".harness/runs/context-tools"
            session_parent.mkdir(parents=True)
            (session_parent / "s").symlink_to(outside, target_is_directory=True)
            payload = {
                "hook_event_name": "PreToolUse", "session_id": "s", "agent_id": "a",
                "agent_type": "sample-context-scout", "cwd": str(root), "model": "sonnet",
                "run_id": "run-1",
                "tool_use_id": "call-1", "tool_name": "Grep", "tool_input": {"pattern": "x"},
            }
            with self.assertRaises(OSError):
                TOOL_LEDGER.record_event(payload, "claude", root)
            self.assertFalse((outside / "tools.jsonl").exists())

    def test_context_tool_ledger_rejects_symlinked_final_file(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_directory:
            root = Path(directory); outside = Path(outside_directory)
            session = root / ".harness/runs/context-tools/s"
            session.mkdir(parents=True)
            target = outside / "outside.jsonl"
            (session / "tools.jsonl").symlink_to(target)
            payload = {
                "hook_event_name": "PreToolUse", "run_id": "run-1", "session_id": "s",
                "agent_id": "a", "agent_type": "sample-context-scout", "cwd": str(root),
                "model": "sonnet", "tool_use_id": "call-1", "tool_name": "Grep",
                "tool_input": {"pattern": "x"},
            }
            with self.assertRaises(OSError):
                TOOL_LEDGER.record_event(payload, "claude", root)
            self.assertFalse(target.exists())

    def test_definition_ids_are_extracted_before_response_excerpt_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            full = "definitions: src/a.py:10 " + ("note " * 4000) + " src/b.py:20"
            common = {
                "run_id": "run-1", "session_id": "s", "agent_id": "a",
                "agent_type": "sample-context-scout", "cwd": str(root), "model": "sonnet",
                "tool_use_id": "graph", "tool_name": "mcp__codegraph__codegraph_explore",
                "tool_input": {"symbol": "x"},
            }
            TOOL_LEDGER.record_event({**common, "hook_event_name": "PreToolUse"}, "claude", root)
            TOOL_LEDGER.record_event(
                {**common, "hook_event_name": "PostToolUse", "tool_response": full}, "claude", root
            )
            records = [
                json.loads(line)
                for line in (root / ".harness/runs/context-tools/s/tools.jsonl").read_text().splitlines()
            ]
            post = next(item for item in records if item["event"] == "PostToolUse")
            self.assertNotIn("src/b.py:20", post["response_excerpt"])
            self.assertEqual(["src/a.py:10", "src/b.py:20"], post["definition_ids"])


class SerenaHealthTest(unittest.TestCase):
    def test_process_and_rss_limits_block(self):
        path = ROOT / ".harness/hooks/serena-health-gate.py"
        spec = importlib.util.spec_from_file_location("serena_health_gate", path)
        module = importlib.util.module_from_spec(spec); assert spec.loader is not None
        sys.modules[spec.name] = module; spec.loader.exec_module(module)
        processes = module.parse_process_table("101 1048576 python -m serena.server\n102 1048576 python -m serena.server\n103 1048576 python -m serena.server\n")
        self.assertFalse(module.evaluate(processes, 2, 4096)[0])
        self.assertFalse(module.evaluate(processes[:2], 2, 1024)[0])


if __name__ == "__main__":
    unittest.main()
