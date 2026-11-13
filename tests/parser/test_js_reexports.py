"""T5: an `export ... from "<module>"` reexport creates an import (R5)."""

from __future__ import annotations

from pathlib import Path

from debtector.metrics import METRICS_VERSION
from debtector.models import EdgeKind
from debtector.parser import PARSER_VERSION
from debtector.parser.js_parser import JavaScriptParser


def _targets(tmp_path: Path, code: str, name: str = "index.ts") -> list[str]:
    path = tmp_path / name
    path.write_text(code, encoding="utf-8")
    _, edges = JavaScriptParser().parse(str(path))
    return [e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM]


def test_E18_export_star(tmp_path: Path) -> None:
    assert _targets(tmp_path, 'export * from "./core.js";\n') == ["./core.js"]


def test_E19_named_and_type_reexports(tmp_path: Path) -> None:
    code = 'export { a, b as c } from "./b";\nexport type { T } from "./t";\n'
    assert sorted(_targets(tmp_path, code)) == ["./b", "./t"]


def test_E19_reexport_in_plain_js(tmp_path: Path) -> None:
    assert _targets(tmp_path, "export * from './x.js';\n", "index.js") == ["./x.js"]


def test_E20_local_exports_make_no_edge(tmp_path: Path) -> None:
    assert _targets(tmp_path, "export const x = 1;\nexport { x };\n") == []


def test_E21_versions_bumped() -> None:
    assert PARSER_VERSION >= 6
    assert METRICS_VERSION >= 5
