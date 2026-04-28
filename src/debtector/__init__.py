"""Debtector — Grafo de código sobre SQLite para reducir consumo de tokens en IA."""

from debtector.graph_store import GraphStore
from debtector.indexer import Indexer
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

__version__ = "0.4.0"

__all__ = [
    "GraphStore",
    "Indexer",
    "NodeInfo",
    "EdgeInfo",
    "NodeKind",
    "EdgeKind",
]
