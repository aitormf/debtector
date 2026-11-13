"""Tests: USES_TYPE edges do not count in Ca/Ce (R3, D-0012)."""

from __future__ import annotations

import pytest

from debtector.graph_store import GraphStore
from debtector.metrics import METRICS_VERSION, compute_metrics
from debtector.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind


def _file(path: str) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.FILE,
        name=path.split("/")[-1],
        qualified_name=path,
        file_path=path,
        language="python",
    )


def _import(source: str, target: str) -> EdgeInfo:
    return EdgeInfo(
        kind=EdgeKind.IMPORTS_FROM,
        source=source,
        target=target,
        file_path=source,
        line=1,
    )


def _uses_type(source: str, target: str) -> EdgeInfo:
    return EdgeInfo(
        kind=EdgeKind.USES_TYPE,
        source=source,
        target=target,
        file_path=source,
        line=1,
    )


class TestUsesTypeDoesNotCount:
    """Type annotations add nothing to Ca/Ce: the import already counts its module."""

    def test_E10_annotations_with_internal_import(self, tmp_db: GraphStore) -> None:
        """Import of models plus 3 annotations: Ce(a) = 1, Ca(models) = 1."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [
                _import("src/a.py", "src/models.py"),
                _uses_type("src/a.py", "Path"),
                _uses_type("src/a.py", "NodeInfo"),
                _uses_type("src/a.py", "src/models.py::NodeInfo"),
            ],
        )
        tmp_db.store_file("src/models.py", [_file("src/models.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].fan_out == pytest.approx(1.0)
        assert metrics["src/models.py"].fan_in == pytest.approx(1.0)

    def test_E11_annotations_without_internal_imports(self, tmp_db: GraphStore) -> None:
        """Annotations only: Ce(a) = 0, Ca = 0, I = 0."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_uses_type("src/a.py", "User"), _uses_type("src/a.py", "Response")],
        )

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].fan_out == pytest.approx(0.0)
        assert metrics["src/a.py"].fan_in == pytest.approx(0.0)
        assert metrics["src/a.py"].instability == pytest.approx(0.0)

    def test_E11_uses_type_to_indexed_file_gives_no_ca(self, tmp_db: GraphStore) -> None:
        """A USES_TYPE edge whose target is an indexed file adds no Ca."""
        tmp_db.store_file("src/a.py", [_file("src/a.py")], [_uses_type("src/a.py", "src/b.py")])
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/b.py"].fan_in == pytest.approx(0.0)

    def test_E12_metrics_version_is_3(self) -> None:
        """The metric changed: baselines of version 2 are incomparable (D-0014)."""
        assert METRICS_VERSION >= 3  # bumped to 4 by T4 (E16)
