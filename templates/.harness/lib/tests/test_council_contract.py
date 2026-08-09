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

from council_contract import ContractError, SCHEMA_NAMES, validate_contract  # noqa: E402
from council_hooks import git_guard, post_tool_guard, pre_tool_guard, stop_guard  # noqa: E402
from council_session import finish_session, start_session  # noqa: E402
from sync_council import council_paths, sync_council  # noqa: E402

SKILL_CONTRACTS = {
    "adversarial-review": ("CRITICAL_BLOCK", "HIGH_FIX_NOW", "DEFER_RUN"),
    "clarification-plan": ("CRITICAL_BLOCK", "HIGH_FIX_NOW", "DEFER_RUN"),
    "planning-and-task-breakdown": ("directed execution graph", "functional", "quality", "regression"),
    "incremental-implementation": ("governing execution skill", "LOCAL commit", "Push"),
    "test-driven-development": ("stable IDs", "functional", "quality", "regression"),
    "interview-me": ("Ask one question at a time", "DEFER_RUN"),
    "code-review-and-quality": ("individually assessed findings", "DEFER_RUN"),
    "code-simplification": ("every added code line", "inputs", "outputs"),
    "prova-de-conclusao": ("functional", "quality", "regression"),
    "verify": ("functional", "quality", "regression"),
}


