"""Relative imports keep their leading dots, so they never collide with absolute ones."""

from __future__ import annotations

from pathlib import Path

from debtector.models import EdgeKind
from debtector.parser.python_parser import PythonParser


def _targets(tmp_path: Path, code: str) -> set[str]:
    path = tmp_path / "pkg" / "mod.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    _, edges = PythonParser().parse(str(path))
    return {e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM}


def test_relative_module_keeps_its_dot(tmp_path: Path) -> None:
    assert _targets(tmp_path, "from .c import x\n") == {".c"}


def test_parent_relative_module_keeps_its_dots(tmp_path: Path) -> None:
    assert _targets(tmp_path, "from ..util.io import read\n") == {"..util.io"}


def test_bare_relative_import_targets_each_name(tmp_path: Path) -> None:
    assert _targets(tmp_path, "from . import a, b as bee\n") == {".a", ".b"}


def test_bare_parent_relative_import(tmp_path: Path) -> None:
    assert _targets(tmp_path, "from .. import helpers\n") == {"..helpers"}


def test_absolute_imports_stay_absolute(tmp_path: Path) -> None:
    assert _targets(tmp_path, "import json\nfrom os.path import join\n") == {"json", "os.path"}
