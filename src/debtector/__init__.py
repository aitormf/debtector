"""Debtector — coupling guardrail for CI and PR reviews, built on a code graph in SQLite."""

from debtector.graph_store import GraphStore
from debtector.indexer import Indexer
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

__version__ = "0.33.0"

__all__ = [
    "GraphStore",
    "Indexer",
    "NodeInfo",
    "EdgeInfo",
    "NodeKind",
    "EdgeKind",
]
