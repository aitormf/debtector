"""Tests for LCOM4 (Lack of Cohesion of Methods, v4) computation."""

from __future__ import annotations

from debtector.audit.lcom4 import compute_lcom4
from debtector.graph_store import GraphStore
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


def _store_class(
    store: GraphStore,
    file_path: str,
    class_name: str,
    methods: list[str],
    calls: list[tuple[str, str]],
) -> str:
    """Persist a class with given methods and intra-class CALLS edges.

    Args:
        store: Target GraphStore.
        file_path: Relative path of the synthetic file.
        class_name: Class identifier.
        methods: Short names of the class methods.
        calls: Pairs ``(caller, callee)`` of method short names.

    Returns:
        The qualified name of the persisted class.
    """
    class_qname = f"{file_path}::{class_name}"
    nodes: list[NodeInfo] = [
        NodeInfo(
            kind=NodeKind.FILE,
            name=file_path.split("/")[-1],
            qualified_name=file_path,
            file_path=file_path,
            language="python",
        ),
        NodeInfo(
            kind=NodeKind.CLASS,
            name=class_name,
            qualified_name=class_qname,
            file_path=file_path,
            language="python",
        ),
    ]
    edges: list[EdgeInfo] = [
        EdgeInfo(
            kind=EdgeKind.CONTAINS,
            source=file_path,
            target=class_qname,
            file_path=file_path,
            line=1,
        ),
    ]
    for method in methods:
        method_qname = f"{class_qname}.{method}"
        nodes.append(
            NodeInfo(
                kind=NodeKind.METHOD,
                name=method,
                qualified_name=method_qname,
                file_path=file_path,
                parent_name=class_name,
                language="python",
            )
        )
        edges.append(
            EdgeInfo(
                kind=EdgeKind.HAS_METHOD,
                source=class_qname,
                target=method_qname,
                file_path=file_path,
                line=1,
            )
        )
    for caller, callee in calls:
        edges.append(
            EdgeInfo(
                kind=EdgeKind.CALLS,
                source=f"{class_qname}.{caller}",
                target=f"{class_qname}.{callee}",
                file_path=file_path,
                line=1,
            )
        )
    store.store_file(file_path, nodes, edges)
    return class_qname


def test_lcom4_cohesive_class_returns_one(tmp_db: GraphStore) -> None:
    """3 methods chained A->B->C form a single connected component."""
    class_qname = _store_class(
        tmp_db,
        "src/cohesive.py",
        "Cohesive",
        methods=["a", "b", "c"],
        calls=[("a", "b"), ("b", "c")],
    )
    assert compute_lcom4(tmp_db, class_qname) == 1


def test_lcom4_disjoint_methods_returns_two(tmp_db: GraphStore) -> None:
    """4 methods with A->B and C->D form two disjoint components."""
    class_qname = _store_class(
        tmp_db,
        "src/split.py",
        "Splittable",
        methods=["a", "b", "c", "d"],
        calls=[("a", "b"), ("c", "d")],
    )
    assert compute_lcom4(tmp_db, class_qname) == 2
