"""Tests for metrics.py — coupling analysis (Ca, Ce, instability)."""

from __future__ import annotations

import pytest

from debtector.graph_store import GraphStore
from debtector.metrics import ModuleMetrics, compute_metrics
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _file(path: str) -> NodeInfo:
    """Create a minimal File NodeInfo."""
    return NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
        language="python",
    )


def _import(source: str, target: str) -> EdgeInfo:
    """Create an IMPORTS_FROM EdgeInfo."""
    return EdgeInfo(
        kind=EdgeKind.IMPORTS_FROM,
        source=source,
        target=target,
        file_path=source,
        line=1,
    )


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────


class TestComputeMetrics:
    """Unit tests for compute_metrics()."""

    def test_empty_store_returns_empty_list(self, tmp_db: GraphStore) -> None:
        """An empty index returns no metrics."""
        assert compute_metrics(tmp_db) == []

    def test_isolated_module_has_zero_coupling(self, tmp_db: GraphStore) -> None:
        """A file with no imports and no dependents has Ca=0, Ce=0, I=0.0."""
        tmp_db.store_file("src/alone.py", [_file("src/alone.py")], [])

        metrics = compute_metrics(tmp_db)
        assert len(metrics) == 1
        row = metrics[0]
        assert row.file_path == "src/alone.py"
        assert row.fan_in == 0
        assert row.fan_out == 0
        assert row.instability == 0.0

    def test_fan_out_counts_internal_imports(self, tmp_db: GraphStore) -> None:
        """Ce counts IMPORTS_FROM edges leaving the file (internal)."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_import("src/a.py", "src/b.py")],
        )
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].fan_out == 1
        assert metrics["src/b.py"].fan_out == 0

    def test_fan_out_counts_external_imports(self, tmp_db: GraphStore) -> None:
        """Ce also counts imports of external packages (e.g. 'flask')."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [
                _import("src/a.py", "src/b.py"),
                _import("src/a.py", "flask"),
            ],
        )
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].fan_out == 2

    def test_fan_in_counts_incoming_imports(self, tmp_db: GraphStore) -> None:
        """Ca counts how many files import this one."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_import("src/a.py", "src/shared.py")],
        )
        tmp_db.store_file(
            "src/b.py",
            [_file("src/b.py")],
            [_import("src/b.py", "src/shared.py")],
        )
        tmp_db.store_file("src/shared.py", [_file("src/shared.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/shared.py"].fan_in == 2
        assert metrics["src/shared.py"].fan_out == 0
        assert metrics["src/a.py"].fan_in == 0
        assert metrics["src/b.py"].fan_in == 0

    def test_instability_fully_unstable(self, tmp_db: GraphStore) -> None:
        """I=1.0 when Ca=0 and Ce>0 (only imports, nobody depends on it)."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_import("src/a.py", "src/b.py")],
        )
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].instability == 1.0

    def test_instability_fully_stable(self, tmp_db: GraphStore) -> None:
        """I=0.0 when Ce=0 and Ca>0 (others depend on it, imports nothing)."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_import("src/a.py", "src/b.py")],
        )
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/b.py"].instability == 0.0

    def test_instability_formula(self, tmp_db: GraphStore) -> None:
        """I = Ce / (Ca + Ce) for mixed coupling."""
        # a→c, b→c, c→d  →  c: Ca=2, Ce=1, I=1/3
        tmp_db.store_file("src/a.py", [_file("src/a.py")], [_import("src/a.py", "src/c.py")])
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [_import("src/b.py", "src/c.py")])
        tmp_db.store_file("src/c.py", [_file("src/c.py")], [_import("src/c.py", "src/d.py")])
        tmp_db.store_file("src/d.py", [_file("src/d.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        c = metrics["src/c.py"]
        assert c.fan_in == 2
        assert c.fan_out == 1
        assert c.instability == pytest.approx(1 / 3)

    def test_returns_one_entry_per_file(self, tmp_db: GraphStore) -> None:
        """compute_metrics returns exactly one ModuleMetrics per indexed file."""
        for p in ["src/x.py", "src/y.py", "src/z.py"]:
            tmp_db.store_file(p, [_file(p)], [])

        metrics = compute_metrics(tmp_db)
        paths = {m.file_path for m in metrics}
        assert paths == {"src/x.py", "src/y.py", "src/z.py"}

    def test_result_type(self, tmp_db: GraphStore) -> None:
        """Each result is a ModuleMetrics dataclass instance."""
        tmp_db.store_file("src/a.py", [_file("src/a.py")], [])
        metrics = compute_metrics(tmp_db)
        assert isinstance(metrics[0], ModuleMetrics)
