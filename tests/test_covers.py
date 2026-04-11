"""Tests for COVERS edge extraction and untested symbol detection.

TDD spec for:
- is_test_file() utility
- Parser emits unresolved CALLS from test files
- GraphStore.update_covers_edges() builds COVERS from unresolved CALLS
- GraphStore.get_uncovered_symbols() returns Functions/Methods with no COVERS
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeindex.graph_store import GraphStore
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind
from codeindex.parser.python_parser import PythonParser
from codeindex.utils import is_test_file

FIXTURES = Path(__file__).parent / "fixtures"
COVERS_PROD = str(FIXTURES / "covers_prod.py")
TEST_COVERS_SAMPLE = str(FIXTURES / "test_covers_sample.py")


# ──────────────────────────────────────────────
# is_test_file
# ──────────────────────────────────────────────


class TestIsTestFile:
    """Unit tests for the is_test_file() path classifier."""

    def test_test_prefix_python(self) -> None:
        assert is_test_file("test_auth.py") is True

    def test_test_prefix_with_path(self) -> None:
        assert is_test_file("tests/test_service.py") is True

    def test_test_prefix_nested(self) -> None:
        assert is_test_file("src/auth/test_utils.py") is True

    def test_suffix_python(self) -> None:
        assert is_test_file("auth_test.py") is True

    def test_test_ts(self) -> None:
        assert is_test_file("service.test.ts") is True

    def test_spec_ts(self) -> None:
        assert is_test_file("service.spec.ts") is True

    def test_test_js(self) -> None:
        assert is_test_file("utils.test.js") is True

    def test_spec_js(self) -> None:
        assert is_test_file("utils.spec.js") is True

    def test_production_py(self) -> None:
        assert is_test_file("service.py") is False

    def test_production_ts(self) -> None:
        assert is_test_file("service.ts") is False

    def test_production_nested(self) -> None:
        assert is_test_file("src/auth/service.py") is False

    def test_calls_sample_not_test(self) -> None:
        assert is_test_file("calls_sample.py") is False

    def test_sample_not_test(self) -> None:
        assert is_test_file("tests/fixtures/sample.py") is False


# ──────────────────────────────────────────────
# Parser: unresolved CALLS in test files
# ──────────────────────────────────────────────


@pytest.fixture()
def test_file_result():
    """Parse test_covers_sample.py (a test file) and return (nodes, edges)."""
    return PythonParser().parse(TEST_COVERS_SAMPLE)


@pytest.fixture()
def prod_file_result():
    """Parse covers_prod.py (a production file) and return (nodes, edges)."""
    return PythonParser().parse(COVERS_PROD)


class TestUnresolvedCallsInTestFiles:
    """Parser must emit unresolved CALLS edges from test files."""

    def test_emits_unresolved_calls(self, test_file_result) -> None:
        _, edges = test_file_result
        unresolved = [e for e in edges if e.kind == EdgeKind.CALLS and e.extra.get("unresolved")]
        assert len(unresolved) > 0

    def test_unresolved_add_call(self, test_file_result) -> None:
        _, edges = test_file_result
        unresolved = [e for e in edges if e.kind == EdgeKind.CALLS and e.extra.get("unresolved")]
        assert "add" in {e.target for e in unresolved}

    def test_unresolved_subtract_call(self, test_file_result) -> None:
        _, edges = test_file_result
        unresolved = [e for e in edges if e.kind == EdgeKind.CALLS and e.extra.get("unresolved")]
        assert "subtract" in {e.target for e in unresolved}

    def test_unresolved_source_is_test_function(self, test_file_result) -> None:
        _, edges = test_file_result
        sources = {
            e.source for e in edges if e.kind == EdgeKind.CALLS and e.extra.get("unresolved")
        }
        # At least one source should be a test function
        assert any("test_" in s for s in sources)

    def test_no_unresolved_from_production_file(self, prod_file_result) -> None:
        """Production files must NOT emit unresolved CALLS."""
        _, edges = prod_file_result
        unresolved = [e for e in edges if e.kind == EdgeKind.CALLS and e.extra.get("unresolved")]
        assert len(unresolved) == 0

    def test_unresolved_calls_have_line_numbers(self, test_file_result) -> None:
        _, edges = test_file_result
        for e in edges:
            if e.kind == EdgeKind.CALLS and e.extra.get("unresolved"):
                assert e.line > 0


# ──────────────────────────────────────────────
# GraphStore: update_covers_edges
# ──────────────────────────────────────────────


def _build_store(tmp_path) -> GraphStore:
    return GraphStore(tmp_path / "covers_test.db")


def _populate_store(store: GraphStore) -> None:
    """Insert prod nodes + test nodes + unresolved CALLS edges."""
    prod_nodes = [
        NodeInfo(
            kind=NodeKind.FUNCTION,
            name="add",
            qualified_name="src/math.py::add",
            file_path="src/math.py",
            language="python",
        ),
        NodeInfo(
            kind=NodeKind.FUNCTION,
            name="subtract",
            qualified_name="src/math.py::subtract",
            file_path="src/math.py",
            language="python",
        ),
        NodeInfo(
            kind=NodeKind.FUNCTION,
            name="multiply",
            qualified_name="src/math.py::multiply",
            file_path="src/math.py",
            language="python",
        ),
    ]
    test_nodes = [
        NodeInfo(
            kind=NodeKind.FUNCTION,
            name="test_add",
            qualified_name="tests/test_math.py::test_add",
            file_path="tests/test_math.py",
            language="python",
        ),
        NodeInfo(
            kind=NodeKind.FUNCTION,
            name="test_subtract",
            qualified_name="tests/test_math.py::test_subtract",
            file_path="tests/test_math.py",
            language="python",
        ),
    ]
    test_calls = [
        EdgeInfo(
            kind=EdgeKind.CALLS,
            source="tests/test_math.py::test_add",
            target="add",
            file_path="tests/test_math.py",
            line=5,
            extra={"unresolved": True},
        ),
        EdgeInfo(
            kind=EdgeKind.CALLS,
            source="tests/test_math.py::test_subtract",
            target="subtract",
            file_path="tests/test_math.py",
            line=10,
            extra={"unresolved": True},
        ),
    ]
    store.store_file("src/math.py", prod_nodes, [], "hash_prod")
    store.store_file("tests/test_math.py", test_nodes, test_calls, "hash_test")


class TestUpdateCoversEdges:
    """GraphStore.update_covers_edges() must derive COVERS from unresolved CALLS."""

    def test_returns_count(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        count = store.update_covers_edges()
        assert count == 2
        store.close()

    def test_covers_edge_kind(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        store.update_covers_edges()
        rows = store._conn.execute("SELECT * FROM edges WHERE kind = 'COVERS'").fetchall()
        assert len(rows) == 2
        store.close()

    def test_covers_source_is_test_function(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        store.update_covers_edges()
        rows = store._conn.execute(
            "SELECT source_qualified FROM edges WHERE kind = 'COVERS'"
        ).fetchall()
        for r in rows:
            assert "tests/" in r["source_qualified"]
        store.close()

    def test_covers_target_is_prod_function(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        store.update_covers_edges()
        rows = store._conn.execute(
            "SELECT target_qualified FROM edges WHERE kind = 'COVERS'"
        ).fetchall()
        targets = {r["target_qualified"] for r in rows}
        assert "src/math.py::add" in targets
        assert "src/math.py::subtract" in targets
        store.close()

    def test_multiply_not_covered(self, tmp_path) -> None:
        """multiply has no test — must NOT appear in COVERS targets."""
        store = _build_store(tmp_path)
        _populate_store(store)
        store.update_covers_edges()
        rows = store._conn.execute(
            "SELECT target_qualified FROM edges WHERE kind = 'COVERS'"
        ).fetchall()
        targets = {r["target_qualified"] for r in rows}
        assert "src/math.py::multiply" not in targets
        store.close()

    def test_idempotent(self, tmp_path) -> None:
        """Calling update_covers_edges twice must produce the same result."""
        store = _build_store(tmp_path)
        _populate_store(store)
        store.update_covers_edges()
        store.update_covers_edges()
        count = store._conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'COVERS'").fetchone()[
            0
        ]
        assert count == 2
        store.close()

    def test_no_covers_targeting_test_files(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        store.update_covers_edges()
        rows = store._conn.execute(
            "SELECT target_qualified FROM edges WHERE kind = 'COVERS'"
        ).fetchall()
        for r in rows:
            assert not r["target_qualified"].startswith("tests/")
        store.close()


# ──────────────────────────────────────────────
# GraphStore: get_uncovered_symbols
# ──────────────────────────────────────────────


class TestGetUncoveredSymbols:
    """GraphStore.get_uncovered_symbols() must list production symbols with no COVERS."""

    def test_all_uncovered_before_update(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        uncovered = store.get_uncovered_symbols()
        names = {n.name for n in uncovered}
        assert "add" in names
        assert "subtract" in names
        assert "multiply" in names
        store.close()

    def test_covered_excluded_after_update(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        store.update_covers_edges()
        uncovered = store.get_uncovered_symbols()
        names = {n.name for n in uncovered}
        assert "add" not in names
        assert "subtract" not in names
        store.close()

    def test_uncovered_remains(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        store.update_covers_edges()
        uncovered = store.get_uncovered_symbols()
        names = {n.name for n in uncovered}
        assert "multiply" in names
        store.close()

    def test_test_functions_excluded(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        uncovered = store.get_uncovered_symbols()
        for n in uncovered:
            assert not n.file_path.startswith("tests/")
        store.close()

    def test_path_filter(self, tmp_path) -> None:
        store = _build_store(tmp_path)
        _populate_store(store)
        uncovered = store.get_uncovered_symbols(path_filter="src/math.py")
        assert all(n.file_path == "src/math.py" for n in uncovered)
        store.close()

    def test_empty_when_all_covered(self, tmp_path) -> None:
        """If all symbols are covered, result must be empty."""
        store = _build_store(tmp_path)
        # Only add + subtract, both covered
        prod_nodes = [
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name="add",
                qualified_name="src/m.py::add",
                file_path="src/m.py",
                language="python",
            ),
        ]
        test_nodes = [
            NodeInfo(
                kind=NodeKind.FUNCTION,
                name="test_add",
                qualified_name="tests/test_m.py::test_add",
                file_path="tests/test_m.py",
                language="python",
            ),
        ]
        test_calls = [
            EdgeInfo(
                kind=EdgeKind.CALLS,
                source="tests/test_m.py::test_add",
                target="add",
                file_path="tests/test_m.py",
                line=3,
                extra={"unresolved": True},
            ),
        ]
        store.store_file("src/m.py", prod_nodes, [], "h1")
        store.store_file("tests/test_m.py", test_nodes, test_calls, "h2")
        store.update_covers_edges()
        assert store.get_uncovered_symbols() == []
        store.close()
