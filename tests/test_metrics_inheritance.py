"""Tests for inheritance depth and children count in metrics.py."""

from __future__ import annotations

from codeindex.graph_store import GraphStore
from codeindex.metrics import InheritanceMetrics, inheritance_metrics
from codeindex.models import EdgeInfo, EdgeKind, NodeInfo, NodeKind

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _class(file: str, name: str, parent: str | None = None) -> NodeInfo:
    return NodeInfo(
        kind=NodeKind.CLASS,
        name=name,
        qualified_name=f"{file}::{name}",
        file_path=file,
        language="python",
        parent_name=parent,
    )


def _inherits(file: str, child: str, parent: str) -> EdgeInfo:
    """INHERITS edge: child → parent (child extends parent)."""
    return EdgeInfo(
        kind=EdgeKind.INHERITS,
        source=f"{file}::{child}",
        target=f"{file}::{parent}",
        file_path=file,
        line=1,
    )


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────


class TestInheritanceMetrics:
    """Unit tests for inheritance_metrics()."""

    def test_empty_store_returns_empty(self, tmp_db: GraphStore) -> None:
        """No classes → no inheritance metrics."""
        assert inheritance_metrics(tmp_db) == []

    def test_root_class_depth_zero(self, tmp_db: GraphStore) -> None:
        """A class that inherits from nothing has depth=0 and children=0."""
        tmp_db.store_file(
            "src/a.py",
            [_class("src/a.py", "Base")],
            [],
        )

        metrics = inheritance_metrics(tmp_db)
        assert len(metrics) == 1
        m = metrics[0]
        assert m.qualified_name == "src/a.py::Base"
        assert m.depth == 0
        assert m.children == 0

    def test_single_level_inheritance(self, tmp_db: GraphStore) -> None:
        """Child depth=1, parent depth=0; parent has 1 child."""
        tmp_db.store_file(
            "src/a.py",
            [_class("src/a.py", "Base"), _class("src/a.py", "Child", "Base")],
            [_inherits("src/a.py", "Child", "Base")],
        )

        metrics = {m.qualified_name: m for m in inheritance_metrics(tmp_db)}
        assert metrics["src/a.py::Base"].depth == 0
        assert metrics["src/a.py::Base"].children == 1
        assert metrics["src/a.py::Child"].depth == 1
        assert metrics["src/a.py::Child"].children == 0

    def test_two_level_chain(self, tmp_db: GraphStore) -> None:
        """Base→Child→GrandChild: depths 0, 1, 2."""
        tmp_db.store_file(
            "src/a.py",
            [
                _class("src/a.py", "Base"),
                _class("src/a.py", "Child", "Base"),
                _class("src/a.py", "GrandChild", "Child"),
            ],
            [
                _inherits("src/a.py", "Child", "Base"),
                _inherits("src/a.py", "GrandChild", "Child"),
            ],
        )

        metrics = {m.qualified_name: m for m in inheritance_metrics(tmp_db)}
        assert metrics["src/a.py::Base"].depth == 0
        assert metrics["src/a.py::Child"].depth == 1
        assert metrics["src/a.py::GrandChild"].depth == 2

    def test_multiple_children(self, tmp_db: GraphStore) -> None:
        """A class with multiple direct children counts all of them."""
        tmp_db.store_file(
            "src/a.py",
            [
                _class("src/a.py", "Base"),
                _class("src/a.py", "ChildA", "Base"),
                _class("src/a.py", "ChildB", "Base"),
                _class("src/a.py", "ChildC", "Base"),
            ],
            [
                _inherits("src/a.py", "ChildA", "Base"),
                _inherits("src/a.py", "ChildB", "Base"),
                _inherits("src/a.py", "ChildC", "Base"),
            ],
        )

        metrics = {m.qualified_name: m for m in inheritance_metrics(tmp_db)}
        assert metrics["src/a.py::Base"].children == 3

    def test_cross_file_inheritance(self, tmp_db: GraphStore) -> None:
        """Inheritance across files is tracked correctly."""
        tmp_db.store_file("src/base.py", [_class("src/base.py", "Base")], [])
        tmp_db.store_file(
            "src/child.py",
            [_class("src/child.py", "Child", "Base")],
            [
                EdgeInfo(
                    kind=EdgeKind.INHERITS,
                    source="src/child.py::Child",
                    target="src/base.py::Base",
                    file_path="src/child.py",
                    line=1,
                )
            ],
        )

        metrics = {m.qualified_name: m for m in inheritance_metrics(tmp_db)}
        assert metrics["src/base.py::Base"].children == 1
        assert metrics["src/child.py::Child"].depth == 1

    def test_returns_inheritance_metrics_instances(self, tmp_db: GraphStore) -> None:
        """Each result is an InheritanceMetrics dataclass."""
        tmp_db.store_file("src/a.py", [_class("src/a.py", "Base")], [])

        result = inheritance_metrics(tmp_db)
        assert isinstance(result[0], InheritanceMetrics)

    def test_cyclic_inheritance_does_not_recurse_infinitely(self, tmp_db: GraphStore) -> None:
        """Circular inheritance (A→B→A) is cut by the visited guard; no RecursionError."""
        tmp_db.store_file(
            "src/a.py",
            [_class("src/a.py", "A"), _class("src/a.py", "B")],
            [
                _inherits("src/a.py", "A", "B"),
                _inherits("src/a.py", "B", "A"),
            ],
        )

        # Must not raise; exact depths are implementation-defined for cyclic graphs
        result = {m.qualified_name: m for m in inheritance_metrics(tmp_db)}
        assert "src/a.py::A" in result
        assert "src/a.py::B" in result
        # Both have finite depth (cycle is cut)
        assert result["src/a.py::A"].depth >= 0
        assert result["src/a.py::B"].depth >= 0
