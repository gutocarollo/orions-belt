"""Provider-neutral knowledge graph contracts for Orion's Belt."""

from .provider import (
    GraphDelta,
    KnowledgeProvider,
    apply_delta,
    edge_id,
    git_changed_files,
    node_id,
    normalized_graph,
)
from .understand_adapter import UnderstandAnythingProvider

__all__ = [
    "GraphDelta",
    "KnowledgeProvider",
    "apply_delta",
    "edge_id",
    "git_changed_files",
    "node_id",
    "normalized_graph",
    "UnderstandAnythingProvider",
]
