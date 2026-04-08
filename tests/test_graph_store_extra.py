"""Additional tests for GraphStore covering low-coverage paths."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
from codeindex.graph_store import GraphStore
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers / extra fixtures
# ──────────────────────────────────────────────


def _make_nodes(file_path: str, language: str = "python") -> list[NodeInfo]:
    """Return a minimal set of nodes for *file_path*.

    Args:
        file_path: Relative file path used for qualified names.
        language: Language tag for the nodes.

    Returns:
        List of :class:`NodeInfo` objects (File + Class + Method).
    """
    return [
        NodeInfo(
            kind=NodeKind.FILE,
            name=file_path.split("/")[-1],
            qualified_name=file_path,
            file_path=file_path,
            line_start=1,
            line_end=50,
            language=language,
        ),
        NodeInfo(
            kind=NodeKind.CLASS,
            name="Service",
            qualified_name=f"{file_path}::Service",
            file_path=file_path,
            line_start=3,
            line_end=40,
            language=language,
        ),
        NodeInfo(
            kind=NodeKind.METHOD,
            name="execute",
            qualified_name=f"{file_path}::Service.execute",
            file_path=file_path,
            line_start=5,
            line_end=20,
            language=language,
            parent_name="Service",
        ),
    ]


def _make_calls_nodes(caller_file: str, callee_file: str) -> tuple[list[NodeInfo], list[EdgeInfo]]:
    """Return nodes and a CALLS edge from *caller* to *callee*.

    Args:
        caller_file: File path for the calling function.
        callee_file: File path for the called function.

    Returns:
        Tuple of (nodes, edges) ready for :meth:`GraphStore.store_file`.
    """
    caller_qn = f"{caller_file}::caller_fn"
    callee_qn = f"{callee_file}::callee_fn"

    nodes = [
        NodeInfo(
            kind=NodeKind.FILE,
            name=caller_file,
            qualified_name=caller_file,
            file_path=caller_file,
            line_start=1,
            line_end=10,
            language="python",
        ),
        NodeInfo(
            kind=NodeKind.FUNCTION,
            name="caller_fn",
            qualified_name=caller_qn,
            file_path=caller_file,
            line_start=2,
            line_end=8,
            language="python",
        ),
    ]
    edges = [
        EdgeInfo(
            kind=EdgeKind.CALLS,
            source=caller_qn,
            target=callee_qn,
            file_path=caller_file,
            line=5,
        )
    ]
    return nodes, edges


# ──────────────────────────────────────────────
# callers_of
# ──────────────────────────────────────────────


class TestCallersOf:
    """Tests for GraphStore.callers_of()."""

    def test_returns_caller_nodes(self, tmp_db: GraphStore) -> None:
        """Returns the nodes that CALL the given symbol."""
        callee_nodes = [
            NodeInfo(
                kind=NodeKind.FILE,
                name="callee.py",
                qualified_name="callee.py",
                file_path="callee.py",
                line_start=1,
                line_end=5,
                language="python",
            ),
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name="callee_fn",
                qualified_name="callee.py::callee_fn",
                file_path="callee.py",
                line_start=2,
                line_end=4,
                language="python",
            ),
        ]
        tmp_db.store_file("callee.py", callee_nodes, [], "hc")

        caller_nodes, caller_edges = _make_calls_nodes("caller.py", "callee.py")
        tmp_db.store_file("caller.py", caller_nodes, caller_edges, "hr")

        callers = tmp_db.callers_of("callee.py::callee_fn")
        caller_names = [n.name for n in callers]
        assert "caller_fn" in caller_names

    def test_empty_when_no_callers(self, tmp_db: GraphStore) -> None:
        """Returns an empty list when no CALLS edge targets the symbol."""
        nodes = _make_nodes("alone.py")
        tmp_db.store_file("alone.py", nodes, [], "ha")
        callers = tmp_db.callers_of("alone.py::Service")
        assert callers == []


# ──────────────────────────────────────────────
# callees_of
# ──────────────────────────────────────────────


class TestCalleesOf:
    """Tests for GraphStore.callees_of()."""

    def test_returns_callee_nodes(self, tmp_db: GraphStore) -> None:
        """Returns the nodes called BY the given symbol."""
        callee_nodes = [
            NodeInfo(
                kind=NodeKind.FILE,
                name="util.py",
                qualified_name="util.py",
                file_path="util.py",
                line_start=1,
                line_end=5,
                language="python",
            ),
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name="callee_fn",
                qualified_name="util.py::callee_fn",
                file_path="util.py",
                line_start=2,
                line_end=4,
                language="python",
            ),
        ]
        tmp_db.store_file("util.py", callee_nodes, [], "hu")

        caller_nodes, caller_edges = _make_calls_nodes("main.py", "util.py")
        tmp_db.store_file("main.py", caller_nodes, caller_edges, "hm")

        callees = tmp_db.callees_of("main.py::caller_fn")
        callee_names = [n.name for n in callees]
        assert "callee_fn" in callee_names

    def test_empty_when_no_callees(self, tmp_db: GraphStore) -> None:
        """Returns empty list when the node has no outbound CALLS edges."""
        nodes = _make_nodes("isolated.py")
        tmp_db.store_file("isolated.py", nodes, [], "hi")
        callees = tmp_db.callees_of("isolated.py::Service")
        assert callees == []


# ──────────────────────────────────────────────
# get_dependency_chain
# ──────────────────────────────────────────────


class TestGetDependencyChain:
    """Tests for GraphStore.get_dependency_chain()."""

    def test_chains_found(self, tmp_db: GraphStore) -> None:
        """Returns at least one chain when outbound edges exist."""
        from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

        nodes_a = [
            NodeInfo(
                kind=NodeKind.FILE,
                name="a.py",
                qualified_name="a.py",
                file_path="a.py",
                line_start=1,
                line_end=5,
                language="python",
            ),
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name="fn_a",
                qualified_name="a.py::fn_a",
                file_path="a.py",
                line_start=2,
                line_end=4,
                language="python",
            ),
        ]
        nodes_b = [
            NodeInfo(
                kind=NodeKind.FILE,
                name="b.py",
                qualified_name="b.py",
                file_path="b.py",
                line_start=1,
                line_end=5,
                language="python",
            ),
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name="fn_b",
                qualified_name="b.py::fn_b",
                file_path="b.py",
                line_start=2,
                line_end=4,
                language="python",
            ),
        ]
        edge = EdgeInfo(
            kind=EdgeKind.CALLS,
            source="a.py::fn_a",
            target="b.py::fn_b",
            file_path="a.py",
            line=3,
        )
        tmp_db.store_file("a.py", nodes_a, [edge], "ha")
        tmp_db.store_file("b.py", nodes_b, [], "hb")

        chains = tmp_db.get_dependency_chain("a.py::fn_a")
        assert len(chains) >= 1
        # Each chain is a list of qualified names
        assert any("b.py::fn_b" in chain for chain in chains)

    def test_nonexistent_node_returns_empty(self, tmp_db: GraphStore) -> None:
        """Returns an empty list when the starting node is not in the graph."""
        chains = tmp_db.get_dependency_chain("does_not_exist::fn")
        assert chains == []

    def test_respects_max_depth(self, tmp_db: GraphStore) -> None:
        """Does not traverse deeper than max_depth hops."""
        # Single hop — max_depth=0 should return no chains
        nodes_a = [
            NodeInfo(
                kind=NodeKind.FILE,
                name="a.py",
                qualified_name="a.py",
                file_path="a.py",
                line_start=1,
                line_end=5,
                language="python",
            ),
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name="fn_a",
                qualified_name="a.py::fn_a",
                file_path="a.py",
                line_start=2,
                line_end=4,
                language="python",
            ),
        ]
        nodes_b = [
            NodeInfo(
                kind=NodeKind.FILE,
                name="b.py",
                qualified_name="b.py",
                file_path="b.py",
                line_start=1,
                line_end=5,
                language="python",
            ),
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name="fn_b",
                qualified_name="b.py::fn_b",
                file_path="b.py",
                line_start=2,
                line_end=4,
                language="python",
            ),
        ]
        edge = EdgeInfo(
            kind=EdgeKind.CALLS,
            source="a.py::fn_a",
            target="b.py::fn_b",
            file_path="a.py",
            line=3,
        )
        tmp_db.store_file("a.py", nodes_a, [edge], "ha2")
        tmp_db.store_file("b.py", nodes_b, [], "hb2")

        chains = tmp_db.get_dependency_chain("a.py::fn_a", max_depth=0)
        assert chains == []


# ──────────────────────────────────────────────
# _search_like fallback + empty FTS expression
# ──────────────────────────────────────────────


class TestSearchFallback:
    """Tests for the _search_like fallback (lines 407-408, 463-478)."""

    def test_falls_back_when_fts_raises(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        """search_nodes falls back to LIKE search when FTS5 raises OperationalError."""
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        with patch.object(
            tmp_db, "_search_fts", side_effect=sqlite3.OperationalError("fts unavailable")
        ):
            results = tmp_db.search_nodes("MyService")
        names = [n.name for n in results]
        assert "MyService" in names

    def test_search_like_with_kind_filter(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        """_search_like respects the kind filter parameter."""
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        results = tmp_db._search_like(["MyService"], "Class", 10)
        assert all(n.kind == NodeKind.CLASS for n in results)

    def test_search_like_no_kind_filter(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        """_search_like returns results across all kinds when kind=None."""
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        results = tmp_db._search_like(["app"], None, 50)
        assert len(results) > 0

    def test_search_like_no_match(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        """_search_like returns empty list when no nodes match."""
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        results = tmp_db._search_like(["zzznomatch"], None, 10)
        assert results == []


class TestSearchFtsEmptyExpr:
    """Tests for the empty fts_expr early return in _search_fts (line 428)."""

    def test_punctuation_only_query_returns_empty(self, tmp_db: GraphStore) -> None:
        """search_nodes returns [] when the query normalises to an empty FTS expression."""
        # After camelCase splitting and non-word removal, "---" becomes ""
        results = tmp_db.search_nodes("---")
        assert results == []

    def test_all_dots_returns_empty(self, tmp_db: GraphStore) -> None:
        """search_nodes returns [] for an all-dots query."""
        results = tmp_db.search_nodes("...")
        assert results == []


# ──────────────────────────────────────────────
# get_file_summary — with edges
# ──────────────────────────────────────────────


class TestGetFileSummaryWithEdges:
    """Tests for GraphStore.get_file_summary() when edges exist (lines 512-521)."""

    def test_summary_includes_edges(self, tmp_db: GraphStore, simple_nodes, simple_edges) -> None:
        """get_file_summary returns non-empty edges list when edges are present."""
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        summary = tmp_db.get_file_summary("src/app.py")
        assert summary is not None
        assert "edges" in summary
        assert len(summary["edges"]) > 0

    def test_summary_edges_have_required_keys(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        """Each edge dict in the summary has kind, source, target keys."""
        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "h1")
        summary = tmp_db.get_file_summary("src/app.py")
        assert summary is not None
        for edge in summary["edges"]:
            assert "kind" in edge
            assert "source" in edge
            assert "target" in edge

    def test_summary_returns_none_for_unknown_file(self, tmp_db: GraphStore) -> None:
        """get_file_summary returns None when the file has not been indexed."""
        result = tmp_db.get_file_summary("nonexistent.py")
        assert result is None


# ──────────────────────────────────────────────
# store_file — rollback on error
# ──────────────────────────────────────────────


class TestStoreFileRollback:
    """Tests for atomic write rollback in GraphStore.store_file() (lines 269-271).

    sqlite3.Connection methods are read-only attributes, so we cannot use
    patch.object on them directly.  Instead we drop the FTS virtual table,
    which makes the FTS INSERT fail mid-transaction and exercises the rollback
    path without any mocking.
    """

    def test_rollback_leaves_no_data(self, tmp_db: GraphStore, simple_nodes) -> None:
        """When a mid-transaction SQL statement fails the data is rolled back."""
        # Corrupt the FTS table so the INSERT into nodes_fts raises
        tmp_db._conn.execute("DROP TABLE IF EXISTS nodes_fts")
        tmp_db._conn.commit()

        with pytest.raises(sqlite3.OperationalError):
            tmp_db.store_file("fail.py", simple_nodes, [], "hfail")

        # The nodes INSERT was inside the same transaction — it must be rolled back
        assert tmp_db.get_nodes_by_file("fail.py") == []

    def test_successful_store_after_failed_store(
        self, tmp_db: GraphStore, simple_nodes, simple_edges
    ) -> None:
        """After a rolled-back write, the store can be used normally once the
        broken FTS table is restored."""
        # Break FTS → force a rollback
        tmp_db._conn.execute("DROP TABLE IF EXISTS nodes_fts")
        tmp_db._conn.commit()

        with pytest.raises(sqlite3.OperationalError):
            tmp_db.store_file("bad.py", simple_nodes, [], "hbad")

        # Restore FTS so subsequent stores work
        tmp_db._conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                node_id UNINDEXED, name, qualified_name, signature, docstring,
                tokenize = 'unicode61'
            );
            """
        )
        tmp_db._conn.commit()

        tmp_db.store_file("src/app.py", simple_nodes, simple_edges, "hok")
        assert len(tmp_db.get_nodes_by_file("src/app.py")) == 3


