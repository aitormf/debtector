"""Tests for cycle detection in metrics.py."""

from __future__ import annotations

from debtector.graph_store import GraphStore
from debtector.metrics import find_cycles
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _file(path: str) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
        language="python",
    )


def _edge(kind: str, source: str, target: str) -> EdgeInfo:
    return EdgeInfo(kind=kind, source=source, target=target, file_path=source, line=1)


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────


class TestFindCycles:
    """Unit tests for find_cycles()."""

    def test_empty_store_returns_empty(self, tmp_db: GraphStore) -> None:
        """An empty index returns no cycles."""
        assert find_cycles(tmp_db) == []

    def test_no_cycles_returns_empty(self, tmp_db: GraphStore) -> None:
        """A DAG with no cycles returns an empty list."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/a.py", "src/b.py")],
        )
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [])

        assert find_cycles(tmp_db) == []

    def test_direct_cycle_imports_from(self, tmp_db: GraphStore) -> None:
        """a→b and b→a via IMPORTS_FROM forms a cycle."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/a.py", "src/b.py")],
        )
        tmp_db.store_file(
            "src/b.py",
            [_file("src/b.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/b.py", "src/a.py")],
        )

        cycles = find_cycles(tmp_db)
        assert len(cycles) >= 1
        # Each cycle is a list of node qualified_names forming the loop
        cycle_sets = [frozenset(c) for c in cycles]
        assert any({"src/a.py", "src/b.py"}.issubset(s) for s in cycle_sets)

    def test_three_node_cycle(self, tmp_db: GraphStore) -> None:
        """a→b→c→a forms a cycle of length 3."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/a.py", "src/b.py")],
        )
        tmp_db.store_file(
            "src/b.py",
            [_file("src/b.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/b.py", "src/c.py")],
        )
        tmp_db.store_file(
            "src/c.py",
            [_file("src/c.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/c.py", "src/a.py")],
        )

        cycles = find_cycles(tmp_db)
        assert len(cycles) >= 1
        cycle_sets = [frozenset(c) for c in cycles]
        assert any({"src/a.py", "src/b.py", "src/c.py"}.issubset(s) for s in cycle_sets)

    def test_cycle_via_calls_edges(self, tmp_db: GraphStore) -> None:
        """Cycles via CALLS edges are also detected."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_edge(EdgeKind.CALLS, "src/a.py", "src/b.py")],
        )
        tmp_db.store_file(
            "src/b.py",
            [_file("src/b.py")],
            [_edge(EdgeKind.CALLS, "src/b.py", "src/a.py")],
        )

        cycles = find_cycles(tmp_db)
        assert len(cycles) >= 1

    def test_isolated_nodes_no_cycle(self, tmp_db: GraphStore) -> None:
        """Files with no edges produce no cycles."""
        for p in ["src/x.py", "src/y.py", "src/z.py"]:
            tmp_db.store_file(p, [_file(p)], [])

        assert find_cycles(tmp_db) == []

    def test_external_import_target_ignored(self, tmp_db: GraphStore) -> None:
        """Imports to external packages (no File node) never form cycles."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/a.py", "flask")],
        )

        assert find_cycles(tmp_db) == []

    def test_returns_list_of_lists(self, tmp_db: GraphStore) -> None:
        """Return type is list[list[str]] even when cycles exist."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/a.py", "src/b.py")],
        )
        tmp_db.store_file(
            "src/b.py",
            [_file("src/b.py")],
            [_edge(EdgeKind.IMPORTS_FROM, "src/b.py", "src/a.py")],
        )

        cycles = find_cycles(tmp_db)
        assert isinstance(cycles, list)
        for cycle in cycles:
            assert isinstance(cycle, list)
            assert all(isinstance(n, str) for n in cycle)
