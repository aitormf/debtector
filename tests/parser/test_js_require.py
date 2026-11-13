"""T4: every require("<literal>") call creates an import, wherever it is (R4)."""

from __future__ import annotations

from pathlib import Path

from debtector.metrics import METRICS_VERSION
from debtector.models import EdgeKind
from debtector.parser import PARSER_VERSION
from debtector.parser.js_parser import JavaScriptParser


def _targets(tmp_path: Path, code: str) -> list[str]:
    path = tmp_path / "mod.js"
    path.write_text(code, encoding="utf-8")
    _, edges = JavaScriptParser().parse(str(path))
    return [e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM]


def test_E14_require_in_var(tmp_path: Path) -> None:
    assert _targets(tmp_path, "var View = require('./view');\n") == ["./view"]


def test_E14_const_still_works(tmp_path: Path) -> None:
    assert _targets(tmp_path, "const a = require('./a');\nlet b = require('./b');\n") == [
        "./a",
        "./b",
    ]


def test_E15_chained_and_called_require(tmp_path: Path) -> None:
    code = "var methods = require('./utils').methods;\nvar debug = require('debug')('x');\n"
    assert sorted(_targets(tmp_path, code)) == ["./utils", "debug"]


def test_E16_non_literal_require_makes_no_edge(tmp_path: Path) -> None:
    assert _targets(tmp_path, "var m = require(name);\n") == []


def test_E17_versions_bumped() -> None:
    assert PARSER_VERSION >= 6
    assert METRICS_VERSION >= 5
