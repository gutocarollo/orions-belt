"""Concrete adapter for Understand Anything JSON artifacts.

Understand Anything remains responsible for code analysis. This adapter only reads its meta and
assembled graph, maps upstream identifiers into Orion's provider-neutral contract, and computes
snapshot deltas. Unknown extraction methods are conservatively classified as LLM-inferred.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .provider import GraphDelta, edge_id, node_id


class UnderstandAnythingProvider:
    name = "understand-anything"

    def __init__(self, artifact_dir: Path | None = None) -> None:
        self.artifact_dir = artifact_dir
        self.version = "unknown"

    def _root(self, project_root: Path) -> Path:
        return (self.artifact_dir or project_root / ".understand-anything").resolve()

    @staticmethod
    def _read_object(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read Understand artifact {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Understand artifact must be a JSON object: {path}")
        return payload

    def _load(self, project_root: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
        root = self._root(project_root)
        meta = self._read_object(root / "meta.json")
        candidates = (root / "assembled-graph.json", root / "graph.json")
        graph_path = next((path for path in candidates if path.is_file()), None)
        if graph_path is None:
            raise ValueError(f"Understand graph not found under {root}")
        graph = self._read_object(graph_path)
        if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
            raise ValueError("Understand graph requires nodes and edges arrays")
        self.version = str(meta.get("version") or graph.get("version") or "unknown")
        return meta, graph, graph_path

    @staticmethod
    def _canonical_hash(value: Mapping[str, Any]) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _edge_class(edge: Mapping[str, Any]) -> str:
        explicit = edge.get("edgeClass") or edge.get("edge_class")
        if explicit in {"deterministic", "compiler_resolved", "llm_inferred"}:
            return str(explicit)
        method = str(edge.get("extractionMethod") or edge.get("method") or "").lower()
        if method in {"ast", "parser", "deterministic"}:
            return "deterministic"
        if method in {"compiler", "language-server", "lsp", "type-checker"}:
            return "compiler_resolved"
        return "llm_inferred"

    def build_full(self, project_root: Path, git_commit: str) -> dict[str, Any]:
        meta, upstream, graph_path = self._load(project_root)
        recorded_at = str(meta.get("lastAnalyzedAt") or "1970-01-01T00:00:00Z")
        source_name = graph_path.name
        upstream_to_stable: dict[str, str] = {}
        nodes: list[dict[str, Any]] = []
        for raw in upstream["nodes"]:
            if not isinstance(raw, dict) or not raw.get("id") or not raw.get("type"):
                raise ValueError("Understand node requires id and type")
            upstream_id = str(raw["id"])
            stable = node_id(self.name, str(raw["type"]), upstream_id)
            if upstream_id in upstream_to_stable:
                raise ValueError(f"duplicate Understand node id: {upstream_id}")
            upstream_to_stable[upstream_id] = stable
            nodes.append(
                {
                    "id": stable,
                    "kind": str(raw["type"]),
                    "key": upstream_id,
                    "locator": str(raw.get("filePath") or upstream_id),
                    "content_hash": self._canonical_hash(raw),
                    "provenance": {
                        "method": "understand-anything",
                        "source": f"{source_name}#node:{upstream_id}",
                        "recorded_at": recorded_at,
                    },
                }
            )

        edges: list[dict[str, Any]] = []
        seen_edge_ids: set[str] = set()
        for index, raw in enumerate(upstream["edges"]):
            if not isinstance(raw, dict) or not all(raw.get(field) for field in ("source", "target", "type")):
                raise ValueError(f"Understand edge {index} requires source, target and type")
            upstream_source, upstream_target = str(raw["source"]), str(raw["target"])
            if upstream_source not in upstream_to_stable or upstream_target not in upstream_to_stable:
                raise ValueError(f"Understand edge {index} references an unknown node")
            source, target = upstream_to_stable[upstream_source], upstream_to_stable[upstream_target]
            stable = edge_id(self.name, str(raw["type"]), source, target)
            if stable in seen_edge_ids:
                raise ValueError(f"duplicate normalized Understand edge: {stable}")
            seen_edge_ids.add(stable)
            edge_class = self._edge_class(raw)
            edge: dict[str, Any] = {
                "id": stable,
                "source": source,
                "target": target,
                "type": str(raw["type"]),
                "edge_class": edge_class,
                "provenance": {
                    "method": f"understand-anything:{edge_class}",
                    "source": f"{source_name}#edge:{index}",
                    "recorded_at": recorded_at,
                },
            }
            if edge_class == "llm_inferred":
                weight = raw.get("weight", 0.5)
                edge["confidence"] = max(0.0, min(1.0, float(weight)))
            edges.append(edge)

        return {
            "schema_version": "1.0.0",
            "metadata": {
                "provider": self.name,
                "provider_version": self.version,
                "git_commit": git_commit,
                "project_root": str(project_root),
            },
            "nodes": nodes,
            "edges": edges,
            "tombstones": [],
        }

    @staticmethod
    def _tombstone(entity_id: str, entity_type: str, commit: str, recorded_at: str) -> dict[str, Any]:
        digest = hashlib.sha256(f"{entity_type}\x1f{entity_id}\x1f{commit}".encode()).hexdigest()[:24]
        return {
            "id": f"tombstone:{digest}",
            "entity_id": entity_id,
            "entity_type": entity_type,
            "deleted_at": recorded_at,
            "provenance": {
                "method": "understand-anything:snapshot-diff",
                "source": "meta.json",
                "recorded_at": recorded_at,
            },
        }

    def build_incremental(
        self,
        project_root: Path,
        previous_graph: Mapping[str, Any],
        changed_files: Sequence[str],
        git_commit: str,
    ) -> GraphDelta:
        if not changed_files:
            return GraphDelta()
        current = self.build_full(project_root, git_commit)
        old_nodes = {item["id"]: item for item in previous_graph.get("nodes", [])}
        old_edges = {item["id"]: item for item in previous_graph.get("edges", [])}
        new_nodes = {item["id"]: item for item in current["nodes"]}
        new_edges = {item["id"]: item for item in current["edges"]}
        recorded_at = next(
            (item["provenance"]["recorded_at"] for item in current["nodes"]),
            "1970-01-01T00:00:00Z",
        )
        tombstones = [
            self._tombstone(entity_id, "edge", git_commit, recorded_at)
            for entity_id in sorted(set(old_edges) - set(new_edges))
        ]
        tombstones.extend(
            self._tombstone(entity_id, "node", git_commit, recorded_at)
            for entity_id in sorted(set(old_nodes) - set(new_nodes))
        )
        return GraphDelta(
            upsert_nodes=tuple(
                new_nodes[key] for key in sorted(new_nodes) if old_nodes.get(key) != new_nodes[key]
            ),
            upsert_edges=tuple(
                new_edges[key] for key in sorted(new_edges) if old_edges.get(key) != new_edges[key]
            ),
            tombstones=tuple(tombstones),
        )
