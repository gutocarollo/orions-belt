import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from engine.integration.council_pipeline import IntegrationError, _code_commits, _validate_graph_bindings, _validate_semantic_evidence, integrate_events  # noqa: E402

TESTS = {"functional": ["F1"], "quality": ["Q1"], "regression": ["R1"]}
COMMANDS = [
    {"command": "test -s slice.txt", "exit_code": 0, "test_ids": ["F1"]},
    {"command": "git diff --check", "exit_code": 0, "test_ids": ["Q1"]},
    {"command": "test \"$(cat slice.txt)\" = slice", "exit_code": 0, "test_ids": ["R1"]},
]


def graph_fixture(evidence="events.jsonl"):
    return {"objective": "deliver", "start_node": "request", "goal_node": "done", "nodes": ["request", "done"], "edges": [{"edge_id": "E1", "from": "request", "to": "done", "critical": True, "phase": "p1", "item": "i1", "tests": TESTS, "evidence": [evidence]}]}


def complex_events(commit_sha="a" * 40, manifest="delivery.json", base_sha="0" * 40, graph_evidence="events.jsonl"):
    return [
        {"event": "ANCHOR", "payload": {"mutation_mode": "WORKSPACE_WRITE", "anchor_source": "prompt", "base_sha": base_sha, "worktree_baseline": [], "execution_graph": graph_fixture(graph_evidence)}},
        {"event": "PHASE-PLAN", "payload": {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "items": ["i1"], "objective": "deliver", "edge_id": "E1", "entry_node": "request", "exit_node": "done", "tests": TESTS}},
        {"event": "ITEM-PLAN", "payload": {"skill": "planning-and-task-breakdown", "status": "PRONTO", "phase": "p1", "item": "i1", "slice": "s1", "validation": ["test"], "objective": "deliver", "edge_id": "E1", "deliverable": "working result", "tests": TESTS}},
        {"event": "SLICE", "payload": {"skill": "incremental-implementation", "slice": "s1", "changed_files": ["slice.txt"]}},
        {"event": "VALIDATION", "payload": {"status": "PASS", "commands": deepcopy(COMMANDS), "checked_files": ["slice.txt"], "executor": "agent_swarm_ledger", "validated_at": "2026-01-01T00:00:00Z", "file_hashes": [{"path": "slice.txt", "sha256": "971c9401e58679c2670ab91b83db3846e47927d9e9c527ea952f29d11c7515f9"}], "tests": TESTS}},
        {"event": "LOCAL-COMMIT", "payload": {"sha": commit_sha, "files": ["slice.txt"]}},
        {"event": "QUALITY", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "99999999-9999-4999-8999-999999999999"}},
        {"event": "SIMPLIFICATION", "payload": {"status": "NAO_NECESSARIA", "reason": "already minimal"}},
        {"event": "ADVERSARIAL", "payload": {"status": "SATISFEITO", "critical": 0, "required": 0, "reviewer_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}},
        {"event": "DELIVERY", "payload": {"status": "SATISFEITO", "manifest": manifest}},
    ]


def delivery_manifest(commit_sha, evidence="events.jsonl"):
    return {"commits": [commit_sha], "execution_graph": "execution-graph.json", "code_necessity_report": "code-necessity.json", "acceptance": [{"criterion": "done", "phase": "p1", "item": "i1", "slice": "s1", "commit": commit_sha, "files": ["slice.txt"], "commands": [item["command"] for item in COMMANDS], "evidence": [evidence], "reviewer_ids": ["99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"], "edge_id": "E1", "test_ids": [test_id for ids in TESTS.values() for test_id in ids]}]}


def write_delivery_support(folder, base_sha, head_sha, evidence="events.jsonl", branch=False, portions=None):
    graph = graph_fixture(evidence)
    if branch:
        graph["nodes"].append("alternate")
        graph["edges"].extend([
            {**graph["edges"][0], "edge_id": "E2", "to": "alternate"},
            {**graph["edges"][0], "edge_id": "E3", "from": "alternate"},
        ])
    (folder / "execution-graph.json").write_text(json.dumps(graph), encoding="utf-8")
    (folder / "code-necessity.json").write_text(json.dumps({"base_sha": base_sha, "head_sha": head_sha, "portions": portions or []}), encoding="utf-8")


def commit_all(folder, message):
    subprocess.run(["git", "add", "-A"], cwd=folder, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=folder, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder, text=True).strip()


def commit_files(folder, message, *files):
    subprocess.run(["git", "add", *files], cwd=folder, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=folder, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder, text=True).strip()


class CouncilPipelineTest(unittest.TestCase):
    def test_review_edge_requires_terminal_satisfied_verdicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review = root / "adversarial.md"
            review.write_text("ADVERSARIAL-VERIFICATION: CORRIGIR\n", encoding="utf-8")
            graph = {
                "nodes": ["review", "done"],
                "edges": [{
                    "edge_id": "E5", "from": "review", "to": "done",
                    "critical": True, "phase": "review", "item": "close reviews",
                    "tests": TESTS, "evidence": [review.name],
                }],
            }
            with self.assertRaisesRegex(IntegrationError, "terminal review evidence"):
                _validate_semantic_evidence(root, graph, [])
            quality = root / "quality.md"
            simplification = root / "simplification.md"
            adversarial = root / "adversarial-final.md"
            quality.write_text("QUALITY-REVIEW: SATISFEITO\n", encoding="utf-8")
            simplification.write_text("SIMPLIFICATION: NAO_NECESSARIA\n", encoding="utf-8")
            adversarial.write_text("ADVERSARIAL-VERIFICATION: SATISFEITO\n", encoding="utf-8")
            graph["edges"][0]["evidence"].extend([quality.name, simplification.name, adversarial.name])
            _validate_semantic_evidence(root, graph, [])

    def test_real_impact_marker_must_resolve_in_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_text("actual marker\n", encoding="utf-8")
            impact = {
                "evidence_status": "REAL",
                "evidence": {"path": source.name, "line": 1, "contains": "fabricated marker"},
            }
            events = [{"event": "QUALITY", "payload": {"findings": [{"impact": impact}]}}]
            with self.assertRaisesRegex(IntegrationError, "impact evidence marker"):
                _validate_semantic_evidence(root, {"edges": []}, events)

    def test_graph_binding_rejects_fabricated_phase_nodes(self):
        events = complex_events()
        graph = {
            "objective": "deliver",
            "start_node": "request",
            "goal_node": "done",
            "nodes": ["request", "done"],
            "edges": [{
                "edge_id": "E1", "from": "request", "to": "done",
                "critical": True, "phase": "p1", "item": "i1",
                "tests": TESTS, "evidence": ["events.jsonl"],
            }],
        }
        events[1]["payload"]["entry_node"] = "fabricated-entry"
        events[1]["payload"]["exit_node"] = "fabricated-exit"
        with self.assertRaisesRegex(IntegrationError, "PHASE-PLAN.*graph edge"):
            _validate_graph_bindings(graph, events)
        events = complex_events()
        self.assertEqual({"E1": graph["edges"][0]}, _validate_graph_bindings(graph, events))

    def test_direct_read_only_transition_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".harness/lib/agent_swarm_ledger.py"),
                    "transition",
                    "--run-id",
                    "read-only-bypass",
                    "--event",
                    "ANCHOR",
                    "--payload-json",
                    json.dumps({"mutation_mode": "READ_ONLY", "anchor_source": "inline"}),
                ],
                cwd=ROOT,
                env={**os.environ, "HARNESS_PROJECT_ROOT": str(root)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, process.returncode)
            self.assertIn("read-only Council runs are inline", process.stderr)
            self.assertFalse((root / ".harness").exists())

    def test_planning_review_persists_deferred_finding_in_active_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / ".harness/runs/planning-defer"
            run.mkdir(parents=True)
            state = root / ".harness/runs/agent-swarm/planning-defer/council-state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"mutation_mode": "WORKSPACE_WRITE"}), encoding="utf-8")
            (root / ".harness/runs/ACTIVE").write_text("planning-defer\n", encoding="utf-8")
            run_md = run / "RUN.md"
            run_md.write_text(
                "# RUN\n\n## Pendências não bloqueantes\n- Nenhuma no início do run.\n\n## Journal\n",
                encoding="utf-8",
            )
            impact = {
                "id": "D-PLAN",
                "evidence_status": "UNVERIFIED",
                "evidence": {"path": "RUN.md", "line": 1, "contains": "RUN"},
                "objective_impact": 1,
                "journey_reachability": 1,
                "acceptance_impact": 1,
                "irreversibility": 0,
                "dependency_urgency": 0,
                "on_critical_path": False,
                "affects_current_phase": False,
                "validated_workaround": True,
                "graph_nodes": ["later"],
            }
            review = {
                "deferred_findings": [
                    {"impact": impact, "reason": "safe to defer", "review_after": "next phase"}
                ]
            }
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".harness/lib/agent_swarm_ledger.py"),
                    "append",
                    "--run-id",
                    "planning-defer",
                    "--loop",
                    "planning",
                    "--round",
                    "1",
                    "--event",
                    "review",
                    "--status",
                    "SATISFEITO",
                    "--payload-json",
                    json.dumps(review),
                ],
                cwd=ROOT,
                env={**os.environ, "HARNESS_PROJECT_ROOT": str(root)},
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertEqual(1, run_md.read_text(encoding="utf-8").count("`D-PLAN`"))

    def test_append_rejects_read_only_run_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / ".harness/runs/read-only-append"
            run.mkdir(parents=True)
            run_md = run / "RUN.md"
            run_md.write_text("# RUN\n\n## Pendências não bloqueantes\n", encoding="utf-8")
            state = root / ".harness/runs/agent-swarm/read-only-append/council-state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"mutation_mode": "READ_ONLY"}), encoding="utf-8")
            (root / ".harness/runs/ACTIVE").write_text("read-only-append\n", encoding="utf-8")
            before = run_md.read_bytes()
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / ".harness/lib/agent_swarm_ledger.py"),
                    "append",
                    "--run-id",
                    "read-only-append",
                    "--loop",
                    "planning",
                    "--round",
                    "1",
                    "--event",
                    "review",
                    "--status",
                    "SATISFEITO",
                    "--payload-json",
                    json.dumps({"deferred_findings": []}),
                ],
                cwd=ROOT,
                env={**os.environ, "HARNESS_PROJECT_ROOT": str(root)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, process.returncode)
            self.assertIn("WORKSPACE_WRITE", process.stderr)
            self.assertEqual(before, run_md.read_bytes())
            self.assertFalse((state.parent / "loop.jsonl").exists())

    def test_integrates_exact_sequence_with_sha_and_reviewers(self):
        result = integrate_events(complex_events(), "b" * 40)
        self.assertEqual("DELIVERY", result["state"]["stage"])
        self.assertEqual("b" * 40, result["evidence"]["git_sha"])
        self.assertEqual(["99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"], result["evidence"]["reviewer_ids"])
        self.assertEqual(["a" * 40], result["evidence"]["local_commits"])

    def test_invalid_transition_reports_event_index(self):
        with self.assertRaisesRegex(IntegrationError, "event 2"):
            integrate_events(complex_events()[:1] + [complex_events()[3]], "b" * 40)

    def test_delivery_rejects_code_commit_missing_from_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=folder, check=True)
            (folder / "baseline.txt").write_text("baseline\n")
            base_sha = commit_all(folder, "baseline")
            (folder / "slice.txt").write_text("slice\n")
            slice_sha = commit_all(folder, "recorded slice")
            (folder / "unrecorded.py").write_text("value = 1\n")
            unrecorded_sha = commit_all(folder, "unrecorded code")
            write_delivery_support(folder, base_sha, unrecorded_sha, portions=[{
                "path": "unrecorded.py", "start_line": 1, "end_line": 1,
                "purpose": "demonstrate unrecorded code", "objective": "reject code absent from the ledger", "inputs": ["request"], "outputs": ["value"],
                "evidence": [{"path": "unrecorded.py", "line": 1, "contains": "value = 1", "command": "test -s unrecorded.py"}],
                "simpler_alternative": "omit it", "necessity": "test fixture",
            }])
            (folder / "delivery.json").write_text(json.dumps(delivery_manifest(slice_sha)))
            ledger = folder / "events.jsonl"
            ledger.write_text("".join(json.dumps(item) + "\n" for item in complex_events(slice_sha, base_sha=base_sha)), encoding="utf-8")
            final_sha = commit_all(folder, "delivery proof")
            process = subprocess.run(
                [sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", final_sha, "--repo-root", str(folder), "--output-dir", str(folder / "proof")],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(2, process.returncode)
            self.assertIn("unrecorded code commit", process.stderr)

    def test_code_commit_detection_includes_merge_resolutions(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=folder, check=True)
            (folder / "value.py").write_text("value = 0\n")
            base_sha = commit_all(folder, "baseline")
            main_branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=folder, text=True).strip()
            subprocess.run(["git", "checkout", "-q", "-b", "side"], cwd=folder, check=True)
            (folder / "value.py").write_text("value = 1\n")
            commit_all(folder, "side code")
            subprocess.run(["git", "checkout", "-q", main_branch], cwd=folder, check=True)
            (folder / "value.py").write_text("value = 2\n")
            commit_all(folder, "main code")
            conflict = subprocess.run(["git", "merge", "side", "-m", "merge resolution"], cwd=folder, capture_output=True, text=True)
            self.assertNotEqual(0, conflict.returncode)
            (folder / "value.py").write_text("value = 3\n")
            merge_sha = commit_all(folder, "merge resolution")
            self.assertIn(merge_sha, _code_commits(folder, base_sha, merge_sha))

    def test_code_commit_detection_includes_jinja_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=folder, check=True)
            (folder / "baseline.txt").write_text("baseline\n")
            base_sha = commit_all(folder, "baseline")
            (folder / "SKILL.md.jinja").write_text("generated contract\n")
            template_sha = commit_all(folder, "template source")
            self.assertEqual([template_sha], _code_commits(folder, base_sha, template_sha))

    def test_delivery_reexecutes_declared_validation_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=folder, check=True)
            (folder / "baseline.txt").write_text("baseline\n")
            base_sha = commit_all(folder, "baseline")
            (folder / "slice.txt").write_text("slice\n")
            slice_sha = commit_all(folder, "slice")
            write_delivery_support(folder, base_sha, slice_sha)
            events = complex_events(slice_sha, base_sha=base_sha)
            events[4]["payload"]["commands"][0]["command"] = "command-that-does-not-exist"
            manifest = delivery_manifest(slice_sha)
            manifest["acceptance"][0]["commands"][0] = "command-that-does-not-exist"
            (folder / "delivery.json").write_text(json.dumps(manifest))
            ledger = folder / "events.jsonl"
            ledger.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
            final_sha = commit_all(folder, "fabricated validation proof")
            process = subprocess.run(
                [sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", final_sha, "--repo-root", str(folder), "--output-dir", str(folder / "proof")],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(2, process.returncode)
            self.assertIn("validation command failed during delivery replay", process.stderr)

    def test_delivery_rejects_validation_replay_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=folder, check=True)
            (folder / "baseline.txt").write_text("baseline\n")
            base_sha = commit_all(folder, "baseline")
            (folder / "slice.txt").write_text("slice\n")
            slice_sha = commit_all(folder, "slice")
            write_delivery_support(folder, base_sha, slice_sha)
            events = complex_events(slice_sha, base_sha=base_sha)
            events[4]["payload"]["commands"][0]["command"] = "touch replay-side-effect"
            manifest = delivery_manifest(slice_sha)
            manifest["acceptance"][0]["commands"][0] = "touch replay-side-effect"
            (folder / "delivery.json").write_text(json.dumps(manifest))
            ledger = folder / "events.jsonl"
            ledger.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
            final_sha = commit_all(folder, "side-effecting validation proof")
            process = subprocess.run(
                [sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", final_sha, "--repo-root", str(folder), "--output-dir", str(folder / "proof")],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(2, process.returncode)
            self.assertIn("validation replay mutated the repository", process.stderr)
            self.assertTrue((folder / "replay-side-effect").exists())

    def test_delivery_rejects_missing_execution_graph_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=folder, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=folder, check=True)
            (folder / "baseline.txt").write_text("baseline\n")
            base_sha = commit_all(folder, "baseline")
            (folder / "slice.txt").write_text("slice\n")
            slice_sha = commit_all(folder, "slice")
            write_delivery_support(folder, base_sha, slice_sha, evidence="missing-proof.json")
            (folder / "delivery.json").write_text(json.dumps(delivery_manifest(slice_sha)))
            ledger = folder / "events.jsonl"
            ledger.write_text("".join(json.dumps(item) + "\n" for item in complex_events(slice_sha, base_sha=base_sha, graph_evidence="missing-proof.json")), encoding="utf-8")
            final_sha = commit_all(folder, "missing graph evidence")
            process = subprocess.run(
                [sys.executable, "engine/integration/council_pipeline.py", str(ledger), "--git-sha", final_sha, "--repo-root", str(folder), "--output-dir", str(folder / "proof")],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(2, process.returncode)
            self.assertIn("execution graph evidence is missing", process.stderr)

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
            self.assertIn("differs from the Council ANCHOR", branch_rejected.stderr)

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

            events = complex_events(base_sha=base_sha, graph_evidence=".harness/runs/agent-swarm/real-flow/council-events.jsonl")
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
