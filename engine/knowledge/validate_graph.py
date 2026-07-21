#!/usr/bin/env python3
"""Fail-closed semantic validator for provider-neutral knowledge graph JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from .provider import edge_id as stable_edge_id
    from .provider import node_id as stable_node_id
except ImportError:  # direct script execution
    from provider import edge_id as stable_edge_id
    from provider import node_id as stable_node_id

NODE_ID = re.compile(r"^node:[a-f0-9]{24}$")
EDGE_ID = re.compile(r"^edge:[a-f0-9]{24}$")
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
EDGE_CLASSES = {"deterministic", "compiler_resolved", "llm_inferred"}


def _valid_provenance(value: object) -> bool:
    return isinstance(value, dict) and all(value.get(field) for field in ("method", "source", "recorded_at"))


def validate(graph: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"schema_version", "metadata", "nodes", "edges", "tombstones"}
    missing = required - set(graph)
    if missing:
        errors.append(f"missing top-level fields: {', '.join(sorted(missing))}")
        return errors
    if graph["schema_version"] != "1.0.0":
        errors.append("schema_version must be 1.0.0")
    metadata = graph.get("metadata")
    if not isinstance(metadata, dict) or not all(
        metadata.get(field) for field in ("provider", "provider_version", "git_commit", "project_root")
    ):
        errors.append("metadata must identify provider, version, commit and project_root")

    nodes: dict[str, Mapping[str, Any]] = {}
    provider = str(metadata.get("provider", "")) if isinstance(metadata, dict) else ""
    for index, node in enumerate(graph.get("nodes", [])):
        node_id_value = node.get("id", "") if isinstance(node, dict) else ""
        if not NODE_ID.fullmatch(str(node_id_value)):
            errors.append(f"nodes[{index}].id is invalid")
            continue
        if node_id_value in nodes:
            errors.append(f"duplicate node id: {node_id_value}")
        nodes[node_id_value] = node
        for field in ("kind", "key", "locator", "provenance"):
            if not node.get(field):
                errors.append(f"node {node_id_value} missing {field}")
        if not SHA256.fullmatch(str(node.get("content_hash", ""))):
            errors.append(f"node {node_id_value} has invalid content_hash")
        if node.get("kind") and node.get("key") and node_id_value != stable_node_id(provider, str(node["kind"]), str(node["key"])):
            errors.append(f"node {node_id_value} is not the stable ID for provider/kind/key")
        if not _valid_provenance(node.get("provenance")):
            errors.append(f"node {node_id_value} has incomplete provenance")

    edge_ids: set[str] = set()
    for index, edge in enumerate(graph.get("edges", [])):
        edge_id_value = edge.get("id", "") if isinstance(edge, dict) else ""
        if not EDGE_ID.fullmatch(str(edge_id_value)):
            errors.append(f"edges[{index}].id is invalid")
            continue
        if edge_id_value in edge_ids:
            errors.append(f"duplicate edge id: {edge_id_value}")
        edge_ids.add(edge_id_value)
        if edge.get("type") and edge.get("source") and edge.get("target") and edge_id_value != stable_edge_id(
            provider, str(edge["type"]), str(edge["source"]), str(edge["target"])
        ):
            errors.append(f"edge {edge_id_value} is not the stable ID for provider/type/endpoints")
        if edge.get("source") not in nodes or edge.get("target") not in nodes:
            errors.append(f"edge {edge_id_value} references a missing node")
        edge_class = edge.get("edge_class")
        if edge_class not in EDGE_CLASSES:
            errors.append(f"edge {edge_id_value} has invalid edge_class")
        if edge_class == "llm_inferred":
            confidence = edge.get("confidence")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
                errors.append(f"edge {edge_id_value} requires confidence in [0,1]")
        if not edge.get("type") or not _valid_provenance(edge.get("provenance")):
            errors.append(f"edge {edge_id_value} missing type or provenance")

    tombstone_ids: set[str] = set()
    live_ids = set(nodes) | edge_ids
    for index, tombstone in enumerate(graph.get("tombstones", [])):
        tombstone_id = tombstone.get("id", "") if isinstance(tombstone, dict) else ""
        if not re.fullmatch(r"tombstone:[a-f0-9]{24}", str(tombstone_id)):
            errors.append(f"tombstones[{index}].id is invalid")
        if tombstone_id in tombstone_ids:
            errors.append(f"duplicate tombstone id: {tombstone_id}")
        tombstone_ids.add(tombstone_id)
        if tombstone.get("entity_id") in live_ids:
            errors.append(f"tombstoned entity is still live: {tombstone.get('entity_id')}")
        if tombstone.get("entity_type") not in {"node", "edge"}:
            errors.append(f"tombstone {tombstone_id} has invalid entity_type")
        if not tombstone.get("deleted_at") or not _valid_provenance(tombstone.get("provenance")):
            errors.append(f"tombstone {tombstone_id} lacks deletion provenance")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("graph", type=Path)
    args = parser.parse_args()
    try:
        graph = json.loads(args.graph.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"knowledge-graph: cannot read graph: {exc}", file=sys.stderr)
        return 2
    errors = validate(graph)
    if errors:
        for error in errors:
            print(f"knowledge-graph: {error}", file=sys.stderr)
        return 1
    print("knowledge-graph: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
