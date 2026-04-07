"""Tests for codeindex.models."""

from __future__ import annotations

from codeindex.models import (
    EdgeInfo,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeInfo,
    NodeKind,
    edge_to_dict,
    make_qualified_name,
    node_to_dict,
)


class TestMakeQualifiedName:
    """Tests for the make_qualified_name helper."""

    def test_file_returns_file_path(self) -> None:
        result = make_qualified_name("src/app.py", "app.py", NodeKind.FILE)
        assert result == "src/app.py"

    def test_class_returns_file_and_class(self) -> None:
        result = make_qualified_name("src/app.py", "UserService", NodeKind.CLASS)
        assert result == "src/app.py::UserService"

    def test_function_returns_file_and_name(self) -> None:
        result = make_qualified_name("src/app.py", "create_app", NodeKind.FUNCTION)
        assert result == "src/app.py::create_app"

    def test_method_includes_parent(self) -> None:
        result = make_qualified_name("src/app.py", "get_user", NodeKind.METHOD, "UserService")
        assert result == "src/app.py::UserService.get_user"

    def test_method_without_parent_treats_as_function(self) -> None:
        result = make_qualified_name("src/app.py", "helper", NodeKind.METHOD, None)
        assert result == "src/app.py::helper"

    def test_nested_path(self) -> None:
        result = make_qualified_name("src/auth/service.py", "AuthService", NodeKind.CLASS)
        assert result == "src/auth/service.py::AuthService"


class TestNodeInfo:
    """Tests for NodeInfo dataclass."""

    def test_minimal_construction(self) -> None:
        node = NodeInfo(
            kind=NodeKind.FILE,
            name="app.py",
            qualified_name="src/app.py",
            file_path="src/app.py",
        )
        assert node.kind == NodeKind.FILE
        assert node.name == "app.py"
        assert node.line_start == 0
        assert node.language == ""
        assert node.decorators == []
        assert node.extra == {}

    def test_full_construction(self) -> None:
        node = NodeInfo(
            kind=NodeKind.METHOD,
            name="get_user",
            qualified_name="src/app.py::UserService.get_user",
            file_path="src/app.py",
            line_start=10,
            line_end=20,
            language="python",
            parent_name="UserService",
            signature="def get_user(self, id: int) -> User",
            docstring="Gets a user by ID.",
            decorators=["@cache"],
            extra={"is_async": False},
        )
        assert node.parent_name == "UserService"
        assert node.decorators == ["@cache"]

    def test_decorators_default_is_independent(self) -> None:
        """Each NodeInfo instance gets its own decorators list (no shared mutable default)."""
        n1 = NodeInfo(kind=NodeKind.FILE, name="a", qualified_name="a", file_path="a")
        n2 = NodeInfo(kind=NodeKind.FILE, name="b", qualified_name="b", file_path="b")
        n1.decorators.append("@x")
        assert n2.decorators == []


class TestEdgeInfo:
    """Tests for EdgeInfo dataclass."""

    def test_minimal_construction(self) -> None:
        edge = EdgeInfo(
            kind=EdgeKind.CONTAINS,
            source="src/app.py",
            target="src/app.py::UserService",
            file_path="src/app.py",
        )
        assert edge.line == 0
        assert edge.extra == {}

    def test_extra_default_is_independent(self) -> None:
        e1 = EdgeInfo(kind=EdgeKind.CONTAINS, source="a", target="b", file_path="f")
        e2 = EdgeInfo(kind=EdgeKind.CONTAINS, source="c", target="d", file_path="f")
        e1.extra["key"] = "val"
        assert e2.extra == {}


class TestNodeToDict:
    """Tests for node_to_dict serialization helper."""

    def test_contains_expected_keys(self) -> None:
        node = GraphNode(
            id=1,
            kind=NodeKind.CLASS,
            name="MyClass",
            qualified_name="src/app.py::MyClass",
            file_path="src/app.py",
            line_start=5,
            line_end=20,
            language="python",
            parent_name=None,
            signature="class MyClass",
            docstring=None,
            file_hash="abc123",
            extra={},
        )
        d = node_to_dict(node)
        assert d["kind"] == NodeKind.CLASS
        assert d["name"] == "MyClass"
        assert d["qualified_name"] == "src/app.py::MyClass"
        assert d["file_path"] == "src/app.py"
        assert d["line_start"] == 5
        assert d["line_end"] == 20
        assert d["language"] == "python"
        assert d["parent_name"] is None
        assert d["signature"] == "class MyClass"


class TestEdgeToDict:
    """Tests for edge_to_dict serialization helper."""

    def test_contains_expected_keys(self) -> None:
        edge = GraphEdge(
            id=1,
            kind=EdgeKind.IMPORTS_FROM,
            source_qualified="src/app.py",
            target_qualified="flask",
            file_path="src/app.py",
            line=3,
            extra={},
        )
        d = edge_to_dict(edge)
        assert d["kind"] == EdgeKind.IMPORTS_FROM
        assert d["source"] == "src/app.py"
        assert d["target"] == "flask"
        assert d["file_path"] == "src/app.py"
        assert d["line"] == 3
