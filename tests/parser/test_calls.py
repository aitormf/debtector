"""Tests for CALLS edge extraction in Python and JavaScript/TypeScript parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeindex.models import EdgeKind
from codeindex.parser.js_parser import JavaScriptParser
from codeindex.parser.python_parser import PythonParser

FIXTURES = Path(__file__).parent.parent / "fixtures"
PY_SAMPLE = str(FIXTURES / "calls_sample.py")
TS_SAMPLE = str(FIXTURES / "calls_sample.ts")


# ──────────────────────────────────────────────
# Python CALLS
# ──────────────────────────────────────────────


@pytest.fixture()
def py_calls():
    """Parse calls_sample.py and return (nodes, edges)."""
    return PythonParser().parse(PY_SAMPLE)


def _calls(edges):
    """Filter only CALLS edges and return (source_suffix, target_suffix) tuples."""
    return [
        (e.source.split("::")[-1], e.target.split("::")[-1])
        for e in edges
        if e.kind == EdgeKind.CALLS
    ]


class TestPythonCalls:
    """CALLS edges extracted from calls_sample.py."""

    def test_has_calls_edges(self, py_calls) -> None:
        _, edges = py_calls
        assert any(e.kind == EdgeKind.CALLS for e in edges)

    def test_main_calls_helper(self, py_calls) -> None:
        """main() calls helper() — plain function call."""
        _, edges = py_calls
        pairs = _calls(edges)
        assert ("main", "helper") in pairs

    def test_process_calls_validate(self, py_calls) -> None:
        """Service.process calls self.validate() — intra-class self call."""
        _, edges = py_calls
        pairs = _calls(edges)
        assert ("Service.process", "Service.validate") in pairs

    def test_process_calls_transform(self, py_calls) -> None:
        """Service.process calls self.transform() — intra-class self call."""
        _, edges = py_calls
        pairs = _calls(edges)
        assert ("Service.process", "Service.transform") in pairs

    def test_no_self_calls(self, py_calls) -> None:
        """A function should not emit a CALLS edge to itself."""
        _, edges = py_calls
        for e in edges:
            if e.kind == EdgeKind.CALLS:
                assert e.source != e.target

    def test_calls_have_line_numbers(self, py_calls) -> None:
        """CALLS edges carry a non-zero line number."""
        _, edges = py_calls
        for e in edges:
            if e.kind == EdgeKind.CALLS:
                assert e.line > 0

    def test_calls_targets_are_known_symbols(self, py_calls) -> None:
        """All CALLS edge targets correspond to a node qualified_name in the file."""
        nodes, edges = py_calls
        known_qns = {n.qualified_name for n in nodes}
        for e in edges:
            if e.kind == EdgeKind.CALLS:
                assert e.target in known_qns, f"Unresolved CALLS target: {e.target}"

    def test_pipeline_run_calls_service_constructor(self, py_calls) -> None:
        """Pipeline.run calls Service() — class constructor call."""
        _, edges = py_calls
        pairs = _calls(edges)
        assert ("Pipeline.run", "Service") in pairs


# ──────────────────────────────────────────────
# TypeScript CALLS
# ──────────────────────────────────────────────


@pytest.fixture()
def ts_calls():
    """Parse calls_sample.ts and return (nodes, edges)."""
    return JavaScriptParser().parse(TS_SAMPLE)


class TestTypeScriptCalls:
    """CALLS edges extracted from calls_sample.ts."""

    def test_has_calls_edges(self, ts_calls) -> None:
        _, edges = ts_calls
        assert any(e.kind == EdgeKind.CALLS for e in edges)

    def test_main_calls_helper(self, ts_calls) -> None:
        """main() calls helper() — plain function call."""
        _, edges = ts_calls
        pairs = _calls(edges)
        assert ("main", "helper") in pairs

    def test_process_calls_validate(self, ts_calls) -> None:
        """Service.process calls this.validate() — intra-class this call."""
        _, edges = ts_calls
        pairs = _calls(edges)
        assert ("Service.process", "Service.validate") in pairs

    def test_process_calls_transform(self, ts_calls) -> None:
        """Service.process calls this.transform() — intra-class this call."""
        _, edges = ts_calls
        pairs = _calls(edges)
        assert ("Service.process", "Service.transform") in pairs

    def test_no_self_calls(self, ts_calls) -> None:
        _, edges = ts_calls
        for e in edges:
            if e.kind == EdgeKind.CALLS:
                assert e.source != e.target

    def test_calls_targets_are_known_symbols(self, ts_calls) -> None:
        nodes, edges = ts_calls
        known_qns = {n.qualified_name for n in nodes}
        for e in edges:
            if e.kind == EdgeKind.CALLS:
                assert e.target in known_qns, f"Unresolved CALLS target: {e.target}"
