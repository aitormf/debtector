"""Tests for debtector.parser.js_parser.JavaScriptParser.

Parses tests/fixtures/sample.ts and verifies extracted structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from debtector.models import EdgeKind, NodeKind
from debtector.parser.js_parser import JavaScriptParser


@pytest.fixture()
def parsed_ts(sample_ts_fixture_path: Path):
    """Parse sample.ts and return (nodes, edges)."""
    parser = JavaScriptParser()
    return parser.parse(str(sample_ts_fixture_path))


class TestJSParserNodes:
    """Tests for nodes extracted from sample.ts."""

    def test_has_file_node(self, parsed_ts) -> None:
        nodes, _ = parsed_ts
        file_nodes = [n for n in nodes if n.kind == NodeKind.FILE]
        assert len(file_nodes) == 1

    def test_has_two_classes(self, parsed_ts) -> None:
        nodes, _ = parsed_ts
        classes = [n for n in nodes if n.kind == NodeKind.CLASS]
        class_names = {n.name for n in classes}
        assert "UserService" in class_names
        assert "AdminService" in class_names

    def test_has_methods(self, parsed_ts) -> None:
        nodes, _ = parsed_ts
        methods = [n for n in nodes if n.kind == NodeKind.METHOD]
        method_names = {n.name for n in methods}
        assert "getUser" in method_names
        assert "createUser" in method_names
        assert "validateEmail" in method_names
        assert "deactivateUser" in method_names

    def test_has_top_level_functions(self, parsed_ts) -> None:
        nodes, _ = parsed_ts
        functions = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        func_names = {n.name for n in functions}
        assert "createApp" in func_names
        assert "healthCheck" in func_names

    def test_language_is_typescript(self, parsed_ts) -> None:
        nodes, _ = parsed_ts
        non_file = [n for n in nodes if n.kind != NodeKind.FILE]
        for n in non_file:
            assert n.language == "typescript"

    def test_method_has_parent_name(self, parsed_ts) -> None:
        nodes, _ = parsed_ts
        get_user = next(n for n in nodes if n.name == "getUser")
        assert get_user.parent_name == "UserService"

    def test_nodes_have_line_numbers(self, parsed_ts) -> None:
        nodes, _ = parsed_ts
        for n in nodes:
            assert n.line_start > 0, f"{n.name} has line_start=0"


class TestJSParserEdges:
    """Tests for edges extracted from sample.ts."""

    def test_has_imports_from_edges(self, parsed_ts) -> None:
        _, edges = parsed_ts
        import_targets = {e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM}
        assert any("database" in t.lower() for t in import_targets)

    def test_adminservice_inherits_userservice(self, parsed_ts) -> None:
        _, edges = parsed_ts
        inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
        assert any("AdminService" in e.source and e.target == "UserService" for e in inherits)

    def test_has_method_edges(self, parsed_ts) -> None:
        _, edges = parsed_ts
        has_method = [e for e in edges if e.kind == EdgeKind.HAS_METHOD]
        assert len(has_method) >= 3

    def test_contains_edges_for_classes_and_functions(self, parsed_ts) -> None:
        _, edges = parsed_ts
        contains = [e for e in edges if e.kind == EdgeKind.CONTAINS]
        targets = {e.target for e in contains}
        assert any("UserService" in t for t in targets)
        assert any("createApp" in t for t in targets)


class TestJSParserQualifiedNames:
    """Tests that qualified_names are correctly formed."""

    def test_file_qualified_name_is_path(self, parsed_ts, sample_ts_fixture_path) -> None:
        nodes, _ = parsed_ts
        file_node = next(n for n in nodes if n.kind == NodeKind.FILE)
        assert file_node.qualified_name == str(sample_ts_fixture_path)

    def test_class_qualified_name_format(self, parsed_ts, sample_ts_fixture_path) -> None:
        nodes, _ = parsed_ts
        user_service = next(n for n in nodes if n.name == "UserService")
        assert user_service.qualified_name == f"{sample_ts_fixture_path}::UserService"

    def test_method_qualified_name_format(self, parsed_ts, sample_ts_fixture_path) -> None:
        nodes, _ = parsed_ts
        get_user = next(n for n in nodes if n.name == "getUser")
        assert get_user.qualified_name == f"{sample_ts_fixture_path}::UserService.getUser"
