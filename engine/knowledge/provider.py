"""Contract helpers for external knowledge-graph providers.

This module intentionally does not parse source code or infer semantic relationships. Providers
such as Understand Anything own extraction; Orion owns stable interchange, validation and parity.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


JsonObject = dict[str, Any]


def _stable_id(namespace: str, *parts: str) -> str:
    canonical = "\x1f".join((namespace, *parts)).encode("utf-8")
    return f"{namespace}:{hashlib.sha256(canonical).hexdigest()[:24]}"


def node_id(provider: str, kind: str, key: str) -> str:
    """Return a content-independent ID for one provider entity."""

    return _stable_id("node", provider, kind, key)


def edge_id(provider: str, edge_type: str, source: str, target: str) -> str:
    """Return a stable ID for one typed, directed relationship."""

    return _stable_id("edge", provider, edge_type, source, target)


@dataclass(frozen=True)
class GraphDelta:
    """Provider output for one incremental refresh."""

    upsert_nodes: tuple[JsonObject, ...] = field(default_factory=tuple)
    upsert_edges: tuple[JsonObject, ...] = field(default_factory=tuple)
    tombstones: tuple[JsonObject, ...] = field(default_factory=tuple)


class KnowledgeProvider(Protocol):
    """Adapter boundary implemented by Understand Anything or another extractor."""

    name: str
    version: str

    def build_full(self, project_root: Path, git_commit: str) -> JsonObject:
        """Build a complete graph for ``git_commit``."""

    def build_incremental(
        self,
        project_root: Path,
        previous_graph: Mapping[str, Any],
        changed_files: Sequence[str],
        git_commit: str,
    ) -> GraphDelta:
        """Return only upserts and tombstones caused by ``changed_files``."""


def _index_by_id(items: Sequence[Mapping[str, Any]]) -> dict[str, JsonObject]:
    return {str(item["id"]): dict(item) for item in items}


def apply_delta(previous: Mapping[str, Any], delta: GraphDelta, git_commit: str) -> JsonObject:
    """Apply an incremental result without mutating the provider's prior snapshot."""

    nodes = _index_by_id(previous.get("nodes", []))
    edges = _index_by_id(previous.get("edges", []))
    tombstones = _index_by_id(previous.get("tombstones", []))

    deleted_edge_ids = {
        str(item["entity_id"])
        for item in delta.tombstones
        if item.get("entity_type") == "edge"
    }
    for tombstone in delta.tombstones:
        entity_id = str(tombstone["entity_id"])
        entity_type = tombstone["entity_type"]
        if entity_type == "node":
            incident_edges = {
                key
                for key, edge in edges.items()
                if edge.get("source") == entity_id or edge.get("target") == entity_id
            }
            missing_edge_tombstones = incident_edges - deleted_edge_ids
            if missing_edge_tombstones:
                raise ValueError(
                    "node deletion requires tombstones for incident edges: "
                    + ", ".join(sorted(missing_edge_tombstones))
                )
            nodes.pop(entity_id, None)
            edges = {
                key: edge
                for key, edge in edges.items()
                if edge.get("source") != entity_id and edge.get("target") != entity_id
            }
        elif entity_type == "edge":
            edges.pop(entity_id, None)
        else:
            raise ValueError(f"unsupported tombstone entity_type: {entity_type}")
        tombstones[str(tombstone["id"])] = dict(tombstone)

    for node in delta.upsert_nodes:
        nodes[str(node["id"])] = dict(node)
    for edge in delta.upsert_edges:
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError(f"edge {edge['id']} references a missing node")
        edges[str(edge["id"])] = dict(edge)

    metadata = dict(previous.get("metadata", {}))
    metadata["git_commit"] = git_commit
    return {
        "schema_version": previous.get("schema_version", "1.0.0"),
        "metadata": metadata,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "tombstones": list(tombstones.values()),
    }


def normalized_graph(graph: Mapping[str, Any], *, include_tombstones: bool = False) -> str:
    """Canonical representation used to compare incremental and clean builds."""

    normalized = {
        "nodes": sorted(graph.get("nodes", []), key=lambda item: item["id"]),
        "edges": sorted(graph.get("edges", []), key=lambda item: item["id"]),
    }
    if include_tombstones:
        normalized["tombstones"] = sorted(
            graph.get("tombstones", []), key=lambda item: item["id"]
        )
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def git_changed_files(
    repo_root: Path, project_root: Path, base: str, head: str = "HEAD"
) -> list[str]:
    """Return Git changes relative to ``project_root``, never repo-prefixed paths."""

    repo = repo_root.resolve()
    project = project_root.resolve()
    try:
        relative_root = project.relative_to(repo)
    except ValueError as exc:
        raise ValueError("project_root must be inside repo_root") from exc

    relative_arg = "." if relative_root == Path(".") else relative_root.as_posix()
    command = [
        "git",
        "-C",
        str(repo),
        "diff",
        f"--relative={relative_arg}",
        "--name-only",
        f"{base}..{head}",
        "--",
        relative_arg,
    ]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    paths = [line for line in result.stdout.splitlines() if line]
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"git returned an unsafe relative path: {path}")
        if relative_root != Path(".") and path.startswith(f"{relative_arg}/"):
            raise ValueError(f"git returned a repo-relative path instead of project-relative: {path}")
    return paths