# ──────────────────────────────────────────────
# get_impact_radius — max_nodes safety cap
# ──────────────────────────────────────────────


class TestImpactRadiusMaxNodes:
    """Tests for the max_nodes BFS cap in get_impact_radius() (lines 682-683, 687)."""

    def _build_chain(self, store: GraphStore, length: int) -> list[str]:
        """Build a linear chain of *length* files with CALLS edges.

        Args:
            store: GraphStore to write into.
            length: Number of nodes in the chain.

        Returns:
            List of file paths in chain order.
        """
        files = [f"chain_{i}.py" for i in range(length)]
        for i, fp in enumerate(files):
            nodes = [
                NodeInfo(
                    kind=NodeKind.FILE,
                    name=fp,
                    qualified_name=fp,
                    file_path=fp,
                    line_start=1,
                    line_end=5,
                    language="python",
                ),
                NodeInfo(
                    kind=NodeKind.FUNCTION,
                    name=f"fn_{i}",
                    qualified_name=f"{fp}::fn_{i}",
                    file_path=fp,
                    line_start=2,
                    line_end=4,
                    language="python",
                ),
            ]
            edges = []
            if i > 0:
                prev = files[i - 1]
                edges.append(
                    EdgeInfo(
                        kind=EdgeKind.CALLS,
                        source=f"{prev}::fn_{i - 1}",
                        target=f"{fp}::fn_{i}",
                        file_path=prev,
                        line=3,
                    )
                )
            store.store_file(fp, nodes, edges, f"h{i}")
        return files

    def test_max_nodes_stops_bfs(self, tmp_db: GraphStore) -> None:
        """With max_nodes=3, BFS stops early and does not visit the entire chain."""
        files = self._build_chain(tmp_db, 10)
        result = tmp_db.get_impact_radius([files[0]], max_depth=10, max_nodes=3)
        # Total nodes visited should be limited
        total = len(result["changed_nodes"]) + len(result["impacted_nodes"])
        # With max_nodes=3 the BFS breaks early, so we won't reach all 10 nodes
        assert total < 10
