"""Parsers store the cyclomatic complexity in ``extra`` of Function/Method nodes."""

from __future__ import annotations

from pathlib import Path

from debtector.models import NodeKind
from debtector.parser.js_parser import JavaScriptParser
from debtector.parser.python_parser import PythonParser

PY_SRC = """\
import os


class Service:
    \"\"\"Doc.\"\"\"

    def check(self, a, b):
        if a and b:
            return 1
        return 2

    def plain(self):
        return 0


def helper(xs):
    for x in xs:
        if x:
            return x
    return None


def trivial():
    pass
"""

TS_SRC = """\
export function pick(a: number): number {
  return a > 0 ? 1 : 2;
}

export const arrow = (a: boolean, b: boolean) => {
  if (a && b) { return 1; }
  return 0;
};

class Repo {
  find(id: string): string {
    for (const x of [id]) {
      if (x) { return x; }
    }
    return "";
  }
}
"""


def _complexities(nodes) -> dict[str, int]:
    return {
        n.qualified_name.split("::")[-1]: n.extra["complexity"]
        for n in nodes
        if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)
    }


def test_python_functions_and_methods_carry_complexity(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text(PY_SRC, encoding="utf-8")

    nodes, _ = PythonParser().parse(str(path))

    assert _complexities(nodes) == {
        "Service.check": 3,
        "Service.plain": 1,
        "helper": 3,
        "trivial": 1,
    }


def test_python_files_and_classes_have_no_complexity(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text(PY_SRC, encoding="utf-8")

    nodes, _ = PythonParser().parse(str(path))

    for node in nodes:
        if node.kind in (NodeKind.FILE, NodeKind.CLASS):
            assert "complexity" not in node.extra


def test_python_decorated_function_carries_complexity(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("@deco\ndef f(a):\n    if a:\n        pass\n", encoding="utf-8")

    nodes, _ = PythonParser().parse(str(path))

    assert _complexities(nodes) == {"f": 2}


def test_ts_functions_arrows_and_methods_carry_complexity(tmp_path: Path) -> None:
    path = tmp_path / "mod.ts"
    path.write_text(TS_SRC, encoding="utf-8")

    nodes, _ = JavaScriptParser().parse(str(path))

    assert _complexities(nodes) == {"pick": 2, "arrow": 3, "Repo.find": 3}


def test_sample_fixture_functions_all_have_complexity(
    sample_fixture_path: Path, sample_ts_fixture_path: Path
) -> None:
    for parser, fixture in (
        (PythonParser(), sample_fixture_path),
        (JavaScriptParser(), sample_ts_fixture_path),
    ):
        nodes, _ = parser.parse(str(fixture))
        symbols = [n for n in nodes if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD)]
        assert symbols
        assert all(n.extra["complexity"] >= 1 for n in symbols)


NESTED_SRC = """\
def factory(a):
    if a:
        pass

    def inner(b):
        if b and a:
            pass

        def deep(c):
            if c:
                pass

    return inner


def flat():
    pass
"""


def test_nested_scopes_keep_outer_complexity_radon_compatible(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text(NESTED_SRC, encoding="utf-8")

    nodes, _ = PythonParser().parse(str(path))

    by_name = {n.name: n for n in nodes if n.kind == NodeKind.FUNCTION}
    assert set(by_name) == {"factory", "flat"}  # closures are not graph nodes
    assert by_name["factory"].extra["complexity"] == 2  # radon: factory (2)
    # radon closures: inner (3) + deep (2), recursively
    assert by_name["factory"].extra["nested_complexity"] == 5
    assert "nested_complexity" not in by_name["flat"].extra


def test_file_complexity_includes_nested_scopes(tmp_path: Path) -> None:
    from debtector.git_history import _file_complexities
    from debtector.graph_store import GraphStore
    from debtector.indexer import Indexer

    (tmp_path / "mod.py").write_text(NESTED_SRC, encoding="utf-8")
    store = GraphStore(tmp_path / "idx.db")
    Indexer(store).index(str(tmp_path))

    assert _file_complexities(store) == {"mod.py": 2 + 5 + 1}
    store.close()
