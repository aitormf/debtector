"""Shared pytest fixtures for CodeIndex tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeindex.graph_store import GraphStore
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind
from codeindex.parser.python_parser import PythonParser


@pytest.fixture()
def tmp_db(tmp_path: Path) -> GraphStore:
    """Provide a temporary in-memory-like GraphStore backed by a temp file."""
    db_path = tmp_path / ".codeindex.db"
    store = GraphStore(db_path)
    yield store
    store.close()


@pytest.fixture()
def python_parser() -> PythonParser:
    """Provide a PythonParser instance."""
    return PythonParser()


@pytest.fixture()
def sample_fixture_path() -> Path:
    """Return the absolute path to tests/fixtures/sample.py."""
    return Path(__file__).parent / "fixtures" / "sample.py"


@pytest.fixture()
def sample_ts_fixture_path() -> Path:
    """Return the absolute path to tests/fixtures/sample.ts."""
    return Path(__file__).parent / "fixtures" / "sample.ts"


@pytest.fixture()
def python_extras_fixture_path() -> Path:
    """Return the absolute path to tests/fixtures/python_extras.py."""
    return Path(__file__).parent / "fixtures" / "python_extras.py"


@pytest.fixture()
def js_commonjs_fixture_path() -> Path:
    """Return the absolute path to tests/fixtures/js_commonjs.js."""
    return Path(__file__).parent / "fixtures" / "js_commonjs.js"


@pytest.fixture()
def ts_calls_fixture_path() -> Path:
    """Return the absolute path to tests/fixtures/calls_sample.ts."""
    return Path(__file__).parent / "fixtures" / "calls_sample.ts"


@pytest.fixture()
def simple_nodes() -> list[NodeInfo]:
    """A minimal set of nodes for testing graph_store writes."""
    return [
        NodeInfo(
            kind=NodeKind.FILE,
            name="app.py",
            qualified_name="src/app.py",
            file_path="src/app.py",
            line_start=1,
            line_end=50,
            language="python",
        ),
        NodeInfo(
            kind=NodeKind.CLASS,
            name="MyService",
            qualified_name="src/app.py::MyService",
            file_path="src/app.py",
            line_start=5,
            line_end=30,
            language="python",
        ),
        NodeInfo(
            kind=NodeKind.METHOD,
            name="run",
            qualified_name="src/app.py::MyService.run",
            file_path="src/app.py",
            line_start=10,
            line_end=20,
            language="python",
            parent_name="MyService",
        ),
    ]


@pytest.fixture()
def simple_edges() -> list[EdgeInfo]:
    """A minimal set of edges matching simple_nodes."""
    return [
        EdgeInfo(
            kind=EdgeKind.CONTAINS,
            source="src/app.py",
            target="src/app.py::MyService",
            file_path="src/app.py",
            line=5,
        ),
        EdgeInfo(
            kind=EdgeKind.HAS_METHOD,
            source="src/app.py::MyService",
            target="src/app.py::MyService.run",
            file_path="src/app.py",
            line=10,
        ),
        EdgeInfo(
            kind=EdgeKind.IMPORTS_FROM,
            source="src/app.py",
            target="flask",
            file_path="src/app.py",
            line=1,
        ),
    ]