class CouncilContractTest(unittest.TestCase):
    def test_installed_contract_is_valid(self):
        report = validate_contract(ROOT)
        self.assertEqual("PASS", report["status"])
        self.assertEqual(len(SCHEMA_NAMES), report["schemas"])

    def test_skill_surfaces_are_identical_and_checkable(self):
        source, target = council_paths(ROOT)
        self.assertEqual(source.read_bytes(), target.read_bytes())
        self.assertFalse(sync_council(ROOT, check=True))

    def test_operating_skills_render_on_both_runtimes_with_role_contracts(self):
        for skill, markers in SKILL_CONTRACTS.items():
            claude = ROOT / ".claude/skills" / skill / "SKILL.md"
            agents = ROOT / ".agents/skills" / skill / "SKILL.md"
            with self.subTest(skill=skill):
                self.assertEqual(claude.read_bytes(), agents.read_bytes())
                text = claude.read_text(encoding="utf-8")
                for marker in markers:
                    self.assertIn(marker, text)
        council = council_paths(ROOT)[0].read_text(encoding="utf-8")
        for marker in ("interview-me", "clarification-plan", "test-driven-development", "prova-de-conclusao", "code-necessity"):
            self.assertIn(marker, council)

    def test_semantic_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = council_paths(root)
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_text("canonical", encoding="utf-8")
            target.write_text("drift", encoding="utf-8")
            self.assertTrue(sync_council(root, check=True))
            sync_council(root, check=False)
            self.assertEqual("canonical", target.read_text(encoding="utf-8"))

    def test_single_runtime_surface_is_not_reported_as_drift(self):
        for runtime in (".claude", ".agents"):
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / runtime / "skills" / "sample-delivery-council" / "SKILL.md"
                path.parent.mkdir(parents=True)
                path.write_text("single runtime", encoding="utf-8")
                self.assertFalse(sync_council(root, check=True))
                self.assertIn("sample-delivery-council", str(council_paths(root)[0]))

    def test_every_schema_is_valid_json_with_required_fields(self):
        for name in SCHEMA_NAMES:
            data = json.loads((ROOT / ".harness" / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual("object", data["type"])
            self.assertTrue(data["required"])
            self.assertFalse(data["additionalProperties"])

    def test_codex_registers_council_pre_post_and_stop_gates(self):
        hooks = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
        for event, suffix in (("PreToolUse", " pre"), ("PostToolUse", " post"), ("Stop", " stop")):
            commands = [hook.get("command", "") for group in hooks[event] for hook in group.get("hooks", [])]
            self.assertTrue(any("council-gate.py" in command and command.endswith(suffix) for command in commands), event)

    def test_pre_tool_blocks_edit_without_ready_item(self):
        decision = pre_tool_guard({"tool_name": "Edit", "state": {"stage": "PHASE-PLAN"}})
        self.assertFalse(decision["allow"])
        self.assertTrue(pre_tool_guard({"tool_name": "Edit", "state": {"stage": "ITEM-PLAN"}})["allow"])
        self.assertFalse(pre_tool_guard({"tool_name": "MultiEdit", "state": {"stage": "PHASE-PLAN"}})["allow"])

    def test_post_tool_requires_validation_after_edit(self):
        decision = post_tool_guard({"tool_name": "Write", "success": True})
        self.assertEqual("VALIDATION", decision["required_next"])
        self.assertEqual("VALIDATION", post_tool_guard({"tool_name": "MultiEdit", "success": True})["required_next"])

    def test_stop_requires_delivery_and_evidence(self):
        self.assertFalse(stop_guard({"state": {"stage": "ADVERSARIAL"}})["allow"])
        self.assertFalse(stop_guard({"state": {"stage": "DELIVERY", "history": [{"event": "DELIVERY"}]}})["allow"])
        self.assertTrue(stop_guard({"state": {"stage": "DELIVERY", "delivery_verified": True, "history": [{"event": "DELIVERY"}]}})["allow"])

    def test_git_guard_allows_local_commit_but_blocks_unauthorized_remote(self):
        self.assertTrue(git_guard({"action": "local-commit"})["allow"])
        self.assertFalse(git_guard({"action": "push"})["allow"])
        self.assertTrue(git_guard({"action": "merge-main", "authority": {"remote_authorized": True, "authorized_by": "user", "authorization_evidence": "prompt"}})["allow"])

    def test_council_git_executes_remote_action_only_with_authority(self):
        tool = ROOT / ".harness/lib/council_git.py"
        blocked = subprocess.run([sys.executable, str(tool), "merge-main", "--", sys.executable, "-c", "raise SystemExit(0)"], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(0, blocked.returncode)
        with tempfile.TemporaryDirectory() as directory:
            authority = Path(directory) / "authority.json"
            authority.write_text(json.dumps({"remote_authorized": True, "authorized_by": "user", "authorization_evidence": "prompt"}))
            allowed = subprocess.run([sys.executable, str(tool), "merge-main", "--authorization", str(authority), "--", sys.executable, "-c", "raise SystemExit(0)"], cwd=ROOT, capture_output=True, text=True)
            bypass = subprocess.run([sys.executable, str(tool), "push", "--authorization", str(authority), "--", "git", "push", "--no-verify"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        self.assertNotEqual(0, bypass.returncode)
        self.assertIn("forbids --no-verify", bypass.stderr)

    def test_missing_required_semantic_marker_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = council_paths(root)
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_text("incomplete", encoding="utf-8")
            target.write_text("incomplete", encoding="utf-8")
            with self.assertRaises(ContractError):
                validate_contract(root)

    def test_session_lifecycle_activates_state_and_installs_real_push_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            state_path = start_session(root, "lifecycle", "inline")
            pointer = root / ".harness/council-active"
            self.assertEqual(state_path, Path(pointer.read_text().strip()))
            self.assertTrue((root / ".git/hooks/pre-push").is_file())
            self.assertTrue((root / ".git/hooks/pre-push").stat().st_mode & 0o100)
            self.assertEqual("lifecycle", (root / ".harness/runs/ACTIVE").read_text().strip())
            self.assertIn("## Pendências não bloqueantes", (root / ".harness/runs/lifecycle/RUN.md").read_text())
            with self.assertRaisesRegex(RuntimeError, "DELIVERY"):
                finish_session(root)

    def test_finished_session_clears_active_run_but_preserves_run_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            state_path = start_session(root, "finished", "inline")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["stage"] = "DELIVERY"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            finish_session(root)
            self.assertFalse((root / ".harness/runs/ACTIVE").exists())
            self.assertTrue((root / ".harness/runs/finished/RUN.md").is_file())

    def test_read_only_session_is_inline_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*") if ".git" not in path.parts)
            state_path = start_session(root, "read-only", "inline", "READ_ONLY")
            after = sorted(str(path.relative_to(root)) for path in root.rglob("*") if ".git" not in path.parts)
            self.assertIsNone(state_path)
            self.assertEqual(before, after)
            self.assertFalse((root / ".git/hooks/pre-push").exists())

    def test_active_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pointer = root / ".harness/council-active"
            pointer.parent.mkdir(parents=True)
            missing = root / "missing-state.json"
            pointer.write_text(str(missing), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(ROOT / ".harness/hooks/council-gate.py"), "pre"],
                cwd=root, env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
                input=json.dumps({"tool_name": "Edit"}), capture_output=True, text=True,
            )
            self.assertEqual(2, process.returncode)
            self.assertIn("active Council state", process.stderr)

    def test_active_state_that_differs_from_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            state_path = start_session(root, "tampered", "inline")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["stage"] = "DELIVERY"
            state["delivery_verified"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(ROOT / ".harness/hooks/council-gate.py"), "stop"],
                cwd=root, env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)}, input="{}", capture_output=True, text=True,
            )
            self.assertEqual(2, process.returncode)
            self.assertIn("differs from event-ledger replay", process.stderr)

    def test_corrupt_active_state_blocks_real_git_push(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo, remote = base / "repo", base / "remote.git"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "init", "--bare", "-q", str(remote)], cwd=base, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "file.txt").write_text("x\n")
            subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
            hook = repo / ".git/hooks/pre-push"
            hook.write_bytes((ROOT / ".githooks/pre-push").read_bytes())
            hook.chmod(0o755)
            pointer = repo / ".harness/council-active"
            pointer.parent.mkdir(parents=True)
            pointer.write_text(str(repo / "missing-state.json") + "\n")
            process = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=repo, capture_output=True, text=True)
            self.assertNotEqual(0, process.returncode)
            self.assertIn("corrupt", process.stderr.lower())


if __name__ == "__main__":
    unittest.main()
