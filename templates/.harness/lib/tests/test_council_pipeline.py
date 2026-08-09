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

TESTS = {"functional": ["F1"], "quality": ["Q1"], "regression": ["R1"]}
COMMANDS = [
    {"command": "test -s slice.txt", "exit_code": 0, "test_ids": ["F1"]},
    {"command": "git diff --check", "exit_code": 0, "test_ids": ["Q1"]},
    {"command": "test \"$(cat slice.txt)\" = slice", "exit_code": 0, "test_ids": ["R1"]},
]


def complex_events(commit_sha="a" * 40, manifest="delivery.json", base_sha="0" * 40):
    return [
        {"event": "ANCHOR", "payload": {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "prompt", "base_sha": base_sha, "worktree_baseline": []}},
        {"event": "PHASE-PLAN", "payload": {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "items": ["i1"], "objective": "deliver", "edge_id": "E1", "entry_node": "request", "exit_node": "done", "tests": TESTS}},
        {"event": "ITEM-PLAN", "payload": {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "item": "i1", "slice": "s1", "validation": ["test"], "objective": "deliver", "edge_id": "E1", "deliverable": "working result", "tests": TESTS}},
        {"event": "SLICE", "payload": {"skill": "incremental-implementation", "slice": "s1", "changed_files": ["slice.txt"]}},
        {"event": "VALIDATION", "payload": {"status": "PASS", "commands": COMMANDS, "checked_files": ["slice.txt"], "executor": "agent_swarm_ledger", "validated_at": "2026-01-01T00:00:00Z", "file_hashes": [{"path": "slice.txt", "sha256": "971c9401e58679c2670ab91b83db3846e47927d9e9c527ea952f29d11c7515f9"}], "tests": TESTS}},
        {"event": "LOCAL-COMMIT", "payload": {"sha": commit_sha, "files": ["slice.txt"]}},
        {"event": "QUALITY", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "99999999-9999-4999-8999-999999999999"}},
        {"event": "SIMPLIFICATION", "payload": {"status": "NAO_NECESSARIA", "reason": "already minimal"}},
        {"event": "ADVERSARIAL", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}},
        {"event": "DELIVERY", "payload": {"status": "SATISFEITO", "manifest": manifest}},
    ]


def delivery_manifest(commit_sha, evidence="events.jsonl"):
    return {"commits": [commit_sha], "execution_graph": "execution-graph.json", "code_necessity_report": "code-necessity.json", "acceptance": [{"criterion": "done", "phase": "p1", "item": "i1", "slice": "s1", "commit": commit_sha, "files": ["slice.txt"], "commands": [item["command"] for item in COMMANDS], "evidence": [evidence], "reviewer_ids": ["99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"], "edge_id": "E1", "test_ids": [test_id for ids in TESTS.values() for test_id in ids]}]}


def write_delivery_support(folder, base_sha, head_sha, evidence="events.jsonl", branch=False):
    graph = {"objective": "deliver", "start_node": "request", "goal_node": "done", "nodes": ["request", "done"], "edges": [{"edge_id": "E1", "from": "request", "to": "done", "critical": True, "phase": "p1", "item": "i1", "tests": TESTS, "evidence": [evidence]}]}
    if branch:
        graph["nodes"].append("alternate")
        graph["edges"].extend([
            {**graph["edges"][0], "edge_id": "E2", "to": "alternate"},
            {**graph["edges"][0], "edge_id": "E3", "from": "alternate"},
        ])
    (folder / "execution-graph.json").write_text(json.dumps(graph), encoding="utf-8")
    (folder / "code-necessity.json").write_text(json.dumps({"base_sha": base_sha, "head_sha": head_sha, "portions": []}), encoding="utf-8")


def commit_all(folder, message):
    subprocess.run(["git", "add", "-A"], cwd=folder, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=folder, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder, text=True).strip()


