"""Tests for codeindex.parser.python_parser.PythonParser.

Parses tests/fixtures/sample.py and verifies the extracted structure matches
the expected counts documented in CONTEXT.md §19.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeindex.models import EdgeKind, NodeKind
from codeindex.parser.python_parser import PythonParser


@pytest.fixture()
def parsed(sample_fixture_path: Path):
    """Parse sample.py and return (nodes, edges)."""
    parser = PythonParser()
    return parser.parse(str(sample_fixture_path))


class TestPythonParserNodes:
    """Tests for nodes extracted from sample.py."""

    def test_has_file_node(self, parsed) -> None:
        nodes, _ = parsed
        file_nodes = [n for n in nodes if n.kind == NodeKind.FILE]
        assert len(file_nodes) == 1

    def test_has_three_classes(self, parsed) -> None:
        nodes, _ = parsed
        classes = [n for n in nodes if n.kind == NodeKind.CLASS]
        class_names = {n.name for n in classes}
        assert "User" in class_names
        assert "UserService" in class_names
        assert "AdminService" in class_names

    def test_has_five_methods(self, parsed) -> None:
        nodes, _ = parsed
        methods = [n for n in nodes if n.kind == NodeKind.METHOD]
        method_names = {n.name for n in methods}
        assert "__init__" in method_names
        assert "get_user" in method_names
        assert "create_user" in method_names
        assert "validate_email" in method_names
        assert "deactivate_user" in method_names

    def test_has_two_top_level_functions(self, parsed) -> None:
        nodes, _ = parsed
        functions = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        func_names = {n.name for n in functions}
        assert "create_app" in func_names
        assert "health_check" in func_names

    def test_total_node_count(self, parsed) -> None:
        """1 File + 3 Class + 5 Method + 2 Function = 11 nodes."""
        nodes, _ = parsed
        assert len(nodes) == 11

    def test_method_has_parent_name(self, parsed) -> None:
        nodes, _ = parsed
        get_user = next(n for n in nodes if n.name == "get_user")
        assert get_user.parent_name == "UserService"

    def test_method_has_signature(self, parsed) -> None:
        nodes, _ = parsed
        get_user = next(n for n in nodes if n.name == "get_user")
        assert get_user.signature is not None
        assert "get_user" in get_user.signature

    def test_class_has_docstring(self, parsed) -> None:
        nodes, _ = parsed
        user_service = next(n for n in nodes if n.name == "UserService")
        assert user_service.docstring is not None
        assert len(user_service.docstring) > 0

    def test_nodes_have_line_numbers(self, parsed) -> None:
        nodes, _ = parsed
        for n in nodes:
            assert n.line_start > 0, f"{n.name} has line_start=0"

    def test_language_is_python(self, parsed) -> None:
        nodes, _ = parsed
        for n in nodes:
            assert n.language == "python"


class TestPythonParserEdges:
    """Tests for edges extracted from sample.py."""

    def test_has_imports_from_edges(self, parsed) -> None:
        _, edges = parsed
        import_targets = {e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM}
        assert "os" in import_targets
        assert "dataclasses" in import_targets
        assert "typing" in import_targets
        assert "flask" in import_targets

    def test_has_relative_import(self, parsed) -> None:
        _, edges = parsed
        import_targets = {e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM}
        # .database relative import
        assert any("database" in t for t in import_targets)

    def test_adminservice_inherits_userservice(self, parsed) -> None:
        _, edges = parsed
        inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
        assert any("AdminService" in e.source and e.target == "UserService" for e in inherits)

    def test_contains_edges_for_classes_and_functions(self, parsed) -> None:
        _, edges = parsed
        contains = [e for e in edges if e.kind == EdgeKind.CONTAINS]
        targets = {e.target for e in contains}
        assert any("UserService" in t for t in targets)
        assert any("create_app" in t for t in targets)

    def test_has_method_edges(self, parsed) -> None:
        _, edges = parsed
        has_method = [e for e in edges if e.kind == EdgeKind.HAS_METHOD]
        targets = {e.target for e in has_method}
        assert any("get_user" in t for t in targets)
        assert any("deactivate_user" in t for t in targets)

    def test_total_edge_count_approximately(self, parsed) -> None:
        """~14 structural + up to 4 CALLS + some USES_TYPE edges."""
        _, edges = parsed
        # 5 CONTAINS + 5 HAS_METHOD + 5 IMPORTS_FROM + 1 INHERITS + ≤4 CALLS + ≤10 USES_TYPE
        assert 13 <= len(edges) <= 30, f"Got {len(edges)} edges: {[e.kind for e in edges]}"


class TestPythonParserQualifiedNames:
    """Tests that qualified_names are correctly formed."""

    def test_file_qualified_name_is_path(self, parsed, sample_fixture_path) -> None:
        nodes, _ = parsed
        file_node = next(n for n in nodes if n.kind == NodeKind.FILE)
        assert file_node.qualified_name == str(sample_fixture_path)

    def test_class_qualified_name_format(self, parsed, sample_fixture_path) -> None:
        nodes, _ = parsed
        user_service = next(n for n in nodes if n.name == "UserService")
        assert user_service.qualified_name == f"{sample_fixture_path}::UserService"

    def test_method_qualified_name_format(self, parsed, sample_fixture_path) -> None:
        nodes, _ = parsed
        get_user = next(n for n in nodes if n.name == "get_user")
        assert get_user.qualified_name == f"{sample_fixture_path}::UserService.get_user"

    def test_function_qualified_name_format(self, parsed, sample_fixture_path) -> None:
        nodes, _ = parsed
        create_app = next(n for n in nodes if n.name == "create_app")
        assert create_app.qualified_name == f"{sample_fixture_path}::create_app"
