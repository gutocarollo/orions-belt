from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from engine.knowledge.provider import (
    GraphDelta,
    apply_delta,
    edge_id,
    git_changed_files,
    node_id,
    normalized_graph,
)
from engine.knowledge.validate_graph import validate
from engine.knowledge.understand_adapter import UnderstandAnythingProvider


STAMP = "2026-07-21T00:00:00Z"


def provenance(source: str = "fixture") -> dict[str, str]:
    return {"method": "fixture", "source": source, "recorded_at": STAMP}


def node(key: str, content: str) -> dict[str, object]:
    return {
        "id": node_id("fixture", "file", key),
        "kind": "file",
        "key": key,
        "locator": key,
        "content_hash": f"sha256:{hashlib.sha256(content.encode()).hexdigest()}",
        "provenance": provenance(key),
    }


def graph(nodes: list[dict[str, object]], edges: list[dict[str, object]], commit: str) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "metadata": {
            "provider": "fixture",
            "provider_version": "1",
            "git_commit": commit,
            "project_root": "apps",
        },
        "nodes": nodes,
        "edges": edges,
        "tombstones": [],
    }


class KnowledgeContractTests(unittest.TestCase):
    def test_stable_ids_do_not_change_with_content(self) -> None:
        self.assertEqual(node("a.py", "v1")["id"], node("a.py", "v2")["id"])

    def test_incremental_equals_clean_fixture(self) -> None:
        old_a, old_b = node("a.py", "v1"), node("b.py", "v1")
        old_edge = {
            "id": edge_id("fixture", "imports", str(old_a["id"]), str(old_b["id"])),
            "source": old_a["id"],
            "target": old_b["id"],
            "type": "imports",
            "edge_class": "compiler_resolved",
            "provenance": provenance("compiler"),
        }
        initial = graph([old_a, old_b], [old_edge], "old")
        new_a, new_c = node("a.py", "v2"), node("c.py", "v1")
        new_edge = {
            "id": edge_id("fixture", "imports", str(new_a["id"]), str(new_c["id"])),
            "source": new_a["id"],
            "target": new_c["id"],
            "type": "imports",
            "edge_class": "compiler_resolved",
            "provenance": provenance("compiler"),
        }
        tombstones = (
            {
                "id": "tombstone:" + hashlib.sha256(str(old_b["id"]).encode()).hexdigest()[:24],
                "entity_id": old_b["id"],
                "entity_type": "node",
                "deleted_at": STAMP,
                "provenance": provenance("git-delete"),
            },
            {
                "id": "tombstone:" + hashlib.sha256(str(old_edge["id"]).encode()).hexdigest()[:24],
                "entity_id": old_edge["id"],
                "entity_type": "edge",
                "deleted_at": STAMP,
                "provenance": provenance("git-delete"),
            },
        )
        incremental = apply_delta(
            initial,
            GraphDelta(upsert_nodes=(new_a, new_c), upsert_edges=(new_edge,), tombstones=tombstones),
            "new",
        )
        clean = graph([new_a, new_c], [new_edge], "new")
        self.assertEqual(normalized_graph(incremental), normalized_graph(clean))
        self.assertEqual(validate(incremental), [])

    def test_llm_edge_requires_confidence(self) -> None:
        a, b = node("a.py", "a"), node("b.py", "b")
        inferred = {
            "id": edge_id("fixture", "related", str(a["id"]), str(b["id"])),
            "source": a["id"],
            "target": b["id"],
            "type": "related",
            "edge_class": "llm_inferred",
            "provenance": provenance("model"),
        }
        self.assertTrue(any("requires confidence" in error for error in validate(graph([a, b], [inferred], "x"))))

    def test_node_deletion_requires_incident_edge_tombstones(self) -> None:
        a, b = node("a.py", "a"), node("b.py", "b")
        relation = {
            "id": edge_id("fixture", "imports", str(a["id"]), str(b["id"])),
            "source": a["id"],
            "target": b["id"],
            "type": "imports",
            "edge_class": "compiler_resolved",
            "provenance": provenance(),
        }
        node_tombstone = {
            "id": "tombstone:" + hashlib.sha256(str(b["id"]).encode()).hexdigest()[:24],
            "entity_id": b["id"],
            "entity_type": "node",
            "deleted_at": STAMP,
            "provenance": provenance(),
        }
        with self.assertRaisesRegex(ValueError, "incident edges"):
            apply_delta(graph([a, b], [relation], "old"), GraphDelta(tombstones=(node_tombstone,)), "new")

    def test_changed_files_are_project_relative(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "apps").mkdir()
            (repo / "apps" / "a.py").write_text("old", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "old"], check=True)
            base = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, text=True, capture_output=True
            ).stdout.strip()
            (repo / "apps" / "a.py").write_text("new", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "new"], check=True)
            self.assertEqual(git_changed_files(repo, repo / "apps", base), ["a.py"])

    def test_understand_adapter_full_equals_incremental(self) -> None:
        fixtures = Path(__file__).parent / "fixtures" / "understand"
        old = UnderstandAnythingProvider(fixtures / "v1").build_full(Path("apps"), "commit-v1")
        provider = UnderstandAnythingProvider(fixtures / "v2")
        clean = provider.build_full(Path("apps"), "commit-v2")
        delta = provider.build_incremental(Path("apps"), old, ["web/main.ts", "web/config.ts"], "commit-v2")
        incremental = apply_delta(old, delta, "commit-v2")
        self.assertEqual(normalized_graph(incremental), normalized_graph(clean))
        self.assertEqual(validate(clean), [])
        self.assertTrue(delta.tombstones)
        self.assertTrue(all(edge["edge_class"] == "llm_inferred" for edge in clean["edges"]))
        self.assertTrue(all("confidence" in edge for edge in clean["edges"]))

    def test_understand_adapter_reads_current_knowledge_graph_json_filename(self) -> None:
        # Regression: the adapter used to look only for assembled-graph.json/graph.json,
        # which are Understand Anything's OLD output names — it failed on every real graph
        # (current output filename is knowledge-graph.json), verified against a real 7,962
        # node / 19,459 edge graph on 2026-07-21 before the fix.
        fixtures = Path(__file__).parent / "fixtures" / "understand"
        graph = UnderstandAnythingProvider(fixtures / "v3-current-name").build_full(Path("apps"), "commit-v3")
        self.assertEqual(validate(graph), [])
        self.assertTrue(graph["nodes"])


if __name__ == "__main__":
    unittest.main()
