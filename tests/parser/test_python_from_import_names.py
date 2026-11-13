"""The parser keeps the imported names of ``from X import a, b`` in the edge (D-0018)."""

from __future__ import annotations

from pathlib import Path

from debtector.metrics import METRICS_VERSION
from debtector.models import EdgeInfo, EdgeKind
from debtector.parser import PARSER_VERSION
from debtector.parser.python_parser import PythonParser


def _imports(tmp_path: Path, code: str) -> list[EdgeInfo]:
    path = tmp_path / "pkg" / "mod.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    _, edges = PythonParser().parse(str(path))
    return [e for e in edges if e.kind == EdgeKind.IMPORTS_FROM]


def test_E1_names_go_in_one_edge_to_the_package(tmp_path: Path) -> None:
    edges = _imports(tmp_path, "from blib2to3.pgen2 import grammar, token as t\n")
    assert [(e.target, e.extra) for e in edges] == [
        ("blib2to3.pgen2", {"names": ["grammar", "token"]})
    ]


def test_E2_bare_relative_import_is_one_edge_to_the_dot(tmp_path: Path) -> None:
    edges = _imports(tmp_path, "from . import a, b as bee\n")
    assert [(e.target, e.extra) for e in edges] == [(".", {"names": ["a", "b"]})]


def test_E3_wildcard_has_no_names(tmp_path: Path) -> None:
    edges = _imports(tmp_path, "from pkg import *\n")
    assert [(e.target, e.extra.get("names")) for e in edges] == [("pkg", None)]


def test_E4_parser_version_bumped() -> None:
    assert PARSER_VERSION >= 9


def test_E14_metrics_version_bumped() -> None:
    assert METRICS_VERSION >= 12
