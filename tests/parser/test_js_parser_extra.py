"""Extra tests for JavaScriptParser covering edge cases not in test_js_parser.py.

Patterns covered:
- CommonJS require() imports — lines 122-124, 163-166
- Arrow functions (const fn = () => {}) — lines 321, 350-374
- Arrow function CALLS extraction — lines 539-550
- this.method() CALLS within TS class — lines 627-629, 641-644
- JavaScript language label (.js extension) — line 34
- JS class extends (without TypeScript extends_clause) — line 442
- Parser metadata (language, extensions, can_parse)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from codeindex.models import EdgeKind, NodeKind
from codeindex.parser.js_parser import JavaScriptParser


@pytest.fixture()
def parser() -> JavaScriptParser:
    """Provide a fresh JavaScriptParser instance."""
    return JavaScriptParser()


@pytest.fixture()
def parsed_js(js_commonjs_fixture_path: Path):
    """Parse js_commonjs.js and return (nodes, edges).

    Args:
        js_commonjs_fixture_path: Path to the CommonJS JS fixture.

    Returns:
        Tuple of (nodes, edges).
    """
    return JavaScriptParser().parse(str(js_commonjs_fixture_path))


@pytest.fixture()
def parsed_ts_calls(ts_calls_fixture_path: Path):
    """Parse calls_sample.ts and return (nodes, edges).

    Args:
        ts_calls_fixture_path: Path to the TS calls fixture.

    Returns:
        Tuple of (nodes, edges).
    """
    return JavaScriptParser().parse(str(ts_calls_fixture_path))


# ──────────────────────────────────────────────
# Parser metadata
# ──────────────────────────────────────────────


class TestJSParserMetadata:
    """Tests for parser properties and can_parse."""

    def test_language_property(self, parser: JavaScriptParser) -> None:
        """language property returns 'javascript'."""
        assert parser.language == "javascript"

    def test_extensions(self, parser: JavaScriptParser) -> None:
        """extensions includes .js, .jsx, .ts, .tsx."""
        exts = parser.extensions
        assert ".js" in exts
        assert ".ts" in exts
        assert ".jsx" in exts
        assert ".tsx" in exts

    def test_can_parse_js(self, parser: JavaScriptParser) -> None:
        """can_parse returns True for .js files."""
        assert parser.can_parse("src/app.js")

    def test_can_parse_ts(self, parser: JavaScriptParser) -> None:
        """can_parse returns True for .ts files."""
        assert parser.can_parse("src/app.ts")

    def test_can_parse_jsx(self, parser: JavaScriptParser) -> None:
        """can_parse returns True for .jsx files."""
        assert parser.can_parse("src/App.jsx")

    def test_can_parse_tsx(self, parser: JavaScriptParser) -> None:
        """can_parse returns True for .tsx files."""
        assert parser.can_parse("src/App.tsx")

    def test_cannot_parse_py(self, parser: JavaScriptParser) -> None:
        """can_parse returns False for .py files."""
        assert not parser.can_parse("src/app.py")


# ──────────────────────────────────────────────
# JavaScript language label
# ──────────────────────────────────────────────


class TestJSLanguageLabel:
    """Tests for language assignment based on file extension."""

    def test_js_file_nodes_have_javascript_language(self, parsed_js) -> None:
        """Nodes from a .js file carry language='javascript'."""
        nodes, _ = parsed_js
        non_file = [n for n in nodes if n.kind != NodeKind.FILE]
        assert all(n.language == "javascript" for n in non_file)

    def test_ts_file_nodes_have_typescript_language(self, parsed_ts_calls) -> None:
        """Nodes from a .ts file carry language='typescript'."""
        nodes, _ = parsed_ts_calls
        non_file = [n for n in nodes if n.kind != NodeKind.FILE]
        assert all(n.language == "typescript" for n in non_file)


# ──────────────────────────────────────────────
# CommonJS require() imports
# ──────────────────────────────────────────────


class TestCommonJSImports:
    """Tests for IMPORTS_FROM edges from require() calls."""

    def test_require_creates_imports_from_edge(self, parsed_js) -> None:
        """const x = require('path') creates an IMPORTS_FROM edge."""
        _, edges = parsed_js
        import_targets = {e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM}
        assert "path" in import_targets

    def test_multiple_requires_create_edges(self, parsed_js) -> None:
        """Two require() calls create two IMPORTS_FROM edges."""
        _, edges = parsed_js
        import_targets = {e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM}
        assert "path" in import_targets
        assert "fs" in import_targets

    def test_require_inline_snippet(self, tmp_path: Path) -> None:
        """Inline: const db = require('./db') creates IMPORTS_FROM './db'."""
        f = tmp_path / "cjs.js"
        f.write_text("const db = require('./db');\n", encoding="utf-8")
        _, edges = JavaScriptParser().parse(str(f))
        import_targets = {e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM}
        assert "./db" in import_targets


# ──────────────────────────────────────────────
# Arrow functions
# ──────────────────────────────────────────────


class TestArrowFunctions:
    """Tests for FUNCTION nodes extracted from arrow function declarations."""

    def test_arrow_fn_extracted_as_function_node(self, parsed_js) -> None:
        """const greet = (name) => {} is extracted as a FUNCTION node."""
        nodes, _ = parsed_js
        func_names = {n.name for n in nodes if n.kind == NodeKind.FUNCTION}
        assert "greet" in func_names

    def test_arrow_fn_has_contains_edge(self, parsed_js) -> None:
        """Arrow function produces a CONTAINS edge from the file node."""
        _, edges = parsed_js
        contains_targets = {e.target for e in edges if e.kind == EdgeKind.CONTAINS}
        assert any("greet" in t for t in contains_targets)

    def test_arrow_fn_language_matches_file(self, parsed_js) -> None:
        """Arrow function node carries the correct language label."""
        nodes, _ = parsed_js
        greet = next(n for n in nodes if n.name == "greet")
        assert greet.language == "javascript"

    def test_ts_arrow_fn_extracted(self, parsed_ts_calls) -> None:
        """const pipeline = (input) => {} in a .ts file is extracted as FUNCTION."""
        nodes, _ = parsed_ts_calls
        func_names = {n.name for n in nodes if n.kind == NodeKind.FUNCTION}
        assert "pipeline" in func_names


# ──────────────────────────────────────────────
# Arrow function CALLS extraction
# ──────────────────────────────────────────────


class TestArrowFunctionCalls:
    """Tests for CALLS edges inside arrow function bodies."""

    def test_arrow_fn_calls_resolved(self, parsed_ts_calls) -> None:
        """pipeline() calls helper() — should produce a CALLS edge."""
        _, edges = parsed_ts_calls
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert any("pipeline" in e.source and "helper" in e.target for e in calls)

    def test_arrow_fn_calls_in_js(self, tmp_path: Path) -> None:
        """Arrow function in JS calling a named function generates CALLS edge."""
        f = tmp_path / "arrow_calls.js"
        f.write_text(
            "function greet(name) { return name; }\n"
            "const main = () => { return greet('world'); };\n",
            encoding="utf-8",
        )
        _, edges = JavaScriptParser().parse(str(f))
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert any("main" in e.source and "greet" in e.target for e in calls)


# ──────────────────────────────────────────────
# Intra-class this.method() CALLS (TypeScript)
# ──────────────────────────────────────────────


class TestTSIntraClassCalls:
    """Tests for CALLS edges from this.method() inside TypeScript classes."""

    def test_this_validate_call_creates_edge(self, parsed_ts_calls) -> None:
        """process() calls this.validate() → CALLS edge process→validate."""
        _, edges = parsed_ts_calls
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert any("process" in e.source and "validate" in e.target for e in calls)

    def test_this_transform_call_creates_edge(self, parsed_ts_calls) -> None:
        """process() calls this.transform() → CALLS edge process→transform."""
        _, edges = parsed_ts_calls
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert any("process" in e.source and "transform" in e.target for e in calls)

    def test_function_to_function_call(self, parsed_ts_calls) -> None:
        """main() calls helper() → CALLS edge main→helper."""
        _, edges = parsed_ts_calls
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert any("main" in e.source and "helper" in e.target for e in calls)


# ──────────────────────────────────────────────
# JS class extends (class heritage)
# ──────────────────────────────────────────────


class TestJSClassHeritage:
    """Tests for INHERITS edges from JS class extends clauses."""

    def test_extends_creates_inherits_edge(self, parsed_js) -> None:
        """class Dog extends Animal creates an INHERITS edge."""
        _, edges = parsed_js
        inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
        assert len(inherits) >= 1

    def test_extends_target_is_base_class(self, parsed_js) -> None:
        """INHERITS edge target is 'Animal'."""
        _, edges = parsed_js
        inherits_targets = {e.target for e in edges if e.kind == EdgeKind.INHERITS}
        assert "Animal" in inherits_targets

    def test_extends_source_contains_dog(self, parsed_js) -> None:
        """INHERITS edge source contains 'Dog'."""
        _, edges = parsed_js
        inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
        assert any("Dog" in e.source for e in inherits)


# ──────────────────────────────────────────────
# Miscellaneous inline JS/TS snippets
# ──────────────────────────────────────────────


class TestJSInlineSnippets:
    """Tests for small inline JS/TS programs."""

    def test_empty_file_produces_only_file_node(self, tmp_path: Path) -> None:
        """An empty .ts file produces exactly one File node and no edges."""
        f = tmp_path / "empty.ts"
        f.write_text("", encoding="utf-8")
        nodes, edges = JavaScriptParser().parse(str(f))
        assert len([n for n in nodes if n.kind == NodeKind.FILE]) == 1
        assert edges == []

    def test_es_import_creates_edge(self, tmp_path: Path) -> None:
        """import { x } from 'module' creates an IMPORTS_FROM edge."""
        f = tmp_path / "esm.ts"
        f.write_text("import { readFile } from 'fs';\n", encoding="utf-8")
        _, edges = JavaScriptParser().parse(str(f))
        import_targets = {e.target for e in edges if e.kind == EdgeKind.IMPORTS_FROM}
        assert "fs" in import_targets

    def test_class_method_nodes_extracted(self, tmp_path: Path) -> None:
        """Methods inside a TS class are extracted as METHOD nodes."""
        f = tmp_path / "cls.ts"
        f.write_text(
            "class Svc {\n" "    run(): void {}\n" "    stop(): void {}\n" "}\n",
            encoding="utf-8",
        )
        nodes, _ = JavaScriptParser().parse(str(f))
        method_names = {n.name for n in nodes if n.kind == NodeKind.METHOD}
        assert "run" in method_names
        assert "stop" in method_names

    def test_caller_class_same_method_resolved(self, tmp_path: Path) -> None:
        """Identifier call inside class resolves to same-class method via caller_class."""
        f = tmp_path / "sameclass.ts"
        f.write_text(
            "class Svc {\n" "    run(): void { this.stop(); }\n" "    stop(): void {}\n" "}\n",
            encoding="utf-8",
        )
        _, edges = JavaScriptParser().parse(str(f))
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert any("run" in e.source and "stop" in e.target for e in calls)
