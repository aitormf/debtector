"""
Data models for Debtector.

Design inspired by real graph stores: every symbol is a NODE with a unique
qualified_name, and relations (imports, inheritance, calls) are directed
EDGES between nodes.

The qualified_name is the "full address" of each symbol:
    file.py                             → The file itself
    file.py::MyClass                    → A class
    file.py::MyClass.my_method          → A method
    file.py::my_function                → A top-level function
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ──────────────────────────────────────────────
# Node and edge kinds
# ──────────────────────────────────────────────


class NodeKind(StrEnum):
    """Node kinds in the code graph."""

    FILE = "File"
    CLASS = "Class"
    FUNCTION = "Function"
    METHOD = "Method"


class EdgeKind(StrEnum):
    """Kinds of relations between nodes."""

    CONTAINS = "CONTAINS"  # file contains class/function
    HAS_METHOD = "HAS_METHOD"  # class contains method
    IMPORTS_FROM = "IMPORTS_FROM"  # file imports from module
    CALLS = "CALLS"  # function/method calls another
    INHERITS = "INHERITS"  # class inherits from another
    DEPENDS_ON = "DEPENDS_ON"  # generic dependency
    COVERS = "COVERS"  # test function/method exercises a production symbol
    USES_TYPE = "USES_TYPE"  # function/method references a type in its signature


# ──────────────────────────────────────────────
# Nodes
# ──────────────────────────────────────────────


@dataclass
class NodeInfo:
    """
    Node information to insert into the graph.

    This is what a parser produces. The GraphStore turns it into a
    persistent record with an ID and timestamps.

    Args:
        kind: Node kind (File, Class, Function, Method)
        name: Short name ("get_user", "UserService")
        qualified_name: Unique full name ("src/app.py::UserService.get_user")
        file_path: Path of the file where it lives
        line_start: Start line
        line_end: End line
        language: Programming language
        parent_name: Name of the parent class (for methods)
        signature: Full signature ("def get_user(self, id: int) -> User")
        docstring: Documentation of the symbol
        decorators: List of decorators
        extra: Additional free-form data
    """

    kind: str
    name: str
    qualified_name: str
    file_path: str
    line_start: int = 0
    line_end: int = 0
    language: str = ""
    parent_name: str | None = None
    signature: str | None = None
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class EdgeInfo:
    """
    Edge information to insert into the graph.

    Connects two nodes by their qualified_names.

    Args:
        kind: Relation kind (CONTAINS, IMPORTS_FROM, CALLS, etc.)
        source: qualified_name of the source node
        target: qualified_name of the target node
        file_path: File where the relation is established
        line: Line where it occurs (e.g. the line of the import or call)
        extra: Additional data
    """

    kind: str
    source: str
    target: str
    file_path: str
    line: int = 0
    extra: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# Query results (what the GraphStore returns)
# ──────────────────────────────────────────────


@dataclass
class GraphNode:
    """Node stored in the graph (with ID and store metadata)."""

    id: int
    kind: str
    name: str
    qualified_name: str
    file_path: str
    line_start: int
    line_end: int
    language: str
    parent_name: str | None
    signature: str | None
    docstring: str | None
    file_hash: str | None
    extra: dict


@dataclass
class GraphEdge:
    """Edge stored in the graph."""

    id: int
    kind: str
    source_qualified: str
    target_qualified: str
    file_path: str
    line: int
    extra: dict


@dataclass
class GraphStats:
    """Aggregated graph statistics."""

    total_nodes: int
    total_edges: int
    nodes_by_kind: dict[str, int]
    edges_by_kind: dict[str, int]
    languages: list[str]
    files_count: int


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def make_qualified_name(
    file_path: str,
    name: str,
    kind: str,
    parent_name: str | None = None,
) -> str:
    """
    Build the qualified_name of a symbol.

    Examples:
        make_qualified_name("src/app.py", "app.py", "File")
            → "src/app.py"
        make_qualified_name("src/app.py", "UserService", "Class")
            → "src/app.py::UserService"
        make_qualified_name("src/app.py", "get_user", "Method", "UserService")
            → "src/app.py::UserService.get_user"
        make_qualified_name("src/app.py", "create_app", "Function")
            → "src/app.py::create_app"
    """
    if kind == NodeKind.FILE:
        return file_path
    if parent_name:
        return f"{file_path}::{parent_name}.{name}"
    return f"{file_path}::{name}"


def node_to_dict(n: GraphNode) -> dict:
    """Convert a GraphNode to a dictionary (for serialization/API)."""
    return {
        "id": n.id,
        "kind": n.kind,
        "name": n.name,
        "qualified_name": n.qualified_name,
        "file_path": n.file_path,
        "line_start": n.line_start,
        "line_end": n.line_end,
        "language": n.language,
        "parent_name": n.parent_name,
        "signature": n.signature,
    }


def edge_to_dict(e: GraphEdge) -> dict:
    """Convert a GraphEdge to a dictionary."""
    return {
        "id": e.id,
        "kind": e.kind,
        "source": e.source_qualified,
        "target": e.target_qualified,
        "file_path": e.file_path,
        "line": e.line,
    }
