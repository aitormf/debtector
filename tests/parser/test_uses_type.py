"""Tests for USES_TYPE edge extraction in Python and JS/TS parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeindex.models import EdgeKind
from codeindex.parser.js_parser import JavaScriptParser
from codeindex.parser.python_parser import PythonParser

# ──────────────────────────────────────────────
# Python
# ──────────────────────────────────────────────


@pytest.fixture()
def py_parser() -> PythonParser:
    return PythonParser()


def _py(tmp_path: Path, code: str) -> tuple:
    """Write *code* to a .py file and parse it."""
    f = tmp_path / "mod.py"
    f.write_text(code, encoding="utf-8")
    return PythonParser().parse(str(f))


def _ts(tmp_path: Path, code: str) -> tuple:
    """Write *code* to a .ts file and parse it."""
    f = tmp_path / "mod.ts"
    f.write_text(code, encoding="utf-8")
    return JavaScriptParser().parse(str(f))


def _uses_type_targets(edges) -> set[str]:
    return {e.target for e in edges if e.kind == EdgeKind.USES_TYPE}


class TestPythonUsesType:
    """USES_TYPE edges extracted by PythonParser."""

    def test_param_type_generates_edge(self, tmp_path: Path) -> None:
        """A typed parameter produces a USES_TYPE edge for the type name."""
        _, edges = _py(tmp_path, "def f(x: User) -> None:\n    pass\n")
        assert "User" in _uses_type_targets(edges)

    def test_return_type_generates_edge(self, tmp_path: Path) -> None:
        """A return type annotation produces a USES_TYPE edge."""
        _, edges = _py(tmp_path, "def f() -> Response:\n    pass\n")
        assert "Response" in _uses_type_targets(edges)

    def test_lowercase_primitives_filtered_out(self, tmp_path: Path) -> None:
        """Lowercase primitive types (int, str, bool) are NOT emitted."""
        _, edges = _py(tmp_path, "def f(x: int, y: str) -> bool:\n    pass\n")
        targets = _uses_type_targets(edges)
        assert "int" not in targets
        assert "str" not in targets
        assert "bool" not in targets

    def test_generic_type_extracts_inner(self, tmp_path: Path) -> None:
        """Optional[User] and List[Response] extract inner type names."""
        code = "def f(x: Optional[User]) -> List[Response]:\n    pass\n"
        _, edges = _py(tmp_path, code)
        targets = _uses_type_targets(edges)
        assert "User" in targets
        assert "Response" in targets

    def test_method_type_hints(self, tmp_path: Path) -> None:
        """Type hints on class methods are also extracted."""
        code = "class MyService:\n    def get(self, user: User) -> Response:\n        pass\n"
        _, edges = _py(tmp_path, code)
        assert "User" in _uses_type_targets(edges)
        assert "Response" in _uses_type_targets(edges)

    def test_no_type_hints_no_uses_type_edges(self, tmp_path: Path) -> None:
        """A function with no type hints produces no USES_TYPE edges."""
        _, edges = _py(tmp_path, "def f(x, y):\n    pass\n")
        assert not any(e.kind == EdgeKind.USES_TYPE for e in edges)

    def test_source_is_file_path(self, tmp_path: Path) -> None:
        """USES_TYPE edge source is the file's qualified_name (file path)."""
        _, edges = _py(tmp_path, "def f(x: User) -> None:\n    pass\n")
        uses = [e for e in edges if e.kind == EdgeKind.USES_TYPE]
        expected_source = str(tmp_path / "mod.py")
        assert all(e.source == expected_source for e in uses)

    def test_no_duplicate_edges_for_same_type(self, tmp_path: Path) -> None:
        """The same type referenced twice in one file produces one edge."""
        code = "def f(x: User) -> User:\n    pass\ndef g(y: User) -> None:\n    pass\n"
        _, edges = _py(tmp_path, code)
        uses_user = [e for e in edges if e.kind == EdgeKind.USES_TYPE and e.target == "User"]
        assert len(uses_user) == 1


class TestTypeScriptUsesType:
    """USES_TYPE edges extracted by JavaScriptParser for TypeScript files."""

    def test_param_type_generates_edge(self, tmp_path: Path) -> None:
        """A typed TS parameter produces a USES_TYPE edge."""
        code = "function greet(user: User): void {}\n"
        _, edges = _ts(tmp_path, code)
        assert "User" in _uses_type_targets(edges)

    def test_return_type_generates_edge(self, tmp_path: Path) -> None:
        """A TS return type annotation produces a USES_TYPE edge."""
        code = "function greet(): Response {}\n"
        _, edges = _ts(tmp_path, code)
        assert "Response" in _uses_type_targets(edges)

    def test_lowercase_primitives_filtered(self, tmp_path: Path) -> None:
        """Primitive TS types (string, number, boolean) are NOT emitted."""
        code = "function f(x: string, y: number): boolean { return true; }\n"
        _, edges = _ts(tmp_path, code)
        targets = _uses_type_targets(edges)
        assert "string" not in targets
        assert "number" not in targets
        assert "boolean" not in targets

    def test_method_type_hints(self, tmp_path: Path) -> None:
        """Type hints on class methods are extracted."""
        code = "class MyService {\n  get(user: User): Response { return {} as Response; }\n}\n"
        _, edges = _ts(tmp_path, code)
        targets = _uses_type_targets(edges)
        assert "User" in targets
        assert "Response" in targets
