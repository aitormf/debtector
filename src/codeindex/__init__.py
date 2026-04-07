"""CodeIndex — Grafo de código sobre SQLite para reducir consumo de tokens en IA."""

from codeindex.graph_store import GraphStore
from codeindex.indexer import Indexer
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

__version__ = "0.2.0"

__all__ = [
    "GraphStore",
    "Indexer",
    "NodeInfo",
    "EdgeInfo",
    "NodeKind",
    "EdgeKind",
]
