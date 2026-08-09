import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from engine.integration.council_pipeline import IntegrationError, integrate_events  # noqa: E402


def complex_events(commit_sha="a" * 40, manifest="delivery.json"):
    return [
        {"event": "ANCHOR", "payload": {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "prompt"}},
        {"event": "PHASE-PLAN", "payload": {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "items": ["i1"]}},
        {"event": "ITEM-PLAN", "payload": {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "item": "i1", "slice": "s1", "validation": ["test"]}},
        {"event": "SLICE", "payload": {"skill": "incremental-implementation", "slice": "s1", "changed_files": ["slice.txt"]}},
        {"event": "VALIDATION", "payload": {"status": "PASS", "commands": [{"command": "git diff --check", "exit_code": 0}], "checked_files": ["slice.txt"], "executor": "agent_swarm_ledger", "validated_at": "2026-01-01T00:00:00Z", "file_hashes": [{"path": "slice.txt", "sha256": "971c9401e58679c2670ab91b83db3846e47927d9e9c527ea952f29d11c7515f9"}]}},
        {"event": "LOCAL-COMMIT", "payload": {"sha": commit_sha, "files": ["slice.txt"]}},
        {"event": "QUALITY", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "99999999-9999-4999-8999-999999999999"}},
        {"event": "SIMPLIFICATION", "payload": {"status": "NAO_NECESSARIA"}},
        {"event": "ADVERSARIAL", "payload": {"status": "SATISFEITO", "reviewer_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}},
        {"event": "DELIVERY", "payload": {"status": "SATISFEITO", "manifest": manifest}},
    ]


def delivery_manifest(commit_sha, evidence="events.jsonl"):
    return {"commits": [commit_sha], "acceptance": [{"criterion": "done", "phase": "p1", "item": "i1", "slice": "s1", "commit": commit_sha, "files": ["slice.txt"], "commands": ["git diff --check"], "evidence": [evidence], "reviewer_ids": ["99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]}]}


class CouncilPipelineTest(unittest.TestCase):
    def test_integrates_exact_sequence_with_sha_and_reviewers(self):
        result = integrate_events(complex_events(), "b" * 40)
        self.assertEqual("DELIVERY", result["state"]["stage"])
        self.assertEqual("b" * 40, result["evidence"]["git_sha"])
        self.assertEqual(["99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"], result["evidence"]["reviewer_ids"])
        self.assertEqual(["a" * 40], result["evidence"]["local_commits"])

    def test_invalid_transition_reports_event_index(self):
        with self.assertRaisesRegex(IntegrationError, "event 2"):
            integrate_events(complex_events()[:1] + [complex_events()[3]], "b" * 40)

    def test_cli_materializes_state_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=folder, check=True)
            (folder / "slice.txt").write_text("slice\n")
            subprocess.run(["git", "add", "slice.txt"], cwd=folder, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "slice"], cwd=folder, check=True)
            commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder, text=True).strip()
            (folder / "delivery.json").write_text(json.dumps(delivery_manifest(commit_sha)))
            ledger = folder / "events.jsonl"
            ledger.write_text("".join(json.dumps(item) + "\n" for item in complex_events(commit_sha)), encoding="utf-8")
            output = folder / "proof"
            process = subprocess.run(
                [sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", commit_sha, "--repo-root", str(folder), "--output-dir", str(output)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            delivered = json.loads((output / "run-state.json").read_text())
            self.assertEqual("DELIVERY", delivered["stage"])
            self.assertTrue(delivered["delivery_verified"])

    def test_contract_entrypoints_pass(self):
        for command in ([sys.executable, "engine/contract/scripts/validate_contract.py"], [sys.executable, "scripts/validate_contract.py"]):
            process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertIn("council-contract-ok", process.stdout)

    def test_installed_ledger_rejects_invalid_state_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [sys.executable, str(ROOT / ".harness/lib/agent_swarm_ledger.py"), "transition", "--run-id", "negative-transition", "--event", "SLICE", "--payload-json", '{"skill":"incremental-implementation"}'],
                cwd=ROOT, env={**os.environ, "HARNESS_PROJECT_ROOT": directory}, capture_output=True, text=True,
            )
        self.assertNotEqual(0, process.returncode)
        self.assertIn("invalid Council transition", process.stderr)

    def test_installed_ledger_rejects_fabricated_local_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "slice.txt").write_text("slice\n", encoding="utf-8")
            env = {**os.environ, "HARNESS_PROJECT_ROOT": str(root)}
            for item in complex_events("a" * 40)[:6]:
                process = subprocess.run(
                    [sys.executable, str(ROOT / ".harness/lib/agent_swarm_ledger.py"), "transition", "--run-id", "fake-commit", "--event", item["event"], "--payload-json", json.dumps(item["payload"])],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                )
            self.assertNotEqual(0, process.returncode)
            self.assertIn("local commit does not exist", process.stderr)

    def test_transition_ledger_is_consumed_by_documented_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            env = {**os.environ, "HARNESS_PROJECT_ROOT": str(root)}

            def transition(item):
                process = subprocess.run(
                    [sys.executable, str(ROOT / ".harness/lib/agent_swarm_ledger.py"), "transition", "--run-id", "real-flow", "--event", item["event"], "--payload-json", json.dumps(item["payload"])],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                )
                self.assertEqual(0, process.returncode, process.stdout + process.stderr)

            events = complex_events()
            for item in events[:3]:
                transition(item)
            (root / "slice.txt").write_text("slice\n")
            transition(events[3])
            transition(events[4])
            subprocess.run(["git", "add", "slice.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "slice"], cwd=root, check=True)
            commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            transition({"event": "LOCAL-COMMIT", "payload": {"sha": commit_sha, "files": ["slice.txt"]}})
            for item in events[6:9]:
                transition(item)
            (root / "delivery.json").write_text(json.dumps(delivery_manifest(commit_sha, ".harness/runs/agent-swarm/real-flow/council-events.jsonl")))
            transition({"event": "DELIVERY", "payload": {"status": "SATISFEITO", "manifest": "delivery.json"}})
            ledger = root / ".harness/runs/agent-swarm/real-flow/council-events.jsonl"
            output = root / "proof"
            process = subprocess.run(
                [sys.executable, str(ROOT / "engine/integration/council_pipeline.py"), str(ledger), "--git-sha", commit_sha, "--repo-root", str(root), "--output-dir", str(output)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            delivered = json.loads((output / "run-state.json").read_text())
            self.assertEqual("DELIVERY", delivered["stage"])
            self.assertTrue(delivered["delivery_verified"])


if __name__ == "__main__":
    unittest.main()
