"""Tests for USES_TYPE weight in compute_metrics."""

from __future__ import annotations

import pytest

from debtector.graph_store import GraphStore
from debtector.metrics import USES_TYPE_WEIGHT, compute_metrics
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


class TestUsesTypeWeight:
    """USES_TYPE edges contribute USES_TYPE_WEIGHT (1.0) to Ce."""

    def test_uses_type_weight_constant(self) -> None:
        """USES_TYPE_WEIGHT is 1.0."""
        assert USES_TYPE_WEIGHT == 1.0

    def test_uses_type_adds_to_fan_out(self, tmp_db: GraphStore) -> None:
        """A USES_TYPE edge increases Ce by 1.0."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_uses_type("src/a.py", "User")],
        )

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].fan_out == pytest.approx(1.0)

    def test_imports_from_weight_one(self, tmp_db: GraphStore) -> None:
        """An IMPORTS_FROM edge still contributes 1.0 to Ce."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_import("src/a.py", "flask")],
        )

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].fan_out == pytest.approx(1.0)

    def test_mixed_edges_sum_correctly(self, tmp_db: GraphStore) -> None:
        """1 IMPORTS_FROM + 2 USES_TYPE = Ce of 3.0."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [
                _import("src/a.py", "flask"),
                _uses_type("src/a.py", "User"),
                _uses_type("src/a.py", "Response"),
            ],
        )

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        # 1 * 1.0 + 2 * 1.0 = 3.0
        assert metrics["src/a.py"].fan_out == pytest.approx(3.0)

    def test_uses_type_instability_effect(self, tmp_db: GraphStore) -> None:
        """USES_TYPE contributes to instability via Ce."""
        # src/a.py has only USES_TYPE (Ce=1.0, Ca=0) → I=1.0
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_uses_type("src/a.py", "User")],
        )

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].instability == pytest.approx(1.0)

    def test_no_uses_type_no_change(self, tmp_db: GraphStore) -> None:
        """Files without USES_TYPE edges are unaffected."""
        tmp_db.store_file(
            "src/a.py",
            [_file("src/a.py")],
            [_import("src/a.py", "src/b.py")],
        )
        tmp_db.store_file("src/b.py", [_file("src/b.py")], [])

        metrics = {m.file_path: m for m in compute_metrics(tmp_db)}
        assert metrics["src/a.py"].fan_out == pytest.approx(1.0)
        assert metrics["src/b.py"].fan_in == pytest.approx(1.0)