def commit_files(folder, message, *files):
    subprocess.run(["git", "add", *files], cwd=folder, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=folder, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder, text=True).strip()


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
            (folder / "baseline.txt").write_text("baseline\n")
            base_sha = commit_all(folder, "baseline")
            (folder / "slice.txt").write_text("slice\n")
            commit_sha = commit_all(folder, "slice")
            write_delivery_support(folder, base_sha, commit_sha)
            (folder / "delivery.json").write_text(json.dumps(delivery_manifest(commit_sha)))
            ledger = folder / "events.jsonl"
            ledger.write_text("".join(json.dumps(item) + "\n" for item in complex_events(commit_sha, base_sha=base_sha)), encoding="utf-8")
            final_sha = commit_all(folder, "delivery proof")
            output = folder / "proof"
            process = subprocess.run(
                [sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", final_sha, "--repo-root", str(folder), "--output-dir", str(output)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            delivered = json.loads((output / "run-state.json").read_text())
            self.assertEqual("DELIVERY", delivered["stage"])
            self.assertTrue(delivered["delivery_verified"])

            write_delivery_support(folder, base_sha, commit_sha, branch=True)
            branch_sha = commit_all(folder, "uncovered critical branch")
            branch_rejected = subprocess.run([sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", branch_sha, "--repo-root", str(folder), "--output-dir", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(2, branch_rejected.returncode)
            self.assertIn("every critical graph edge", branch_rejected.stderr)

            write_delivery_support(folder, base_sha, commit_sha)
            invalid = delivery_manifest(commit_sha)
            invalid["acceptance"][0]["test_ids"] = ["F1", "Q1", "wrong"]
            (folder / "delivery.json").write_text(json.dumps(invalid))
            invalid_sha = commit_all(folder, "invalid test evidence")
            rejected = subprocess.run([sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", invalid_sha, "--repo-root", str(folder), "--output-dir", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(2, rejected.returncode)
            self.assertIn("test_ids differ", rejected.stderr)

            (folder / "delivery.json").write_text(json.dumps(delivery_manifest(commit_sha)))
            clean_sha = commit_all(folder, "restore valid evidence")
            (folder / "slice.txt").write_text("uncommitted drift\n")
            dirty = subprocess.run([sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", clean_sha, "--repo-root", str(folder), "--output-dir", str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(2, dirty.returncode)
            self.assertIn("uncommitted drift", dirty.stderr)

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
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "baseline.txt").write_text("baseline\n", encoding="utf-8")
            base_sha = commit_all(root, "baseline")
            (root / "slice.txt").write_text("slice\n", encoding="utf-8")
            env = {**os.environ, "HARNESS_PROJECT_ROOT": str(root)}
            for item in complex_events("a" * 40, base_sha=base_sha)[:6]:
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
            (root / "baseline.txt").write_text("baseline\n", encoding="utf-8")
            base_sha = commit_all(root, "baseline")
            env = {**os.environ, "HARNESS_PROJECT_ROOT": str(root)}

            def transition(item):
                process = subprocess.run(
                    [sys.executable, str(ROOT / ".harness/lib/agent_swarm_ledger.py"), "transition", "--run-id", "real-flow", "--event", item["event"], "--payload-json", json.dumps(item["payload"])],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                )
                self.assertEqual(0, process.returncode, process.stdout + process.stderr)

            events = complex_events(base_sha=base_sha)
            for item in events[:3]:
                transition(item)
            (root / "slice.txt").write_text("slice\n")
            transition(events[3])
            transition(events[4])
            commit_sha = commit_files(root, "slice", "slice.txt")
            transition({"event": "LOCAL-COMMIT", "payload": {"sha": commit_sha, "files": ["slice.txt"]}})
            for item in events[6:9]:
                transition(item)
            write_delivery_support(root, base_sha, commit_sha, ".harness/runs/agent-swarm/real-flow/council-events.jsonl")
            (root / "delivery.json").write_text(json.dumps(delivery_manifest(commit_sha, ".harness/runs/agent-swarm/real-flow/council-events.jsonl")))
            final_sha = commit_files(root, "delivery proof", "delivery.json", "execution-graph.json", "code-necessity.json")
            transition({"event": "DELIVERY", "payload": {"status": "SATISFEITO", "manifest": "delivery.json"}})
            ledger = root / ".harness/runs/agent-swarm/real-flow/council-events.jsonl"
            output = root / "proof"
            process = subprocess.run(
                [sys.executable, str(ROOT / "engine/integration/council_pipeline.py"), str(ledger), "--git-sha", final_sha, "--repo-root", str(root), "--output-dir", str(output)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            delivered = json.loads((output / "run-state.json").read_text())
            self.assertEqual("DELIVERY", delivered["stage"])
            self.assertTrue(delivered["delivery_verified"])


if __name__ == "__main__":
    unittest.main()
